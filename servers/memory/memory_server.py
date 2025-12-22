# memory_server.py
import os
import psycopg2
import psycopg2.extras
from typing import List, Dict, Any
from fastmcp import FastMCP


conn = psycopg2.connect(
    dbname=os.getenv("MEMORY_DB_NAME"),
    user=os.getenv("MEMORY_DB_USER"),
    password=os.getenv("MEMORY_DB_PASSWORD"),
    host=os.getenv("MEMORY_DB_HOST"),
    port=os.getenv("MEMORY_DB_PORT"),
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
    query: str | None = None,
    limit: int = 20
) -> List[Dict[str, Any]]:
    sql = """
        SELECT memory_type, content, created_at
        FROM agent_memory
        WHERE agent_id = %s
    """
    params = [agent_id]

    if memory_type:
        sql += " AND memory_type = %s"
        params.append(memory_type)

    if query:
        sql += " AND content ILIKE %s"
        params.append(f"%{query}%")

    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, params)
        return cur.fetchall()  

if __name__ == "__main__":
    mcp.run(
    transport="http",
    host="0.0.0.0",
    port=8004
)
