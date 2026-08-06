<div align="center">

# KnowFlow AI

**A self-hosted AI agent and knowledge base with observable execution**

Chat, RAG, tools, MCP, Skills, long-term memory, and task execution in one interface.

<p>
  <a href="./README.md"><img alt="简体中文" src="https://img.shields.io/badge/简体中文-E5E7EB?style=flat-square"></a>
  <a href="./README_EN.md"><img alt="English" src="https://img.shields.io/badge/English-111111?style=flat-square"></a>
</p>

<p>
  <a href="#choose-a-starting-point">Quick start</a> ·
  <a href="#linux-cli">Linux CLI</a> ·
  <a href="#linux-deployment">Deployment</a> ·
  <a href="#further-reading">Documentation</a>
</p>

<p>
  <a href="https://github.com/cs-xdu-dev-001/KnowFlow-AI/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/cs-xdu-dev-001/KnowFlow-AI/actions/workflows/ci.yml/badge.svg"></a>
  <a href="./LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-2F855A?style=flat-square"></a>
</p>

</div>

> The current release is intended for personal use, learning agent engineering, and testing in controlled environments. The agent runtime and CLI target Linux; Windows is supported for local development and browser access.

## Core capabilities

- **Observable agent runs**: LangGraph execution with visible model, tool, MCP, memory, and approval steps, plus durable checkpoints and failure recovery.
- **Knowledge-base answers with citations**: ingest common office documents and inspect matched text, relevance, and sources.
- **Switchable models and protocols**: connect OpenAI-compatible endpoints through Chat Completions or the Responses API.
- **Tools, MCP, and Skills**: let the model search the web, call authorized MCP servers, and activate a Skill for the current task.
- **Per-user isolation**: separate knowledge bases, model settings, tool keys, MCP connections, Skills, and memories.
- **Web and Linux CLI**: use the same agent, approvals, memory, and run history from a browser or terminal.

## Choose a starting point

