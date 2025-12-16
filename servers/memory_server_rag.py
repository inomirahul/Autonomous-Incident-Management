# memory_server.py
import os
import psycopg2
import psycopg2.extras
from typing import List, Dict, Any
from fastmcp import FastMCP

from sentence_transformers import SentenceTransformer


conn = psycopg2.connect(
    dbname=os.getenv("MEMORY_DB_NAME"),
    user=os.getenv("MEMORY_DB_USER"),
    password=os.getenv("MEMORY_DB_PASSWORD"),
    host=os.getenv("MEMORY_DB_HOST"),
    port=os.getenv("MEMORY_DB_PORT"),
)
conn.autocommit = True

mcp = FastMCP("agent-memory")
embedder = SentenceTransformer("all-MiniLM-L6-v2")


def embed(text: str) -> list[float]:
    if not text:
        return []
    return embedder.encode(text).tolist()


def _semantic_recall_internal(agent_id: str, query: str, limit: int):
    qvec = embed(query)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT memory_type, content, created_at
            FROM agent_memory
            WHERE agent_id = %s AND embedding IS NOT NULL
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (agent_id, qvec, limit)
        )
        return cur.fetchall()

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
def semantic_recall(agent_id: str, query: str, limit: int = 5):
    return _semantic_recall_internal(agent_id, query, limit)

@mcp.tool()
def rag_context(agent_id: str, query: str) -> str:
    memories = _semantic_recall_internal(agent_id, query, limit=8)
    return "\n".join(
        f"[{m['memory_type']}] {m['content']}"
        for m in memories
    )

if __name__ == "__main__":
    mcp.run(
    transport="http",
    host="0.0.0.0",
    port=8004
)
