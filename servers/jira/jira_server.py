from typing import Dict, Any, Optional
import os
from fastmcp import FastMCP
from jira import JIRA, JIRAError

mcp = FastMCP(name="jira-tools")

JIRA_SERVER = os.getenv("JIRA_SERVER")  # e.g. https://your-domain.atlassian.net
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
if not (JIRA_SERVER and JIRA_EMAIL and JIRA_API_TOKEN):
    raise RuntimeError("JIRA_SERVER, JIRA_EMAIL, JIRA_API_TOKEN required in env")

jira_client = JIRA(server=JIRA_SERVER, basic_auth=(JIRA_EMAIL, JIRA_API_TOKEN))

@mcp.tool()
def create_issue(project_key: str, summary: str, description: str, issuetype: str = "Task", extra_fields: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    fields = {
        "project": {"key": project_key},
        "summary": summary,
        "description": description,
        "issuetype": {"name": issuetype},
    }
    if extra_fields:
        fields.update(extra_fields)
    try:
        issue = jira_client.create_issue(fields=fields)
        return {"key": issue.key, "url": f"{JIRA_SERVER}/browse/{issue.key}"}
    except JIRAError as e:
        raise RuntimeError(f"Failed to create Jira issue: {e}")

if __name__ == "__main__":
    mcp.run(
    transport="http",
    host="0.0.0.0",
    port=8003
)
