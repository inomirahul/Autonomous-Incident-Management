import os
import psycopg2
import psycopg2.extras
from typing import List, Dict, Any, Optional
from fastmcp import FastMCP
from openai import OpenAI

client = OpenAI()
conn = psycopg2.connect(os.getenv("MEMORY_DB_URL"))
conn.autocommit = True

mcp = FastMCP("agent-memory")

def embed(text: str) -> list:
    return client.embeddings.create(
        model="text-embedding-3-small",
        input=text
    ).data[0].embedding

@mcp.tool()
def write_memory(
    agent_id: str,
    memory_type: str,
    content: Dict[str, Any],
    semantic: bool = True
):
    vector = embed(str(content)) if semantic else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_memory (agent_id, memory_type, content, embedding)
            VALUES (%s, %s, %s, %s)
            """,
            (agent_id, memory_type, psycopg2.extras.Json(content), vector)
        )
    return {"status": "stored"}

@mcp.tool()
def semantic_recall(
    agent_id: str,
    query: str,
    limit: int = 5
) -> List[Dict[str, Any]]:
    qvec = embed(query)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT memory_type, content, created_at
            FROM agent_memory
            WHERE agent_id = %s
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (agent_id, qvec, limit)
        )
        return cur.fetchall()

@mcp.tool()
def rag_context(
    agent_id: str,
    query: str
) -> str:
    memories = semantic_recall(agent_id, query, limit=8)
    blocks = []
    for m in memories:
        blocks.append(f"[{m['memory_type']}] {m['content']}")
    return "\n".join(blocks)

if __name__ == "__main__":
    mcp.run(port=8004)
