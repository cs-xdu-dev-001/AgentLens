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
| `KNOWFLOW_DATA_DIR` | Root directory for mutable runtime state | `./data` |
| `KNOWFLOW_DB_URL` | SQLAlchemy database URL | `sqlite:///./data/knowflow.db` |
| `KNOWFLOW_UPLOAD_DIR` | Uploaded document storage directory | `./data/uploads` |
| `KNOWFLOW_SKILL_DIR` | Installed Skill storage directory | `./data/skills` |
| `KNOWFLOW_SKILL_IMPORT_DIR` | Temporary Skill import directory | `./data/skill-imports` |
| `KNOWFLOW_TOOL_RESULT_DIR` | Per-user, per-run storage for oversized tool results | `./data/tool-results` |
| `KNOWFLOW_TOOL_RESULT_CONTEXT_CHARS` | Maximum tool-result characters sent directly back to the model | `12000` |
| `KNOWFLOW_TOOL_RESULT_STORAGE_CHARS` | Maximum characters retained for one oversized tool result | `2000000` |
| `KNOWFLOW_TOOL_RESULT_RETENTION_SECONDS` | Retention period for per-run oversized tool results | `604800` |
| `KNOWFLOW_AGENT_MAX_TOOL_CONCURRENCY` | Maximum concurrent explicitly safe read-only tool calls | `4` |
| `KNOWFLOW_AGENT_TOOL_SEARCH_THRESHOLD` | Deferred MCP tool count that enables contextual ToolSearch | `8` |
| `KNOWFLOW_AGENT_CONTEXT_MAX_TOKENS` | Approximate per-model-call context budget; durable checkpoint history is retained | `96000` |
| `KNOWFLOW_WORKSPACE_ENABLED` | Expose per-user isolated workspace file tools | `0` |
| `KNOWFLOW_WORKSPACE_DIR` | Parent directory for isolated user workspaces | `./data/workspaces` |
| `KNOWFLOW_WORKSPACE_MAX_FILE_BYTES` | Maximum UTF-8 file size accepted by workspace tools | `1000000` |
| `KNOWFLOW_SANDBOX_ENABLED` | Expose shell execution only through Anthropic Sandbox Runtime | `0` |
| `KNOWFLOW_SANDBOX_COMMAND` | Sandbox Runtime CLI executable | `srt` |
| `KNOWFLOW_SANDBOX_SHELL` | Non-interactive Linux shell launched inside the sandbox | `bash` |
| `KNOWFLOW_SANDBOX_LIMIT_COMMAND` | Linux util-linux resource limiter | `prlimit` |
| `KNOWFLOW_SANDBOX_TIMEOUT` | Maximum sandbox command runtime in seconds | `60` |
| `KNOWFLOW_SANDBOX_MAX_OUTPUT_BYTES` | Maximum stdout/stderr retained per sandbox command | `1000000` |
| `KNOWFLOW_SANDBOX_MEMORY_MB` | Maximum virtual memory for one sandbox command | `1024` |
| `KNOWFLOW_SANDBOX_MAX_PROCESSES` | Maximum processes for one sandbox command | `128` |
| `KNOWFLOW_SANDBOX_MAX_FILE_BYTES` | Maximum file size created by one sandbox command | `104857600` |
| `KNOWFLOW_SECRET_KEY` | Key used to encrypt stored model API keys | `change-this-dev-secret` |
| `KNOWFLOW_LANGGRAPH_CHECKPOINT_DB` | Separate SQLite file for LangGraph execution checkpoints | `./data/langgraph/checkpoints.sqlite3` |
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

Each chat model configuration can select either Chat Completions or the Responses API. Chat Completions is intended for traditional OpenAI-compatible endpoints. Responses sends `stream: true` to `POST /v1/responses`, expects standard SSE events, and requires a final `response.completed` event. Text deltas are forwarded to the browser as they arrive; tool arguments are aggregated before execution. KnowFlow does not auto-detect protocol support or downgrade after a failure, preventing duplicate requests or tool execution. If a compatible gateway returns HTTP 400, check that the selected model route supports Responses SSE rather than only Chat Completions. The OpenAI chat preset defaults to Responses, while existing configurations and configurations with the protocol field omitted default to Chat Completions. Mem0's separate LLM configuration is independent of the protocol selection in the settings page.

## Agent Tools and Traces

Each signed-in user configures their own Tavily key in the 设置页. The backend encrypts it in `tool_config`, never returns the plaintext key, and does not load a global Tavily key from the environment or startup script. The connection check uses one Tavily credit.

`web_search` is a native OpenAI-compatible function tool. KnowFlow sends its schema through `tools` only when the current user has enabled a valid configuration, then uses `tool_choice: auto` so the model decides whether the question needs current or external information. Ordinary questions are not forced to search. Tavily is the first search provider and is called through its HTTP API, without a provider SDK.