| Goal | Recommended entry point | Requirements |
| --- | --- | --- |
| Use an existing KnowFlow deployment | [Linux CLI](#linux-cli) or browser | Linux with Python 3.10+, or a modern browser |
| Modify and debug the project on Windows | [Local development](#local-development-on-windows) | Python 3.10+, Node.js 18+, npm |
| Host your own service | [Linux deployment](#linux-deployment) | Ubuntu 24.04, a domain, and HTTPS |

## Linux CLI

The remote CLI is lightweight. It does not install Mem0, ChromaDB, or the server runtime locally.

```bash
curl -fsSL https://raw.githubusercontent.com/cs-xdu-dev-001/KnowFlow-AI/main/install.sh | sh
knowflow auth login https://your-knowflow-server.example
knowflow chat
```

On a headless server, the CLI prints a verification URL and a one-time code so authorization can be completed on another device.

Useful commands:

```bash
knowflow run "Summarize the current project" --events
knowflow runs
knowflow models list
knowflow tools list
knowflow skills list
knowflow mcp list
knowflow memory list
```

The CLI connects to a remote KnowFlow server by default. `--local` opens local databases and runtime storage directly; use it only on a dedicated test machine or during offline maintenance. Do not run it alongside the web service against the same data directory.

## Local development on Windows

### 1. Clone the repository

```powershell
git clone https://github.com/cs-xdu-dev-001/KnowFlow-AI.git
Set-Location "KnowFlow-AI"
```

### 2. Install dependencies

`start-dev.cmd` launches the backend with Windows `py -3`, so install backend dependencies into that Python environment:

```powershell
py -3 -m pip install -r backend\requirements.txt
py -3 -m pip install --no-deps -e backend
Copy-Item backend\.env.example backend\.env

Set-Location frontend
npm install
Set-Location ..
```

### 3. Start development servers

```powershell
.\start-dev.cmd
```

Open <http://127.0.0.1:5173/>. Default addresses:

```text
Frontend: http://127.0.0.1:5173
Backend:  http://127.0.0.1:8010
API docs: http://127.0.0.1:8010/docs
```

Inspect resolved ports and commands without starting the servers:

```powershell
.\start-dev.cmd --check
```

## First use

1. Create a local account and sign in.
2. Add a chat model in Settings. Add an embedding model only when semantic knowledge-base retrieval is needed.
3. Create a knowledge base and upload documents, or start chatting immediately.
4. Configure web search, MCP, Skills, and long-term memory only when needed.

Model configurations belong to the current user. Each user also adds their own Tavily key in the UI; the backend does not load a global search key from the startup script.

## Configuration

Local development does not require editing every environment variable. Copy `backend/.env.example` and start the application; optional capabilities stay disabled or use safe defaults.

### Production checklist

| Variable | Purpose |
| --- | --- |
| `KNOWFLOW_SECRET_KEY` | Encrypts stored model and tool keys; replace the default value |
| `KNOWFLOW_BASE_URL` | Public backend URL used by OAuth callbacks |
| `KNOWFLOW_OAUTH_RETURN_ORIGINS` | Exact frontend origins allowed after OAuth |
| `KNOWFLOW_COOKIE_SECURE=1` | Enables secure cookies for HTTPS deployments |
| `KNOWFLOW_DB_URL` | Keep SQLite by default; change only when MySQL is needed |

### Optional capabilities

| Capability | Configuration |
| --- | --- |
| Chat and embedding models | Settings in the web UI |
| Tavily web search | Tools & MCP in the web UI |
| GitHub login | `KNOWFLOW_GITHUB_CLIENT_ID`, `KNOWFLOW_GITHUB_CLIENT_SECRET` |
| Mem0 long-term memory | `KNOWFLOW_MEMORY_*` |
| Workspace file tools | `KNOWFLOW_WORKSPACE_ENABLED=1` |
| Sandboxed shell | `KNOWFLOW_SANDBOX_ENABLED=1` and Anthropic Sandbox Runtime |
| Private-network MCP | `KNOWFLOW_MCP_ALLOW_PRIVATE_NETWORKS=1` in controlled development only |

See [`backend/.env.example`](backend/.env.example) for the complete list, defaults, and limits. Never commit `backend/.env`.

### Model protocols

- **Chat Completions** is intended for traditional OpenAI-compatible endpoints.
- **Responses API** requires `POST /v1/responses`, SSE streaming events, and a final `response.completed` event.
- KnowFlow does not automatically downgrade after a protocol failure, preventing duplicate requests or tool execution.
- Mem0 uses separate server-side LLM and embedding settings; it is independent of the chat protocol selected in the UI.

<details>
<summary>Advanced configuration and runtime constraints</summary>

The Vite development server uses `--strictPort` and connects to `VITE_BACKEND_URL=http://127.0.0.1:8010`. Keep `KNOWFLOW_OAUTH_RETURN_ORIGINS` aligned when changing the frontend port. Legacy-data adoption through `KNOWFLOW_ADOPT_LEGACY_DATA` is disabled by default.

Local accounts use PBKDF2 password hashes and HttpOnly session cookies. GitHub OAuth is optional. Its local callback is `http://127.0.0.1:8010/api/auth/oauth/github/callback`.

`web_search` uses `tool_choice: auto`; each user stores their own Tavily key. Sanitized SSE events feed the chat progress card and run inspector.

The Notion preset connects to `https://mcp.notion.com/mcp` with per-user OAuth. Custom public HTTPS MCP servers use Streamable HTTP with no authentication, encrypted static headers, or OAuth. Read-only calls may run automatically; write and unknown-risk calls require approval.

A Skill is a per-user package centered on `SKILL.md`. GitHub and ZIP installation uses preview followed by explicit installation. Package scripts are stored for inspection but never executed. One run uses at most one enabled Skill.

Mem0 provides long-term memory only; it does not own the agent loop. Recall is checkpointed, while ADD-only extraction runs asynchronously after the answer is saved. Common tokens, keys, passwords, and bearer values are removed before memory processing. Local Qdrant storage requires one backend worker.

</details>

## Linux deployment

Use Ubuntu 24.04, a non-root service user, one backend worker, systemd, and an HTTPS reverse proxy. The agent runtime does not currently execute on Windows or macOS hosts.

The repository provides:

- [`deploy/knowflow-ai.service.example`](deploy/knowflow-ai.service.example): systemd service template.
- [`deploy/fast-deploy.sh`](deploy/fast-deploy.sh): fast server synchronization after CI succeeds.
- [`.github/workflows/ci.yml`](.github/workflows/ci.yml): dependency, frontend build, and full-check gate.

Install the sandbox runtime before enabling shell execution:

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap util-linux
npm install -g @anthropic-ai/sandbox-runtime
srt --version
```

Store production data under `/var/lib/knowflow-ai` and grant write access to the service user. A consistent stopped-service backup must include the main database, LangGraph checkpoint, `skills`, `workspaces`, `tool-results`, and `mem0` data.

## Design at a glance

```text
React Web / Linux CLI
          │
       FastAPI + SSE
          │
       LangGraph
   ┌──────┼──────────┐
  RAG   Tools/MCP   Skills
   │        │          │
Citations Approval   Instructions
          │
   Mem0 long-term memory
```

Write, delete, destructive, and unknown-risk tools pause the agent for one-time approval. Read-only tools may run automatically. Public traces contain sanitized inputs and bounded result summaries, never system prompts, credentials, or hidden reasoning.

## Development checks

Run all checks from the repository root:

```powershell
Get-ChildItem tests -Filter "check_*.py" |
  Sort-Object Name |
  ForEach-Object {
    python $_.FullName
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  }
```

Build the frontend:

```powershell
Set-Location frontend
npm run build
```

## Security boundaries

- Do not commit `.env`, databases, uploads, user Skills, workspaces, tool results, Mem0 data, or checkpoints.
- Use HTTPS and replace `KNOWFLOW_SECRET_KEY` in production.
- Treat encrypted external-service keys as production credentials.
- Do not allow private-network MCP access on an internet-facing deployment.
- Shell commands run only through the sandbox and always require approval.

## Further reading

- [Web-search agent loop](docs/langgraph-web-search-loop.md)
- [MCP write approval](docs/langgraph-mcp-write-approval.md)
- [Skills and task planning](docs/langgraph-skills-and-planning.md)
- [Long-term memory lifecycle](docs/langgraph-memory-lifecycle.md)
- [API debugging](docs/api-debug.md)

## Stack

FastAPI, SQLAlchemy, React, Vite, LangGraph, and Mem0. SQLite and local retrieval are the defaults; MySQL and Chroma are optional.

## License

[MIT](LICENSE)
