# KnowFlow AI

KnowFlow AI is a local-first knowledge base assistant for document ingestion, retrieval-augmented generation, model configuration, and chat history management.

The project is built with a FastAPI backend and a React + Vite frontend. It is designed for personal knowledge workflows: upload documents, organize them into knowledge bases, retrieve relevant passages, and ask questions with visible citation evidence.

## Features

- Local account authentication with HttpOnly cookie sessions.
- Optional GitHub OAuth login.
- Model configuration for chat and embedding providers.
- OpenAI-compatible chat and embedding gateway.
- Knowledge base management with per-user data isolation.
- Document upload, deduplication, parsing, chunking, and ingestion status tracking.
- Support for common document formats including `txt`, `md`, `pdf`, `docx`, `xlsx`, `pptx`, `html`, `json`, `csv`, `tsv`, `rtf`, `yaml`, `xml`, and `log`.
- RAG debugging with retrieved chunks, scores, matched terms, and retrieval quality metadata.
- Retrieval run tracking through the `retrieval_run` table and detail API.
- Chat interface with references, evidence drawer, and session history.
- Native model-controlled `web_search` with a per-user Tavily key.
- Live, replayable Agent execution traces with sanitized public inputs and results.
- FastAPI Swagger UI, ReDoc, and OpenAPI JSON documentation.

## Tech Stack

- Backend: FastAPI, SQLAlchemy, Pydantic
- Frontend: React, Vite
- Database: SQLite by default, MySQL supported
- Vector backend: local retrieval by default, Chroma supported
- Document parsing: pypdf, python-docx, openpyxl, python-pptx, BeautifulSoup

## Project Structure

```text
KnowFlow AI/
  backend/
    main.py
    knowflow/
      app.py              FastAPI app, auth middleware, static hosting
      config.py           environment variables and runtime paths
      database.py         database wrapper and schema initialization
      db_schema.py        SQLite / MySQL DDL
      responses.py        API response helpers
      runtime.py          RAG, document ingestion, model gateway wiring
      schemas.py          Pydantic request models
      routers/            API routers
      services/           document parsing, model gateway, vector store
    requirements.txt
    .env.example
  frontend/
    package.json
    vite.config.js
    react/
      index.html
      src/
        App.jsx
        main.jsx
        components/
        controller/
        styles.css
    styles.css            canonical stylesheet, synced into React source
  docs/
    api-debug.md
    schema.sql
  tests/
    check_*.py
```

## Requirements

- Python 3.10+
- Node.js 18+
- npm

SQLite works out of the box. MySQL and Chroma are optional.

## Quick Start

Clone the repository and enter the project directory:

```powershell
git clone <your-repo-url>
cd "KnowFlow AI"
```

Create the backend environment:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Install frontend dependencies once:

```powershell
cd ..\frontend
npm install
```

On Windows, start both development servers from the repository root:

```cmd
cd /d "C:\path\to\KnowFlow AI"
start-dev.cmd
```

The helper opens two terminal windows and uses these defaults:

```text
Backend:  http://127.0.0.1:8010
Frontend: http://127.0.0.1:5173
```

Check the resolved paths and commands without starting the servers:

```cmd
start-dev.cmd --check
```

Open `http://127.0.0.1:5173/`. The helper uses Vite `--strictPort` so OAuth return URLs stay predictable. If `5173` is busy, close the old frontend terminal or set `KNOWFLOW_FRONTEND_PORT` before running `start-dev.cmd`.

Manual startup is also supported. Start the backend first:

```powershell
cd backend
$env:KNOWFLOW_BASE_URL="http://127.0.0.1:8010"
$env:KNOWFLOW_OAUTH_RETURN_ORIGINS="http://127.0.0.1:5173"
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8010
```

Then start the frontend in another terminal with the matching backend URL:

```powershell
cd frontend
$env:VITE_BACKEND_URL="http://127.0.0.1:8010"
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

In `cmd.exe`, use:

```cmd
cd /d "C:\path\to\KnowFlow AI\backend"
set KNOWFLOW_BASE_URL=http://127.0.0.1:8010
set KNOWFLOW_OAUTH_RETURN_ORIGINS=http://127.0.0.1:5173
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8010
```

Then in another `cmd.exe` terminal:

```cmd
cd /d "C:\path\to\KnowFlow AI\frontend"
set VITE_BACKEND_URL=http://127.0.0.1:8010
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