Agent progress is emitted as sanitized SSE events. The chat message shows the current step, while the right-side Agent运行图 displays the full nested `model`, `tool`, `mcp`, `skill`, `agent`, `system`, and `approval` protocol. It exposes only bounded public input and result summaries, never hidden chain-of-thought, system prompts, credentials, or raw request logs.

The completed Trace snapshot is stored with the assistant message. Reopening a session restores the same execution view, including completed and failed states.

Longer Agent tasks also persist a public plan and step state in the database. The model may answer simple requests directly; when it creates a plan, the current step lights in the run drawer and tool or MCP traces stay nested under that step. Prefix a request with `/plan` to create the plan without executing it, then choose 开始执行 or 重新规划.

Execution and live SSE subscriptions are process-local, while run, plan, trace, approval, and message state are durable. Refreshing the page reconnects to an active run in the same backend process. A backend restart marks in-progress model or tool work as 已中断, but preserves a LangGraph run that is safely paused at an approval checkpoint. A backend approval runner expires overdue approvals and resumes the current checkpoint with its durable decision, including after a restart or when the browser is closed; a timeout never calls the write handler. The UI uses the same server-issued expiry time for immediate feedback. Cancelling a run also invalidates its pending approvals. Keep this deployment on one backend worker until the run coordinator moves to shared infrastructure.

The backend routes every Agent request through LangGraph. The former handwritten `current` engine and its process-local approval broker have been removed. Historical `current` runs are never resumed because doing so could repeat an unrecorded side effect; users restart them as a new LangGraph run instead. LangGraph runs RAG retrieval, memory recall, the model/tool loop, Skills, and task planning with durable checkpoints while preserving the selected Chat Completions or Responses API transport, streaming events, audits, and run records. A Skill activation is saved as an immutable version snapshot; checkpoint resume revalidates ownership, dependencies, version, and content hash before restoring resource access. Read-only calls run directly, while write, destructive, or unknown-risk calls use LangGraph `interrupt()` and a durable user/run/tool-call approval record. Each approved write is atomically claimed and its result is persisted; an indeterminate remote side effect is never automatically repeated. Tool schemas and execution use the same dynamic engine allow-list. Checkpoints are keyed by user and run ID in the separate SQLite file. RAG and Mem0 snapshots are reused across approval resumes and later plan steps; either context source can fail closed to an empty snapshot without failing the answer. Post-answer memory extraction remains in the existing durable background queue so it never delays the response.

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

For deployment, each backup must include the application database, `data/skills`, `data/tool-results`, `data/workspaces`, and the file configured by `KNOWFLOW_LANGGRAPH_CHECKPOINT_DB` together. Take the database, workspace, tool-result, and LangGraph checkpoint copies from the same stopped-service snapshot so interrupted runs never point at missing or mismatched data. `data/skill-imports` contains temporary previews and may be cleared. The service user needs write permission on the Skill, workspace, tool-result, and checkpoint directories; deployments with multiple workers must share the same persistent volume. Before an upgrade, run the repository checks and frontend build. Never commit user-installed packages, workspace contents, stored tool results, or checkpoint data to Git.

Pushes to`main`先在Ubuntu CI中安装依赖、构建前端并运行全部检查。通过后，CI生成按commit命名的Linux部署包、SHA-256校验文件和内容清单，保留14天；部署包只包含后端源码、已构建前端、部署脚本和README，不包含`.env`、运行数据或依赖缓存。

服务器可使用CI门禁后的快速同步脚本，避免重复运行全量检查。脚本拒绝脏工作树和不属于`origin/main`的提交，确认目标commit的push CI成功后才切换代码；仅当依赖文件哈希变化时执行`pip install`或`npm ci`，仅当前端源码变化时重新构建，最后只重启一次并检查本地健康端点：

```bash
sudo bash /opt/knowflow-ai/app/deploy/fast-deploy.sh <目标commit>
```

首次使用新脚本时，可从目标commit读取到临时文件再执行，避免先手工切换代码：

```bash
cd /opt/knowflow-ai/app
git fetch origin main
git show <目标commit>:deploy/fast-deploy.sh > /tmp/knowflow-fast-deploy.sh
sudo bash /tmp/knowflow-fast-deploy.sh <目标commit>
```

快速同步信任同一commit已经成功的GitHub Actions完整门禁，因此服务器不再重复运行`tests/check_*.py`。数据库和运行数据备份仍是部署前的独立操作，脚本不会读取、复制或修改`.env`和`data`内容。

### Linux Agent运行环境

Workspace file tools are disabled by default and each user receives a separate directory under `KNOWFLOW_WORKSPACE_DIR`. Shell execution has an additional hard gate: `run_sandbox_command` is registered only when both workspace and sandbox support are enabled and the `srt` executable is available. Commands always require approval, receive a scrubbed environment, cannot access the network, and may write only inside that user's workspace.

