import asyncio
from fastmcp import Client
from anthropic import AsyncAnthropic

AGENT_ID = "incident-agent-v1"

INCIDENT_SERVER = "http://localhost:8001"
GITHUB_SERVER   = "http://localhost:8002"
JIRA_SERVER     = "http://localhost:8003"
MEMORY_SERVER   = "http://localhost:8004"


class ClaudeAdapter:
    """
    Minimal adapter that exposes llm.chat.completions.create(...) as an async call
    and forwards to Anthropic's Messages API (AsyncAnthropic.messages.create).

    Notes:
    - This adapter returns a simple response object compatible with the existing
      code shape: response.choices[0].message.content
    """
    def __init__(self, api_key: str | None = None):
        # AsyncAnthropic will read ANTHROPIC_API_KEY env var if api_key is None.
        self.client = AsyncAnthropic(api_key=api_key) 
        # keep same attribute shape as your previous llm
        self.chat = self
        self.completions = self

    async def create(self, *, model: str, messages: list, tools=None, tool_choice="auto", max_tokens: int = 1024):
        # direct call to Anthropic Messages API
        # pass tools/tool_choice through -- Anthropic supports a `tools` param.
        resp = await self.client.messages.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice
        )

        # Build a tiny compatibility object with .choices[0].message
        class _Msg:
            def __init__(self, content, tool_calls=None):
                self.content = content
                # Claude's tool-use blocks are different. We provide an empty list here.
                # For real tool use, parse resp to extract tool_use blocks and populate tool_calls.
                self.tool_calls = tool_calls or []

        class _Choice:
            def __init__(self, message):
                self.message = message

        class _Resp:
            def __init__(self, choices):
                self.choices = choices

        # resp may expose .content, .text or .message depending on SDK version.
        content = None
        if hasattr(resp, "content"):
            content = resp.content
        elif hasattr(resp, "text"):
            content = resp.text
        elif hasattr(resp, "message"):
            try:
                content = resp.message.content
            except Exception:
                content = str(resp)
        else:
            content = str(resp)

        return _Resp([_Choice(_Msg(content))])

# instantiate adapter (reads ANTHROPIC_API_KEY from env if not provided)
llm = ClaudeAdapter()

SYSTEM_PROMPT = """
You are an autonomous incident-response engineer.

You have access to:
- incident tools
- GitHub tools
- Jira tools
- long-term memory

Rules:
- Recall relevant past incidents before acting
- Use memory only if it is relevant
- Store decisions, actions, and outcomes
- Do not ask questions
- Act decisively
"""

async def run_agent():
    async with (
        Client(INCIDENT_SERVER) as incident,
        Client(GITHUB_SERVER) as github,
        Client(JIRA_SERVER) as jira,
        Client(MEMORY_SERVER) as memory
    ):
        # ------------------------------------------------
        # Tool registry (MCP contracts)
        # ------------------------------------------------
        tools = (
            incident.tools +
            github.tools +
            jira.tools +
            memory.tools
        )

        # ------------------------------------------------
        # RAG: semantic recall BEFORE reasoning
        # ------------------------------------------------
        rag_context = await memory.call_tool(
            "rag_context",
            {
                "agent_id": AGENT_ID,
                "query": "production incident remediation"
            }
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": f"Relevant long-term memory (may be empty):\n{rag_context}"
            },
            {
                "role": "user",
                "content": "Handle the most recent production incident end-to-end."
            }
        ]


        while True:
            # use a Claude model name here
            response = await llm.chat.completions.create(
                model="claude-sonnet-4-5-20250929",  # pick a Claude model available to you
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )

            msg = response.choices[0].message

            # --------------------------------------------
            # Tool execution path
            # --------------------------------------------
            if msg.tool_calls:
                for call in msg.tool_calls:
                    tool_name = call.function.name
                    tool_args = call.function.arguments

                    if tool_name in incident.tool_map:
                        result = await incident.call_tool(tool_name, tool_args)
                        memory_type = "incident"

                    elif tool_name in github.tool_map:
                        result = await github.call_tool(tool_name, tool_args)
                        memory_type = "action"

                    elif tool_name in jira.tool_map:
                        result = await jira.call_tool(tool_name, tool_args)
                        memory_type = "action"

                    elif tool_name in memory.tool_map:
                        result = await memory.call_tool(tool_name, tool_args)
                        memory_type = None  # already memory

                    else:
                        raise RuntimeError(f"Unknown tool: {tool_name}")

                    # ---- persist episodic memory automatically ----
                    if memory_type:
                        await memory.call_tool(
                            "write_memory",
                            {
                                "agent_id": AGENT_ID,
                                "memory_type": memory_type,
                                "content": {
                                    "tool": tool_name,
                                    "arguments": tool_args,
                                    "result": result
                                }
                            }
                        )

                    messages.append(msg)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": str(result)
                    })

            # --------------------------------------------
            # Completion path
            # --------------------------------------------
            else:
                await memory.call_tool(
                    "write_memory",
                    {
                        "agent_id": AGENT_ID,
                        "memory_type": "reflection",
                        "content": {
                            "summary": msg.content
                        }
                    }
                )

                print(msg.content)
                break


if __name__ == "__main__":
    asyncio.run(run_agent())
