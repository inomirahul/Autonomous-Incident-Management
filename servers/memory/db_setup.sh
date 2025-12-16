#!/bin/bash
set -e

echo "Waiting for Postgres..."
until pg_isready -h db -p 5432; do
  sleep 1
done

echo "Initializing database..."
psql "$MEMORY_DB_URL" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS agent_memory (
    id BIGSERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    content JSONB NOT NULL,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_memory_agent_id
ON agent_memory(agent_id);

CREATE INDEX IF NOT EXISTS idx_agent_memory_type
ON agent_memory(memory_type);

CREATE INDEX IF NOT EXISTS idx_agent_memory_embedding
ON agent_memory
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 200);
SQL
