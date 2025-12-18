import asyncio
import os
import time
import logging
from typing import Any

from fastmcp import Client
from anthropic import AsyncAnthropic

# ======================================================
# Logging (reach-safe)
# ======================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("incident-agent")

# ======================================================
# Configuration
# ======================================================
AGENT_ID = "incident-agent-v1"

INCIDENT_SERVER = os.getenv("INCIDENT_SERVER")
GITHUB_SERVER   = os.getenv("GITHUB_SERVER")
JIRA_SERVER     = os.getenv("JIRA_SERVER")
MEMORY_SERVER   = os.getenv("MEMORY_SERVER")
CODE_INDEX_SERVER = os.getenv("CODE_INDEX_SERVER")
EDITOR_SERVER   = os.getenv("EDITOR_SERVER")
SHELL_SERVER    = os.getenv("SHELL_SERVER")

MODEL = "claude-opus-4-5-20251101"

SYSTEM_PROMPT = """
You are an autonomous incident-response agent.

## Hard Execution Limits
- Maximum internal reasoning time: 60 seconds.
- If a solution is not reached within this bound, terminate immediately.
- On termination, respond only with a concise explanation of why the task cannot be completed.
- Do not continue analysis, exploration, or tool usage after the limit.
- Do not attempt partial solutions beyond the limit.
- Must exit after task completion.

## Failure Mode
- If required information, access, or determinism is insufficient, exit immediately.
- Failure responses must describe the blocking constraint, not speculation.
- No fallback reasoning, retries, or alternative exploration.

## Directives

1. Investigate the incident
2. Search relevant code
3. Apply minimal fix but make sure changes in all relevant files
4. Create Jira issue for tracking if appropriate tools are available
5. Create GitHub Pull request with clear branch name, clear commit message, clear title, and description
6. Persist incident, actions, and reflections to memory
7. Exit after task completion without further analysis.

## Constraints

- Do not ask questions
- Do not speculate beyond the code
- Act only through tools when action is required
- Focus on factual structure
- Never delete files; document removals in PR description instead
- Make minimal required changes only
"""

claude = AsyncAnthropic()

log.info("startup", extra={
    "agent_id": AGENT_ID,
    "incident_server": INCIDENT_SERVER,
    # "github_server": GITHUB_SERVER
    "jira_server": JIRA_SERVER,
    "memory_server": MEMORY_SERVER,
    "code_index_server": CODE_INDEX_SERVER,
    "editor_server": EDITOR_SERVER,
    "shell_server": SHELL_SERVER,
    "model": MODEL,
})

# ======================================================
# Tool dispatch helper
# ======================================================
async def dispatch_tool(
    name: str,
    tool_args: dict[str, Any],
    incident: Client,
    # github: Client,
    memory: Client,
    code_index: Client,
    editor: Client,
    shell: Client,
    incident_tools,
    # github_tools,
    memory_tools,
    code_index_tools,
    editor_tools,
    shell_tools,
):
    log.info("tool.dispatch", extra={
        "tool": name,
        "tool_args": tool_args,
    })

    if name in incident_tools:
        result = await incident.call_tool(name, tool_args)
        log.info("tool.result", extra={
            "tool": name,
            "domain": "incident",
            "tool_result": str(result),
        })
        return result, "incident"

    # if name in github_tools:
    #     result = await github.call_tool(name, tool_args)
    #     log.info("tool.result", extra={
    #         "tool": name,
    #         "domain": "github",
    #         "tool_result": str(result),
    #     })
    #     return result, "action"

    if name in memory_tools:
        result = await memory.call_tool(name, tool_args)
        log.info("tool.result", extra={
            "tool": name,
            "domain": "memory",
            "tool_result": str(result),
        })
        return result, None

    if name in code_index_tools:
        result = await code_index.call_tool(name, tool_args)
        log.info("tool.result", extra={
            "tool": name,
            "domain": "code_index",
            "tool_result": str(result),
        })
        return result, None

    if name in editor_tools:
        result = await editor.call_tool(name, tool_args)
        log.info("tool.result", extra={
            "tool": name,
            "domain": "editor",
            "tool_result": str(result),
        })
        return result, None

    if name in shell_tools:
        result = await shell.call_tool(name, tool_args)
        log.info("tool.result", extra={
            "tool": name,
            "domain": "shell",
            "tool_result": str(result),
        })
        return result, None

    log.error("tool.unknown", extra={"tool": name})
    raise RuntimeError(f"Unknown tool: {name}")

