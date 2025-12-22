#!/bin/bash
# ============================================================================
# run_local.sh - Run all MCP servers and agent locally (DB via Docker Compose)
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"
PYTHON_CMD=""

# ============================================================================
# Check/Install PostgreSQL client tools
# ============================================================================
check_pg_client() {
    if command -v pg_isready &> /dev/null; then
        echo "PostgreSQL client tools found."
    else
        echo "PostgreSQL client tools not found. Installing..."
        sudo apt-get update && sudo apt-get install -y postgresql-client
        if command -v pg_isready &> /dev/null; then
            echo "PostgreSQL client tools installed successfully."
        else
            echo "ERROR: Failed to install PostgreSQL client tools."
            exit 1
        fi
    fi
}

# ============================================================================
# Find Python 3.11 or 3.13
# ============================================================================
find_python() {
    for cmd in python3.13 python3.11 python3; do
        if command -v "$cmd" &> /dev/null; then
            version=$("$cmd" --version 2>&1 | grep -oP '\d+\.\d+')
            if [[ "$version" == "3.13" || "$version" == "3.11" ]]; then
                PYTHON_CMD="$cmd"
                echo "Found Python: $PYTHON_CMD (version $version)"
                return 0
            fi
        fi
    done
    echo "ERROR: Python 3.11 or 3.13 not found. Please install one of them."
    exit 1
}

# ============================================================================
# Setup virtual environment
# ============================================================================
setup_venv() {
    if [ -d "$VENV_DIR" ]; then
        echo "Virtual environment found at $VENV_DIR"
        source "$VENV_DIR/bin/activate"
        echo "Activated existing virtual environment"
    else
        echo "Creating virtual environment at $VENV_DIR..."
        $PYTHON_CMD -m venv "$VENV_DIR"
        source "$VENV_DIR/bin/activate"
        echo "Created and activated virtual environment"

        echo "Upgrading pip..."
        pip install --upgrade pip
    fi

    echo "Installing/updating dependencies from requirements.txt..."
    pip install -r requirements.txt
    echo "Dependencies installed!"
}

# ============================================================================
# Main setup
# ============================================================================
echo "=============================================="
echo "  Local MCP Infrastructure Setup"
echo "=============================================="

check_pg_client
find_python
setup_venv

# Load environment variables from .env (REQUIRED)
if [ -f .env ]; then
    echo "Loading environment variables from .env..."
    set -a
    source .env
    set +a
else
    echo "ERROR: .env file not found!"
    echo "Please create a .env file with required environment variables."
    echo "You can copy from default.env: cp default.env .env"
    exit 1
fi

# Export local database connection settings (localhost instead of 'db')
export MEMORY_DB_HOST=localhost
export MEMORY_DB_PORT=5432
export MEMORY_DB_NAME=agent
export MEMORY_DB_USER=agent
export MEMORY_DB_PASSWORD=agent
export MEMORY_DB_URL="postgres://agent:agent@localhost:5432/agent"

# Local MCP endpoints
export INCIDENT_SERVER="http://localhost:8001/mcp"
export GITHUB_SERVER="http://localhost:8002/mcp"
export JIRA_SERVER="http://localhost:8003/mcp"
export MEMORY_SERVER="http://localhost:8004/mcp"
export CODE_INDEX_SERVER="http://localhost:8005/mcp"
export EDITOR_SERVER="http://localhost:8006/mcp"
export SHELL_SERVER="http://localhost:8007/mcp"

# Array to track background PIDs
PIDS=()

cleanup() {
    echo ""
    echo "Shutting down MCP servers..."
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done
    echo "All servers stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

wait_for_db() {
    echo "Waiting for database to be ready..."
    for i in {1..30}; do
        if pg_isready -h localhost -p 5432 -U agent > /dev/null 2>&1; then
            echo "Database is ready!"
            return 0
        fi
        echo "  Waiting for database... ($i/30)"
        sleep 1
    done
    echo "ERROR: Database not ready after 30 seconds"
    exit 1
}

setup_database() {
    echo "Setting up database schema..."
    PGPASSWORD=agent psql -h localhost -p 5432 -U agent -d agent <<'SQL'
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
    echo "Database schema ready!"
}

echo "=============================================="
echo "  Starting Local MCP Infrastructure"
echo "=============================================="

# Start database container
echo "Starting database container..."
if docker-compose -f docker-compose-db.yml up -d; then
    echo "Database container started successfully."
else
    echo "ERROR: Failed to start database container!"
    echo "Please ensure Docker is installed and running."
    exit 1
fi

# Wait for database to be ready
wait_for_db
setup_database

echo ""
echo "Starting MCP servers..."

# 1. Incident MCP (port 8001)
echo "  [1/5] Starting Incident MCP on port 8001..."
python servers/incident/mock_incident_server.py &
PIDS+=($!)
sleep 0.5

# 2. Memory MCP (port 8004)
echo "  [2/5] Starting Memory MCP on port 8004..."
python servers/memory/memory_server.py &
PIDS+=($!)
sleep 0.5

# 3. Code Indexer MCP (port 8005)
echo "  [3/5] Starting Code Indexer MCP on port 8005..."
python servers/file/file.py &
PIDS+=($!)
sleep 0.5

# 4. Editor MCP (port 8006)
echo "  [4/5] Starting Editor MCP on port 8006..."
python servers/editor/editor.py &
PIDS+=($!)
sleep 0.5

# 5. Shell MCP (port 8007)
echo "  [5/5] Starting Shell MCP on port 8007..."
python servers/shell/shell.py &
PIDS+=($!)

echo ""
echo "All MCP servers started. Waiting 10 seconds for initialization..."
sleep 7

echo ""
echo "=============================================="
echo "  Starting Agent"
echo "=============================================="
echo ""

# Run agent in foreground
python agent.py

# If agent exits, cleanup will be called via trap