The Vite dev server proxies `/api`, `/docs`, `/redoc`, and `/openapi.json` to the backend configured by `VITE_BACKEND_URL`.

If Windows reports `WinError 10013` on port `8000`, use port `8010` as shown above. If login shows `Backend unavailable. Please start the API server.`, keep the backend terminal open and make sure `VITE_BACKEND_URL` points to the same port.

## Production Build

Build the React frontend:

```powershell
cd frontend
npm run build
```

The build output is written to `frontend/dist`. When `frontend/dist` exists, the FastAPI backend serves it from `/`. If `dist` is missing, the backend serves a small fallback page that tells you to build the frontend first.

## Configuration

Copy `backend/.env.example` to `backend/.env` and update values as needed.

| Variable | Description | Default |
| --- | --- | --- |
| `KNOWFLOW_DB_URL` | SQLAlchemy database URL | `sqlite:///./data/knowflow.db` |
| `KNOWFLOW_UPLOAD_DIR` | Uploaded document storage directory | `./data/uploads` |
| `KNOWFLOW_SECRET_KEY` | Key used to encrypt stored model API keys | `change-this-dev-secret` |
| `KNOWFLOW_WEB_SEARCH_TIMEOUT` | Tavily request timeout in seconds | `15` |
| `KNOWFLOW_WEB_SEARCH_MAX_RESULTS` | Maximum normalized results returned to the model | `5` |
| `KNOWFLOW_BASE_URL` | Public backend URL, used by OAuth callbacks | `http://127.0.0.1:8010` |
| `KNOWFLOW_OAUTH_RETURN_ORIGINS` | Exact frontend origins allowed after OAuth login | `http://127.0.0.1:5173,http://localhost:5173` |
| `KNOWFLOW_MCP_CONNECT_TIMEOUT` | MCP connection timeout in seconds | `10` |
| `KNOWFLOW_MCP_REQUEST_TIMEOUT` | MCP request timeout in seconds | `30` |
| `KNOWFLOW_MCP_APPROVAL_TIMEOUT` | Time allowed for one risky tool approval | `300` |
| `KNOWFLOW_MCP_MAX_RESPONSE_BYTES` | Maximum MCP response size | `1048576` |
| `KNOWFLOW_MCP_MAX_EXPOSED_TOOLS` | Maximum MCP tools exposed to one Agent run | `32` |
| `KNOWFLOW_MCP_ALLOW_PRIVATE_NETWORKS` | Allow private-network MCP endpoints only for controlled development | `0` |
| `KNOWFLOW_VECTOR_BACKEND` | `local` or `chroma` | `local` |
| `KNOWFLOW_CHROMA_DIR` | Chroma persistence directory | `./data/chroma` |
| `KNOWFLOW_GITHUB_CLIENT_ID` | GitHub OAuth client ID | empty |
| `KNOWFLOW_GITHUB_CLIENT_SECRET` | GitHub OAuth client secret | empty |
| `KNOWFLOW_COOKIE_SECURE` | Set to `1` when serving over HTTPS | `0` |
| `KNOWFLOW_ADOPT_LEGACY_DATA` | Set to `1` only to let the first signed-in user adopt legacy rows with `NULL` `user_id` | `0` |
| `KNOWFLOW_TOP_K` | Default retrieval result count | `5` |
| `KNOWFLOW_RAG_SCORE_THRESHOLD` | Retrieval quality threshold | `0.25` |

Do not commit `backend/.env`. The repository `.gitignore` excludes local environment files, runtime databases, uploads, logs, browser test profiles, and build output.

## Agent Tools and Traces

Each signed-in user configures their own Tavily key in the 设置页. The backend encrypts it in `tool_config`, never returns the plaintext key, and does not load a global Tavily key from the environment or startup script. The connection check uses one Tavily credit.

`web_search` is a native OpenAI-compatible function tool. KnowFlow sends its schema through `tools` only when the current user has enabled a valid configuration, then uses `tool_choice: auto` so the model decides whether the question needs current or external information. Ordinary questions are not forced to search. Tavily is the first search provider and is called through its HTTP API, without a provider SDK.

Agent progress is emitted as sanitized SSE events. The chat message shows the current step, while the right-side Agent运行图 displays the full nested `model`, `tool`, `mcp`, `skill`, `agent`, `system`, and `approval` protocol. It exposes only bounded public input and result summaries, never hidden chain-of-thought, system prompts, credentials, or raw request logs.

