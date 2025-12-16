from typing import Optional, Dict, Any, List
import os
import time
from fastmcp import FastMCP

# HTTP client
import requests
from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v2.api.incidents_api import IncidentsApi
from dateutil import parser as _dt_parser

mcp = FastMCP(name="incident-tools")

# --- Datadog ---
@mcp.tool()
def get_latest_datadog_incident(since_unix_ts: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """
    Return the most recent Datadog incident (dict) optionally after since_unix_ts (epoch secs).
    Requires DD_API_KEY & DD_APP_KEY in env or Datadog credentials provided via env.
    """
    api_key = os.getenv("DD_API_KEY")
    app_key = os.getenv("DD_APP_KEY")
    if not (api_key and app_key):
        raise RuntimeError("Datadog keys not configured (DD_API_KEY, DD_APP_KEY)")

    cfg = Configuration()
    cfg.api_key["apiKeyAuth"] = api_key
    cfg.api_key["appKeyAuth"] = app_key

    most_recent = None
    with ApiClient(cfg) as client:
        api = IncidentsApi(client)
        for inc in api.list_incidents_with_pagination():
            d = inc.to_dict() if hasattr(inc, "to_dict") else dict(inc)
            attrs = d.get("attributes", {}) or {}
            ts_val = attrs.get("last_modified") or attrs.get("updated_at") or attrs.get("created_at") or attrs.get("created")
            ts = None
            if isinstance(ts_val, (int, float)):
                ts = int(ts_val)
            elif isinstance(ts_val, str):
                try:
                    ts = int(_dt_parser.parse(ts_val).timestamp())
                except Exception:
                    ts = None
            if since_unix_ts and ts and ts < since_unix_ts:
                continue
            if most_recent is None or (ts and most_recent.get("_ts", 0) < ts):
                most_recent = {"incident": d, "_ts": ts or 0}
    if not most_recent:
        return None
    out = most_recent["incident"]
    out["_timestamp"] = most_recent["_ts"]
    return out

# --- Sentry ---
@mcp.tool()
def get_latest_sentry_issue(org_slug: str, project_slug: Optional[str] = None, stats_period: str = "24h") -> Optional[Dict[str, Any]]:
    """
    Return the most recent Sentry issue for an organization (and optional project).
    Requires SENTRY_API_TOKEN in env.
    """
    token = os.getenv("SENTRY_API_TOKEN")
    if not token:
        raise RuntimeError("SENTRY_API_TOKEN not configured")

    base = os.getenv("SENTRY_BASE_URL", "https://sentry.io").rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if project_slug:
        url = f"{base}/api/0/projects/{org_slug}/{project_slug}/issues/"
    else:
        url = f"{base}/api/0/organizations/{org_slug}/issues/"

    params = {"statsPeriod": stats_period, "per_page": 50}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    issues = resp.json() or []
    most_recent = None
    for it in issues:
        last_seen = it.get("lastSeen") or it.get("firstSeen")
        ts = None
        if last_seen:
            try:
                ts = int(_dt_parser.parse(last_seen).timestamp())
            except Exception:
                ts = None
        if most_recent is None or (ts and most_recent.get("_ts", 0) < ts):
            most_recent = {"issue": it, "_ts": ts or 0}
    if not most_recent:
        return None
    out = most_recent["issue"]
    out["_timestamp"] = most_recent["_ts"]
    return out

if __name__ == "__main__":
    mcp.run(port=8001)
