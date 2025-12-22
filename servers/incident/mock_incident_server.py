from fastmcp import FastMCP
from datetime import datetime

mcp = FastMCP("mock-incident")

@mcp.tool()
def get_latest_incident() -> dict:
    return {
        "id": "INC-SEC-PLAINTEXT-CREDS",
        "project": "hermes",
        "title": "Django request logging exposes user passwords in plain text",
        "severity": "critical",
        "category": "security / sensitive-data-exposure",
        "reported_issue": (
            "Application logs contain end-user credentials, including usernames and passwords, "
            "recorded in plain text. These logs are archived to S3 for audit purposes, creating "
            "persistent exposure of sensitive authentication data."
        ),
        "discovery_context": {
            "discovered_on": "2023-06-27",
            "suspected_introduction_date": "2023-06-11",
            "confidence": "Approximate; requires further verification"
        },
        "affected_components": [
            {
                "layer": "backend",
                "framework": "Django",
                "module": "django.request._log"
            },
            {
                "layer": "configuration",
                "file": "hermes/settings/base.py",
                "component": "request_logging.middleware.LoggingMiddleware"
            },
            {
                "layer": "infrastructure",
                "component": "S3 audit log storage"
            }
        ],
        "observed_evidence": {
            "example_log_entry": (
                "06/27/2023 08:55:27 PM DEBUG - django.request._log - "
                "b'{\"email\":\"jhopkinson@artemishealth.com\","
                "\"password\":\"XXXXXX\",\"mfa_token\":742555}'"
            ),
            "note": (
                "Password value masked in example. Original logs contained raw plain-text passwords."
            )
        },
        "execution_context": {
            "operation": "authentication request logging",
            "log_level": "DEBUG",
            "data_logged": [
                "email",
                "password",
                "mfa_token"
            ]
        },
        "impact": {
            "scope": "All users authenticating during affected period",
            "risk": [
                "Credential compromise",
                "Regulatory non-compliance",
                "Long-term exposure due to log archival"
            ],
            "persistence": "Credentials stored in historical logs in S3"
        },
        "suspected_root_cause": (
            "Request logging captures full request payloads without redaction. "
            "LoggingMiddleware likely logs authentication request bodies verbatim, "
            "including sensitive fields such as passwords."
        ),
        "failure_classification": [
            "Sensitive data logged",
            "Missing credential redaction",
            "Unsafe debug logging in production"
        ],
        "diagnostic_references": {
            "primary_suspect": "request_logging.middleware.LoggingMiddleware",
            "location": "hermes/settings/base.py",
            "signal": "Presence of password fields in django.request debug logs"
        },
        "resolution_hint": (
            "Audit request logging paths for credential handling, remove or hard-disable "
            "LoggingMiddleware for authentication routes, and enforce field-level redaction "
            "before any request data is written to logs."
        )
    }

if __name__ == "__main__":
    mcp.run(
    transport="http",
    host="0.0.0.0",
    port=8001
)