The completed Trace snapshot is stored with the assistant message. Reopening a session restores the same execution view, including completed and failed states.

Longer Agent tasks also persist a public plan and step state in the database. The model may answer simple requests directly; when it creates a plan, the current step lights in the run drawer and tool or MCP traces stay nested under that step. Prefix a request with `/plan` to create the plan without executing it, then choose 开始执行 or 重新规划.

Execution and live SSE subscriptions are process-local, while run, plan, trace, and message state are durable. Refreshing the page reconnects to an active run in the same backend process. A backend restart safely marks unfinished work as 已中断; it never silently replays side effects, and the user must choose 继续执行. Keep this deployment on one backend worker until the coordinator and approval broker move to shared infrastructure.

### Skills

A Skill is a reusable instruction package centered on `SKILL.md`. Its minimum YAML front matter contains `name` and `description`; optional `metadata.knowflow` fields describe the UI label, version, and dependencies without storing credentials:

```yaml
---
name: research-brief
description: Prepare a cited research brief from available sources.
metadata:
  knowflow:
    display_name: Research Brief
    version: "1.0.0"
    required_tools:
      - web_search
    required_mcp:
      - notion
---
```

GitHub and ZIP imports use two stages: preview the package and validation result, then explicitly install it. GitHub sources must use HTTPS on `github.com`. Import limits cover archive and extracted bytes, file count, per-file size, path depth, `SKILL.md` body length, preview TTL, and GitHub timeout. `KNOWFLOW_SKILL_DIR` selects the persistent package root; the `KNOWFLOW_SKILL_MAX_*`, `KNOWFLOW_SKILL_IMPORT_TTL`, and `KNOWFLOW_SKILL_GITHUB_TIMEOUT` limits and safe defaults are documented in `backend/.env.example`.

Skill packages are isolated per-user. Each signed-in user gets builtin Skills disabled by default and cannot see another user's personal installations. One Agent run uses at most one Skill. Enter `/` in the chat input to select one explicitly; without an explicit selection, the model may auto-activate one available, enabled Skill.

A Skill cannot register or enable a tool or MCP connection. Existing tool configuration, MCP connections, and write approval remain authoritative; instructions inside a Skill to skip approval have no effect. Package `scripts/` files are stored for inspection only; the current version不会执行这些脚本. Files under `references/` become available only after activation as bounded, read-only UTF-8 text.

For deployment, each backup must include the database and `data/skills` together. `data/skill-imports` contains temporary previews and may be cleared. The service user needs write permission on the Skill directory; deployments with multiple workers must share the same persistent volume. Before an upgrade, run the repository checks and frontend build. Never commit user-installed packages to Git.

### Remote MCP servers

The 工具与MCP page manages remote MCP connections for the current signed-in user. The built-in Notion preset uses the official `https://mcp.notion.com/mcp` endpoint with user OAuth; it does not ask for a Notion integration token. Select 连接Notion, finish authorization in Notion, return to the settings page, and use 刷新工具 when the remote tool catalog changes. 停用 immediately removes that server's tools from later Agent runs and clears its local authorization.

Custom public HTTPS servers use the Streamable HTTP transport. The add-server dialog supports three authentication modes:

- No authentication.
- Static headers, encrypted with `KNOWFLOW_SECRET_KEY` and never returned in plaintext.
- Standard OAuth with dynamic client registration or an administrator-provided client ID and optional secret.

The model can autonomously choose enabled native or MCP tools. A tool explicitly marked read-only runs automatically. Write, delete, destructive, or unknown-risk operations pause the Agent and require an approval in both the chat message and the run drawer. “允许本次” authorizes only that invocation; enabling a tool is not permanent approval for writes.

Remote URLs are revalidated against SSRF rules before discovery and connection. Private and loopback networks are rejected by default. `KNOWFLOW_MCP_ALLOW_PRIVATE_NETWORKS=1` is only for a controlled local development server; do not enable it in an internet-facing deployment.

The first approval broker is in memory and therefore requires a single backend process. Do not run multiple Uvicorn workers until the broker is moved to shared storage or a message bus. If the process restarts, pending approvals expire safely and the remote write is not sent.

For a real Notion smoke test, connect a non-production workspace and use a dedicated test page. First reject a create-page request and verify that nothing changed; then request it again, allow it once, and verify that exactly one page was created. Disconnect Notion afterward and confirm its tools no longer appear in a new Agent run.

