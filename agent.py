import asyncio
from fastmcp import Client
from openai import AsyncOpenAI


AGENT_ID = "incident-agent-v1"

# -----------------------
# MCP servers
# -----------------------
INCIDENT_SERVER = "http://localhost:8001"
GITHUB_SERVER   = "http://localhost:8002"
JIRA_SERVER     = "http://localhost:8003"
MEMORY_SERVER   = "http://localhost:8004"


llm = AsyncOpenAI()

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

        # ------------------------------------------------
        # Autonomous MCP loop
        # ------------------------------------------------
        while True:
            response = await llm.chat.completions.create(
                model="gpt-4.1",
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
            # Completion path (reflection)
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
