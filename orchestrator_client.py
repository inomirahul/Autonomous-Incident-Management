# client/orchestrator_client.py
import os
import time
from fastmcp import Client  # FastMCP client (programmatic)

# configuration: endpoints (if you run servers on different ports)
INCIDENT_SERVER_URL = os.getenv("INCIDENT_MCP_URL", "http://localhost:8001")
GITHUB_SERVER_URL = os.getenv("GITHUB_MCP_URL", "http://localhost:8002")
JIRA_SERVER_URL = os.getenv("JIRA_MCP_URL", "http://localhost:8003")

def run_workflow(source: str = "sentry"):
    # Connect to incident server and fetch latest issue/incident
    with Client(base_url=INCIDENT_SERVER_URL) as incident_client:
        if source == "datadog":
            incident = incident_client.call_tool("get_latest_datadog_incident", {"since_unix_ts": None})
        else:
            # adjust org_slug/project_slug via env or literal - update before run
            org = os.getenv("SENTRY_ORG_SLUG", "your-org")
            proj = os.getenv("SENTRY_PROJECT_SLUG", None)
            incident = incident_client.call_tool("get_latest_sentry_issue", {"org_slug": org, "project_slug": proj, "stats_period": "7d"})

    if not incident:
        raise RuntimeError("No incident found")

    # Search GitHub for candidate code
    repo = os.getenv("TARGET_REPO", "your-org/your-repo")
    query = incident.get("title") or incident.get("transaction") or incident.get("metadata", {}).get("title", "")
    if not query:
        # basic fallback tokens from incident
        query = "error exception traceback"

    with Client(base_url=GITHUB_SERVER_URL) as gh_client:
        search_hits = gh_client.call_tool("search_code", {"repo_full_name": repo, "query": query, "max_results": 5})

    # create Jira ticket
    jira_project = os.getenv("JIRA_PROJECT", "PROJ")
    issue_summary = f"Automated: {incident.get('title') or 'Incident'}"
    description_lines = [
        f"Incident source: {source}",
        f"Summary: {incident.get('title') or incident.get('type', '')}",
        "",
        "Top code search hits:",
    ]
    for h in (search_hits or [])[:10]:
        description_lines.append(f"- {h['repo']}:{h['path']} ({h['html_url']})")
    description = "\n".join(description_lines)

    with Client(base_url=JIRA_SERVER_URL) as jira_client:
        jira_res = jira_client.call_tool("create_issue", {"project_key": jira_project, "summary": issue_summary, "description": description})

    # create branch + commit + PR on GitHub
    new_branch = f"auto/incident-fix-{int(time.time())}"
    file_path = os.getenv("AUTO_PATCH_PATH", "fixes/auto_patch.txt")
    file_content = f"Auto patch for incident: {issue_summary}\nLinked JIRA: {jira_res.get('key')}\n"
    commit_message = f"chore: auto patch for {jira_res.get('key')}"

    with Client(base_url=GITHUB_SERVER_URL) as gh_client:
        commit_res = gh_client.call_tool("create_branch_and_commit", {
            "repo_full_name": repo,
            "base_branch": "main",
            "new_branch": new_branch,
            "file_path": file_path,
            "file_content": file_content,
            "commit_message": commit_message
        })
        pr_body = f"Automated PR to address incident. Linked Jira: {jira_res.get('key')}"
        pr_res = gh_client.call_tool("create_pull_request", {
            "repo_full_name": repo,
            "title": f"[AUTO] Fix for {jira_res.get('key')}",
            "body": pr_body,
            "head_branch": new_branch,
            "base_branch": "main"
        })

    return {
        "incident": incident,
        "search_hits": search_hits,
        "jira": jira_res,
        "commit": commit_res,
        "pr": pr_res
    }

if __name__ == "__main__":
    res = run_workflow(source=os.getenv("INCIDENT_SOURCE", "sentry"))
    print("JIRA:", res["jira"])
    print("PR:", res["pr"])
