from fastmcp import FastMCP
from datetime import datetime

mcp = FastMCP("mock-incident")

@mcp.tool()
def get_latest_incident() -> dict:
    return {
    "id": "INC-101",
    "title": "ImpersonateMiddleware raises Resolver404 on unmatched URL causing 500",
    "severity": "high",
    "description": (
    "Middleware ImpersonateMiddleware.is_allowed_post_url calls resolve(request.path_info) "
    "without handling Django's Resolver404. When a request path does not match any URL pattern, "
    "Django raises django.urls.exceptions.Resolver404, which is not caught by the middleware and "
    "bubbles up as a 500 server error. Example observed error: "
    "django.urls.exceptions.Resolver404: '/api/unknown/': URLconf ... could not resolve "
    "with stack trace originating from ImpersonateMiddleware.is_allowed_post_url."
    ),
    "suspected_cause": "Calling resolve() directly without catching Resolver404 (or otherwise validating the path) allows unmatched paths to raise an uncaught exception, producing a 500 error."
    }

if __name__ == "__main__":
    mcp.run(
    transport="http",
    host="0.0.0.0",
    port=8001
)
