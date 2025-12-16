import asyncio
import os
from typing import Any
from fastmcp import Client
from anthropic import AsyncAnthropic

AGENT_ID = "incident-agent-v1"

INCIDENT_SERVER = "http://localhost:8001/mcp"
GITHUB_SERVER   = "http://localhost:8002/mcp"
JIRA_SERVER     = "http://localhost:8003"
MEMORY_SERVER   = "http://localhost:8004/mcp"

api_key = os.getenv("ANTHROPIC_API_KEY")


claude = AsyncAnthropic()

MODEL = "claude-opus-4-5-20251101"

SYSTEM_PROMPT = """
You are an autonomous incident-response engineer.

You must:
- Investigate the most recent incident
- Search relevant code
- Create Jira issues when appropriate
- Create GitHub pull requests when appropriate
- Store incidents, actions, and reflections into memory

Do not ask questions.
Act using tools.
"""

# ======================================================
# Tool dispatch helper
# ======================================================
async def dispatch_tool(
    name: str,
    args: dict[str, Any],
    incident: Client,
    github: Client,
    jira: Client,
    memory: Client,
    incident_tools,
    github_tools,
    jira_tools,
    memory_tools,
):
    if name in incident_tools:
        return await incident.call_tool(name, args), "incident"

    if name in github_tools:
        return await github.call_tool(name, args), "action"

    if name in jira_tools:
        return await jira.call_tool(name, args), "action"

    if name in memory_tools:
        return await memory.call_tool(name, args), None

    raise RuntimeError(f"Unknown tool: {name}")


def mcp_tool_to_claude(tool):
    """
    Convert FastMCP Tool -> Claude tool schema
    """
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema or {
            "type": "object",
            "properties": {},
        },
    }



# ======================================================
# Agent loop
# ======================================================
async def run_agent():
    async with (
        Client(INCIDENT_SERVER) as incident,
        Client(GITHUB_SERVER) as github,
        Client(JIRA_SERVER) as jira,
        Client(MEMORY_SERVER) as memory,
    ):
        # ----------------------------------------------
        # Discover tools (MCP-correct)
        # ----------------------------------------------
        incident_tool_objs = await incident.list_tools()
        github_tool_objs   = await github.list_tools()
        jira_tool_objs     = await jira.list_tools()
        memory_tool_objs   = await memory.list_tools()

        incident_tools = {t.name for t in incident_tool_objs}
        github_tools   = {t.name for t in github_tool_objs}
        jira_tools     = {t.name for t in jira_tool_objs}
        memory_tools   = {t.name for t in memory_tool_objs}

        claude_tools = [
            mcp_tool_to_claude(t)
            for t in (
                github_tool_objs
                + incident_tool_objs
                + jira_tool_objs
                + memory_tool_objs
            )
        ]
        # ----------------------------------------------
        # Recall past memory (symbolic)
        # ----------------------------------------------
        past_memory = await memory.call_tool(
            "recall_memory",
            {
                "agent_id": AGENT_ID,
                "limit": 10,
            },
        )

        system_prompt = SYSTEM_PROMPT + "\n\nPast memory:\n" + str(past_memory)

        messages = [
            {
                "role": "user",
                "content": "Handle the most recent production incident end-to-end."
            }
        ]

        # ----------------------------------------------
        # Autonomous loop
        # ----------------------------------------------
        while True:
            response = await claude.messages.create(
                model=MODEL,
                system=system_prompt,
                messages=messages,
                tools=claude_tools,
                max_tokens=2048,
            )

            # ALWAYS append the assistant message first
            assistant_message = {
                "role": "assistant",
                "content": response.content,
            }
            messages.append(assistant_message)

            # Look for a tool_use in THIS assistant message
            tool_block = None
            for block in response.content:
                if block.type == "tool_use":
                    tool_block = block
                    break

            # ------------------------------------------------
            # Tool path (exactly one tool_use)
            # ------------------------------------------------
            if tool_block:
                tool_name = tool_block.name
                tool_args = tool_block.input

                result, memory_type = await dispatch_tool(
                    tool_name,
                    tool_args,
                    incident,
                    github,
                    jira,
                    memory,
                    incident_tools,
                    github_tools,
                    jira_tools,
                    memory_tools,
                )

                if memory_type:
                    await memory.call_tool(
                        "write_memory",
                        {
                            "agent_id": AGENT_ID,
                            "memory_type": memory_type,
                            "content": {
                                "tool": tool_name,
                                "arguments": tool_args,
                                "result": result,
                            },
                        }
                    )

                # NOW append the tool_result as a USER message
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_block.id,
                                "content": str(result),
                            }
                        ],
                    }
                )

                continue  # go back to Claude with correct state

            # ------------------------------------------------
            # No tool_use → final answer
            # ------------------------------------------------
            final_text = ""
            for block in response.content:
                if block.type == "text":
                    final_text += block.text

            await memory.call_tool(
                "write_memory",
                {
                    "agent_id": AGENT_ID,
                    "memory_type": "reflection",
                    "content": {"summary": final_text},
                }
            )

            print(final_text)
            break
if __name__ == "__main__":
    asyncio.run(run_agent())
