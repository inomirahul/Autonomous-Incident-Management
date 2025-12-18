# MCP Incident Response Agent (Autonomous, Memory-Backed)

This project runs a **fully autonomous incident-response agent** using:

- MCP (Model Context Protocol)
- FastMCP servers
- Postgres + pgvector (long-term + semantic memory)
- GitHub, Jira, Datadog, Sentry integrations
- LLM-driven control flow

---

## What this system does

On startup, the agent:

1. Recalls relevant past incidents (semantic RAG memory)
2. Fetches the most recent production incident
3. Searches the GitHub repo for related code
4. Creates a Jira ticket if appropriate
5. Creates a GitHub branch + commit + PR if appropriate
6. Stores all actions, decisions, and reflections in memory

The agent improves over time.

---

## Requirements

- Docker
- Docker Compose
- API keys for the services you want to enable

---

## Environment variables

Create a `.env` file:

```env
OPENAI_API_KEY=sk-...

GITHUB_TOKEN=ghp_...
TARGET_REPO=org/repo

JIRA_SERVER=https://your-domain.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=...

JIRA_PROJECT=PROJ

# Optional
SENTRY_API_TOKEN=...
SENTRY_ORG_SLUG=your-org

DD_API_KEY=...
DD_APP_KEY=...
```

### Run agent

`docker compose up --build`

### Run agent locally (no Docker)

`./run_local.sh`
