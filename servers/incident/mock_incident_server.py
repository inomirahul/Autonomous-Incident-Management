from fastmcp import FastMCP
from datetime import datetime

mcp = FastMCP("mock-incident")

@mcp.tool()
def get_latest_incident() -> dict:
    return {
        "id": "INC-002",
        "title": "When user to input task description immediate failure",
        "severity": "high",
        "repo": "inomirahul/todo_list",
        "description": (
            "Existing error `todo_app.py`, Users report that after Entering task description, "
            "they gettting error `ZeroDivisionError: division by zero`"
        ),
        "suspected_cause": "Somewhere by fault added division by zero"
    }

if __name__ == "__main__":
    mcp.run(
    transport="http",
    host="0.0.0.0",
    port=8001
)