## Auth Mode / Authentication

Local username and password login is enabled by default. Passwords are stored as PBKDF2 hashes, and successful login creates a `knowflow_session` HttpOnly cookie.

GitHub OAuth is optional. To enable it, create a GitHub OAuth App and set:

```text
KNOWFLOW_GITHUB_CLIENT_ID=your_client_id
KNOWFLOW_GITHUB_CLIENT_SECRET=your_client_secret
```

For local development, use this callback URL:

```text
http://127.0.0.1:8010/api/auth/oauth/github/callback
```

The GitHub OAuth App callback should always point to the backend URL above. During frontend development, KnowFlow carries the current Vite page as `returnTo`, but the backend only accepts exact origins listed in `KNOWFLOW_OAUTH_RETURN_ORIGINS`. If you change the frontend port, update that variable before starting the backend.

## Model Providers

KnowFlow AI calls chat and embedding models through OpenAI-compatible endpoints:

```text
POST {baseUrl}/chat/completions
POST {baseUrl}/embeddings
```

You can configure providers such as OpenAI, DeepSeek, DashScope-compatible services, Gemini-compatible gateways, MiniMax, and MiMo by setting `baseUrl`, `apiKey`, and `modelName` in the model configuration screen.

For development, the backend includes fallback behavior:

- If no chat API key is configured, chat responses use a local fallback answer.
- If no embedding API key is configured, embedding uses a deterministic local hash vector.
- If Chroma is disabled, retrieval uses the local retrieval backend.

For demos or production-like usage, configure real chat and embedding models.

## Database Options

SQLite is the default and needs no setup.

To use MySQL, create a database:

```sql
CREATE DATABASE knowflow_ai DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
```

Then set:

```text
KNOWFLOW_DB_URL=mysql+pymysql://user:password@127.0.0.1:3306/knowflow_ai?charset=utf8mb4
```

The backend initializes missing tables at startup and records applied schema versions in `schema_version`.

KnowFlow currently uses a lightweight migration model:

- `db_schema.py` defines the current SQLite and MySQL schema.
- `database.py` creates missing tables, applies compatible column additions, and records `CURRENT_SCHEMA_VERSION`.
- New schema changes should update `CURRENT_SCHEMA_VERSION`, add safe migration logic in `migrate_schema`, and add or update a `tests/check_*.py` contract.

This keeps local development simple while avoiding invisible schema drift. For larger production deployments, replace this with Alembic migrations before running multi-operator database upgrades.

## API Documentation

After starting the backend:

```text
http://127.0.0.1:8010/docs
http://127.0.0.1:8010/redoc
http://127.0.0.1:8010/openapi.json
```

The RAG debugging endpoint is available at:

```text
POST /api/retrieval/debug
GET  /api/retrieval/runs/{run_id}
```

## Quality Checks

Run all project checks from the repository root:

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
cd frontend
npm run build
```

GitHub Actions runs the same release gate on `push` and `pull_request` to `main`:

- install backend dependencies
- install frontend dependencies with `npm ci`
- build the React frontend
- run every `tests/check_*.py` script

Before pushing to GitHub, verify the working tree intentionally excludes secrets and runtime data:

```powershell
git status --short
git ls-files | Select-String -Pattern "(^|/)(\\.env$|.*\\.db$|.*\\.sqlite$|frontend/dist/|frontend/node_modules/)"
git ls-files | Select-String -Pattern "^data/"
```

The second command should not show tracked local secrets, databases, dependency folders, or build output.

## Security Notes

- Change `KNOWFLOW_SECRET_KEY` before storing real API keys.
- Treat stored model and tool keys as production credentials even though they are encrypted at rest.
- Keep `backend/.env` local.
- Use HTTPS and set `KNOWFLOW_COOKIE_SECURE=1` when deploying behind a real domain.
- Review OAuth callback URLs before publishing a deployment.
- Keep private-network MCP access disabled outside an isolated development environment.

## License

KnowFlow AI is released under the MIT License.

## Current Status

KnowFlow AI is usable as a local knowledge base assistant and development prototype. The current engineering baseline includes React UI ownership checks, backend integration checks, release hygiene checks, CI, lightweight schema version tracking, and RAG quality tracking. The main remaining work is to broaden browser-level end-to-end coverage and replace the lightweight schema version system with full migrations if the project moves toward production deployment.