Agent运行时仅支持Linux。Windows和macOS可以作为浏览器客户端访问部署后的KnowFlow，但不会在本机执行Agent命令。生产环境建议Ubuntu 24.04、非root服务用户、单worker和systemd状态目录。

安装Anthropic Sandbox Runtime及其Linux依赖：

```bash
sudo apt-get update
sudo apt-get install -y bubblewrap util-linux
npm install -g @anthropic-ai/sandbox-runtime
srt --version
```

生产环境将`KNOWFLOW_DATA_DIR`设为`/var/lib/knowflow-ai`，并让systemd通过`StateDirectory=knowflow-ai`创建该目录。`KNOWFLOW_DB_URL`需明确改为`sqlite:////var/lib/knowflow-ai/knowflow.db`或外部数据库地址；若环境文件还显式配置了上传、Skill、工具结果、Workspace或checkpoint路径，这些值会覆盖数据根目录的派生默认值，也必须同步迁移或删除覆盖项。不要在部署脚本中以root身份预先运行应用或创建其子目录；应用启动时会以服务用户创建并检查运行路径。任一路径不可读写时启动直接失败，避免运行到一半才出现`PermissionError`。

启用执行工具时设置`KNOWFLOW_WORKSPACE_ENABLED=1`和`KNOWFLOW_SANDBOX_ENABLED=1`。启用后，启动门禁还会要求当前主机为Linux，且`srt`与`bash`均可执行；不会静默退化为无沙箱命令。

### 长期记忆（Mem0）

KnowFlow通过`MemoryProvider`接入开源`mem0ai==2.0.14`。Mem0只负责长期记忆，不会接管Agent循环、任务计划、Skills、工具或MCP。LangGraph执行器把每轮召回作为首个节点，最多读取`KNOWFLOW_MEMORY_TOP_K`条相关记忆并保存到checkpoint；审批恢复和同一计划的后续步骤复用该快照，不重复请求Mem0。召回异常会在Trace中标记为降级，但不会阻断模型回答。assistant消息成功写入数据库后，再由现有持久队列异步运行ADD-only记忆提取。

记忆使用服务端专用LLM和Embedding配置。复制`backend/.env.example`中的`KNOWFLOW_MEMORY_*`变量，填写两个模型Key后，将`KNOWFLOW_MEMORY_ENABLED`设为`1`。如果LLM和Embedding使用同一个兼容OpenAI的服务，`KNOWFLOW_MEMORY_EMBEDDER_API_KEY`可以留空复用LLM Key。未完成服务端配置时，聊天仍然正常运行，记忆页会显示“未配置”。

登录用户在“记忆”页单独启用或停用，查看、纠正、删除自己的记忆。所有Mem0读写都强制使用认证用户ID作为`filters.user_id`，客户端不能指定其他用户。进入Mem0前会移除常见Token、Key、密码和Authorization Bearer值；工具原始输出不会直接写入长期记忆。

默认数据位于`data/mem0/qdrant`和`data/mem0/history.db`。这些目录不进入Git，生产备份必须将主数据库与整个`data/mem0`一起保存。使用本地Qdrant路径时后端保持单worker；多worker部署应改用独立Qdrant服务。升级Mem0前先固定新版本并运行`tests/check_memory_*.py`及全量检查，避免上游API变化破坏隔离规则。

### Remote MCP servers

The 工具与MCP page manages remote MCP connections for the current signed-in user. The built-in Notion preset uses the official `https://mcp.notion.com/mcp` endpoint with user OAuth; it does not ask for a Notion integration token. Select 连接Notion, finish authorization in Notion, return to the settings page, and use 刷新工具 when the remote tool catalog changes. 停用 immediately removes that server's tools from later Agent runs and clears its local authorization.

Custom public HTTPS servers use the Streamable HTTP transport. The add-server dialog supports three authentication modes:

- No authentication.
- Static headers, encrypted with `KNOWFLOW_SECRET_KEY` and never returned in plaintext.
- Standard OAuth with dynamic client registration or an administrator-provided client ID and optional secret.

The model can autonomously choose enabled native or MCP tools. A tool explicitly marked read-only runs automatically. Write, delete, destructive, or unknown-risk operations pause the Agent and require an approval in both the chat message and the run drawer. “允许本次” authorizes only that invocation; enabling a tool is not permanent approval for writes.

Remote URLs are revalidated against SSRF rules before discovery and connection. Private and loopback networks are rejected by default. `KNOWFLOW_MCP_ALLOW_PRIVATE_NETWORKS=1` is only for a controlled local development server; do not enable it in an internet-facing deployment.

Tool approvals are stored durably in the database and resumed through LangGraph checkpoints. Approval records are isolated by user and Agent run, expire after `KNOWFLOW_MCP_APPROVAL_TIMEOUT`, and use an atomic one-time execution claim so an approved write is not replayed after a retry or restart. Keep the LangGraph checkpoint database protected and backed up with the main database because it can contain conversation and tool context.

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
POST {baseUrl}/responses
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
