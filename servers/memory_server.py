# memory_server.py
import os
import psycopg2
import psycopg2.extras
from typing import List, Dict, Any
from fastmcp import FastMCP


conn = psycopg2.connect(
    dbname="agent",
    user="agent",
    password="agent",
    host="localhost",
    port=5432,
)
conn.autocommit = True

mcp = FastMCP("agent-memory")

@mcp.tool()
def write_memory(
    agent_id: str,
    memory_type: str,
    content: Dict[str, Any]
):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_memory (agent_id, memory_type, content)
            VALUES (%s, %s, %s)
            """,
            (agent_id, memory_type, psycopg2.extras.Json(content))
        )
    return {"status": "stored"}

@mcp.tool()
def recall_memory(
    agent_id: str,
    memory_type: str | None = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if memory_type:
            cur.execute(
                """
                SELECT memory_type, content, created_at
                FROM agent_memory
                WHERE agent_id = %s AND memory_type = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (agent_id, memory_type, limit)
            )
        else:
            cur.execute(
                """
                SELECT memory_type, content, created_at
                FROM agent_memory
                WHERE agent_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (agent_id, limit)
            )
        return cur.fetchall()

if __name__ == "__main__":
    mcp.run(
    transport="http",
    host="0.0.0.0",
    port=8004
)