# ======================================================
# MCP → Claude tool conversion
# ======================================================
def mcp_tool_to_claude(tool):
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
        # Client(GITHUB_SERVER) as github,
        Client(MEMORY_SERVER) as memory,
        Client(CODE_INDEX_SERVER) as code_index,
        Client(EDITOR_SERVER) as editor,
        Client(SHELL_SERVER) as shell,
    ):
        # ----------------------------------------------
        # Discover tools
        # ----------------------------------------------
        incident_tool_objs = await incident.list_tools()
        # github_tool_objs   = await github.list_tools()
        memory_tool_objs   = await memory.list_tools()
        code_index_tool_objs = await code_index.list_tools()
        editor_tool_objs = await editor.list_tools()
        shell_tool_objs = await shell.list_tools()

        incident_tools = {t.name for t in incident_tool_objs}
        # github_tools   = {t.name for t in github_tool_objs}
        memory_tools   = {t.name for t in memory_tool_objs}
        code_index_tools = {t.name for t in code_index_tool_objs}
        editor_tools = {t.name for t in editor_tool_objs}
        shell_tools = {t.name for t in shell_tool_objs}

        log.info("tools.discovered", extra={
            "incident_tools": sorted(incident_tools),
            # "github_tools": sorted(github_tools),
            "memory_tools": sorted(memory_tools),
            "code_index_tools": sorted(code_index_tools),
            "editor_tools": sorted(editor_tools),
            "shell_tools": sorted(shell_tools),
        })

        claude_tools = [
            mcp_tool_to_claude(t)
            for t in (
                incident_tool_objs
                + memory_tool_objs
                + code_index_tool_objs
                + editor_tool_objs
                + shell_tool_objs
                # + github_tool_objs
            )
        ]

        # ----------------------------------------------
        # Recall memory
        # ----------------------------------------------
        past_memory = await memory.call_tool(
            "recall_memory",
            {
                "agent_id": AGENT_ID,
                "limit": 10,
            },
        )

        log.info("memory.recalled", extra={
            "memory_raw": str(past_memory),
        })

        system_prompt = SYSTEM_PROMPT + "\n\nPast memory:\n" + str(past_memory)

        messages = [
            {
                "role": "user",
                "content": "Handle the most recent production incident end-to-end.",
            },
            {
                "role": "user",
                "content": "Do not send the entire codebase or full file code to LLM. Provide only the minimal, relevant code segments required to diagnose and fix the issue. The LLM should receive targeted excerpts aligned to the specific failure mode, not a full dump. This constrains reasoning, reduces noise, and improves fix accuracy",
            }
        ]

        # ----------------------------------------------
        # Autonomous loop
        # ----------------------------------------------
        while True:
            log.info("model.call", extra={
                "message_count": len(messages),
            })

            t0 = time.time()
            response = await claude.messages.create(
                model=MODEL,
                system=system_prompt,
                messages=messages,
                tools=claude_tools,
                max_tokens=2048,
            )
            latency_ms = int((time.time() - t0) * 1000)

            log.info("model.response", extra={
                "latency_ms": latency_ms,
                "content_blocks": [getattr(b, "type", None) for b in response.content],
            })

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                }
            )

            tool_uses = [
                block for block in response.content
                if getattr(block, "type", None) == "tool_use"
            ]

            log.info("model.tool_use.detected", extra={
                "count": len(tool_uses),
                "tools": [t.name for t in tool_uses],
            })

            if tool_uses:
                tool_result_blocks = []

                for tool_block in tool_uses:
                    tool_name = tool_block.name
                    tool_args = tool_block.input

                    result, memory_type = await dispatch_tool(
                        tool_name,
                        tool_args,
                        incident,
                        # github,
                        memory,
                        code_index,
                        editor,
                        shell,
                        incident_tools,
                        # github_tools,
                        memory_tools,
                        code_index_tools,
                        editor_tools,
                        shell_tools,
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
                        log.info("memory.write", extra={
                            "memory_type": memory_type,
                            "tool": tool_name,
                        })

                    tool_result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_block.id,
                            "content": str(result),
                        }
                    )

                messages.append(
                    {
                        "role": "user",
                        "content": tool_result_blocks,
                    }
                )

                continue

            # ----------------------------------------------
            # Final response
            # ----------------------------------------------
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

            log.info("memory.write.final", extra={
                "summary_len": len(final_text),
            })

            log.info("agent.complete", extra={
                "final_text": final_text,
            })

            print(final_text)
            break

# ======================================================
# Entry
# ======================================================
if __name__ == "__main__":
    asyncio.run(run_agent())
