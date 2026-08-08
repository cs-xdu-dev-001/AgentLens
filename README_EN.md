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
- **Web and Linux CLI**: the terminal runs a local BYOK agent by default, or can explicitly connect to a KnowFlow server for shared approvals, memory, and run history.

## Choose a starting point

| Goal | Recommended entry point | Requirements |
| --- | --- | --- |
| Run a local agent in a Linux terminal | [Linux CLI](#linux-cli) | Linux, Python 3.10+, Node.js 22+, and your own model API key |
| Use an existing KnowFlow deployment | Browser or CLI `--remote` mode | A modern browser, or the Linux CLI |
| Modify and debug the project on Windows | [Local development](#local-development-on-windows) | Python 3.10+, Node.js 18+, npm |
| Host your own service | [Linux deployment](#linux-deployment) | Ubuntu 24.04, a domain, and HTTPS |

## Linux CLI

The CLI is a local BYOK agent by default. It needs no KnowFlow account, uses your model API key, and runs the LangGraph agent in the current directory. Write tools require confirmation. Shell access is enabled only when Anthropic Sandbox Runtime is installed.

With Node.js 22+ installed on Linux, `knowflow chat` starts a React/Ink interface built on the same UI stack as Claude Code. Python and LangGraph still own models, tools, and permissions; the two layers exchange redacted JSONL events. The CLI falls back to Textual when Node.js 22 is unavailable. Set `KNOWFLOW_TUI=textual` to force that fallback, or use `knowflow chat --plain` for scripts and pipelines.

The Ink interface provides dynamic tool/Skill/MCP commands, fuzzy completion, prompt history, queued tasks, streaming Markdown answers, approvals, and in-place tool progress. Type `/`, navigate with the arrow keys, accept with Tab or →, and dismiss with Esc. `Shift+Tab` cycles Ask, Auto edit, and Full access; `/permissions` opens the inline picker and `Ctrl+R` recalls history. The default main-screen mode delegates scrollback, wheel navigation, text selection, and copy to the terminal; `Ctrl+O` opens the full transcript and `Ctrl+E` expands tool details. Run `KNOWFLOW_CLI_FULLSCREEN=1 knowflow chat` for a fixed-composer fullscreen mode with `PgUp/PgDn` scrolling. To capture the wheel there, also set `KNOWFLOW_CLI_MOUSE=1`; some terminals then require Shift-drag for native selection. Shell progress shows recent output, elapsed time, lines, and bytes. `Ctrl+C` terminates the SRT process group and stops the agent at a safe boundary. The advanced Allow/Ask/Deny rule editor remains available through the Textual fallback during migration.

```bash
sudo apt-get update && sudo apt-get install -y python3-venv git
node --version  # The Ink interface requires v22+
curl -fsSL https://raw.githubusercontent.com/cs-xdu-dev-001/KnowFlow-AI/main/install.sh | sh
knowflow configure
knowflow doctor --cli
knowflow chat
knowflow update
```

The installer only writes to the current user's directories and never elevates privileges. On distributions other than Ubuntu or Debian, install Python venv and Git with the system package manager first. The CLI remains usable without Node.js 22, but falls back to Textual.

Install SRT and its Linux dependencies only when shell tools are needed:

```bash
sudo apt-get install -y bubblewrap util-linux ripgrep socat
npm install -g @anthropic-ai/sandbox-runtime
srt echo sandbox-ok
knowflow doctor --cli
```

Use `/doctor` for the same checks inside the TUI. Some Ubuntu 24.04 cloud images restrict unprivileged user namespaces with AppArmor; prefer a minimal `bwrap` policy and do not globally disable AppArmor restrictions on production hosts.

`knowflow configure` accepts the API key through a hidden prompt and stores public settings separately from credentials. `KNOWFLOW_API_BASE`, `KNOWFLOW_API_KEY`, `KNOWFLOW_MODEL`, and `KNOWFLOW_API_MODE` can temporarily override saved values.

Useful commands:

```bash
knowflow run "Summarize the current project" --events
knowflow run "Run the tests and fix failures" --yes
knowflow update
```

The local CLI and Web app now share the Agent tool-assembly layer. Web search, MCP, Skills, and Mem0 are enabled from local configuration and do not require a KnowFlow account:

```bash
# Tavily web search
knowflow tools configure web-search
knowflow tools list

# Public HTTPS MCP; Notion uses https://mcp.notion.com/mcp
knowflow mcp add notion https://mcp.notion.com/mcp --auth oauth
knowflow mcp oauth <ID printed by the previous command>
knowflow mcp list

# Install a local Skill
knowflow skills install ./my-skill
knowflow skills list

# Optional Mem0 long-term memory
knowflow memory configure
knowflow memory enable
knowflow memory list
```

Type `/tools`, `/mcp`, `/skills`, or `/memory` in the TUI to inspect real runtime status. `/tool:*`, `/skill:*`, and `/mcp:*` commands are discovered at runtime. Secret-bearing setup remains in hidden-input CLI commands so keys do not enter TUI transcripts or shell history.

Public settings live in `~/.config/knowflow/config.json`; the mode-600 `credentials.json` stores model, Tavily, MCP, and Mem0 secrets. LangGraph checkpoints, Skills, Mem0 data, and TUI prompt history live under `~/.local/share/knowflow`. The current directory is the default workspace.

Connecting to an existing KnowFlow Web deployment is optional:

```bash
knowflow auth login https://your-knowflow-server.example
knowflow chat --remote
knowflow run "Summarize the knowledge base" --remote
```

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
sudo apt-get install -y bubblewrap util-linux ripgrep socat
npm install -g @anthropic-ai/sandbox-runtime
srt echo sandbox-ok
knowflow doctor --cli
```

Store production data under `/var/lib/knowflow-ai` and grant write access to the service user. A consistent stopped-service backup must include the main database, LangGraph checkpoint, `skills`, `workspaces`, `tool-results`, and `mem0` data.

## Design at a glance

```text
React Web -- FastAPI + SSE ---------┐
                                    ├-- LangGraph
Ink TUI -- JSONL -- Python BYOK ----┘
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
