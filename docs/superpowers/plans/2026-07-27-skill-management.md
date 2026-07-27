# Skill Management and On-Demand Activation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add secure, per-user Skill installation and management, Codex-style `/` selection, and one-Skill-per-run automatic or explicit Agent activation.

**Architecture:** Skill packages are immutable, validated snapshots stored below a server-owned data directory and referenced through per-user installation rows. A short-lived staged import separates inspection from installation. The Agent exposes only enabled Skill metadata, lazily loads one `SKILL.md` through an internal activation capability, and keeps all tool, MCP, approval, and trace policy in the existing runtime.

**Tech Stack:** FastAPI, Pydantic 2, SQLAlchemy 2, SQLite/MySQL DDL, PyYAML `safe_load`, Python `zipfile`, Requests, React 18, Vite, existing `tests/check_*.py` executable checks.

---

## File Structure

### Backend files to create

- `backend/knowflow/services/skill_manifest.py` — parse and validate `SKILL.md`, normalize KnowFlow metadata, and compute content hashes.
- `backend/knowflow/services/skill_archive.py` — validate ZIP members and extract a bounded package without links, traversal, nested archives, or executable binaries.
- `backend/knowflow/services/skill_store.py` — staged import persistence, immutable package snapshots, user installations, dependency status, update, and delete cleanup.
- `backend/knowflow/services/skill_runtime.py` — build the visible Skill catalog and activate exactly one Skill for an Agent run.
- `backend/knowflow/routers/skills.py` — authenticated list, inspect, install, detail, content, enable, update, and delete endpoints.

### Backend files to modify

- `backend/requirements.txt` — pin PyYAML.
- `backend/.env.example` — document bounded Skill storage/import settings.
- `backend/knowflow/config.py` — resolve Skill directories and clamp import limits.
- `backend/knowflow/db_schema.py` — add `skill_package`, `user_skill`, and `skill_import`; persist used Skill snapshot fields.
- `backend/knowflow/database.py` — bump the schema version and migrate existing databases.
- `backend/knowflow/runtime.py` — instantiate `SkillStore` and persist Skill snapshot metadata with messages/tool calls.
- `backend/knowflow/schemas.py` — Skill request models and optional `ChatRequest.skillId`.
- `backend/knowflow/routers/__init__.py` — register the Skill router.
- `backend/knowflow/app.py` — publish the Skills OpenAPI tag.
- `backend/knowflow/responses.py` — preserve stable string error codes.
- `backend/knowflow/routers/chat.py` — always route explicit Skill requests through the Agent runtime.
- `backend/knowflow/routers/extensions.py` — load the user catalog, register automatic activation, activate an explicit Skill, and parent subsequent trace steps.
- `backend/knowflow/services/agent_loop.py` — expose registry names and allow a successful Skill activation to become the parent of later steps.
- `backend/knowflow/services/approval.py` — move later approvals below an automatically activated Skill trace node.

### Frontend files to create

- `frontend/react/src/components/SkillsPage.jsx` — lightweight installed/built-in list and page-level mutations.
- `frontend/react/src/components/SkillInstallDialog.jsx` — one compact GitHub/ZIP inspect-and-install modal.
- `frontend/react/src/components/SkillDetailDrawer.jsx` — on-demand summary and read-only `SKILL.md`.
- `frontend/react/src/components/SkillPicker.jsx` — accessible Codex-style `/` listbox.

### Frontend files to modify

- `frontend/react/src/api/client.js` — `skillApi`.
- `frontend/react/src/App.jsx` — Skills page key and mounted page.
- `frontend/react/src/data/navigation.js` — Skills navigation item.
- `frontend/react/src/components/Sidebar.jsx` — Skills icon.
- `frontend/react/src/components/ChatComposerForm.jsx` — slash query, selected Skill pill, keyboard control, and `skillId` submission.
- `frontend/react/src/controller/bridgeBindings.js` — forward `skillId`.
- `frontend/react/src/controller/chatFlow.js` — send and retain `skillId` in retry snapshots.
- `frontend/react/src/components/AgentTraceView.jsx` — Skill title and safe version/source/dependency details.
- `frontend/styles.css` — canonical lightweight page, modal, drawer, pill, picker, focus, and responsive styles.

### Checks to create or extend

- Create `tests/check_skill_schema.py`
- Create `tests/check_skill_manifest.py`
- Create `tests/check_skill_archive_security.py`
- Create `tests/check_skill_github_source.py`
- Create `tests/check_skill_import_api.py`
- Create `tests/check_skill_api.py`
- Create `tests/check_skill_runtime.py`
- Create `tests/check_skill_trace.py`
- Create `tests/check_frontend_skills_page_react.py`
- Create `tests/check_frontend_skill_picker_react.py`
- Modify `tests/check_frontend_agent_trace_react.py`
- Modify `tests/check_frontend_chat_flow_module.py`
- Modify `tests/check_frontend_page_navigation_react.py`
- Modify `tests/check_release_hygiene.py`

## Task 1: Add Skill schema, storage settings, and dependency

**Files:**

- Modify: `backend/requirements.txt`
- Modify: `backend/knowflow/config.py`
- Modify: `backend/knowflow/db_schema.py`
- Modify: `backend/knowflow/database.py`
- Create: `tests/check_skill_schema.py`

- [ ] **Step 1: Write the failing schema check**

Create an isolated SQLite database before importing the application. Assert schema version `5`, all three tables, required columns, and the used-Skill columns:

```python
def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "skill-schema.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    os.environ["KNOWFLOW_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["KNOWFLOW_VECTOR_BACKEND"] = "local"
    sys.path.insert(0, str(BACKEND))

    from knowflow.database import CURRENT_SCHEMA_VERSION
    from knowflow.db_schema import MYSQL_SCHEMA
    from knowflow.runtime import fetch_all

    assert CURRENT_SCHEMA_VERSION == 5
    tables = {
        row["name"]
        for row in fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"skill_package", "user_skill", "skill_import"} <= tables
    package_columns = {
        row["name"]
        for row in fetch_all("PRAGMA table_info(skill_package)")
    }
    assert {
        "id", "owner_user_id", "slug", "display_name", "description",
        "version", "source_kind", "source_url", "source_ref",
        "source_subpath", "content_hash", "package_path",
        "manifest_json", "created_at",
    } <= package_columns
    user_skill_columns = {
        row["name"]
        for row in fetch_all("PRAGMA table_info(user_skill)")
    }
    assert {
        "id", "user_id", "skill_package_id", "skill_slug",
        "enabled", "installed_at", "updated_at",
    } <= user_skill_columns
    for table in ("chat_message", "agent_tool_call"):
        columns = {
            row["name"]
            for row in fetch_all(f"PRAGMA table_info({table})")
        }
        assert {
            "skill_id", "skill_slug", "skill_version",
            "skill_content_hash",
        } <= columns
    assert "CREATE TABLE IF NOT EXISTS skill_package" in MYSQL_SCHEMA
    print("skill schema initializes and migrates on SQLite and MySQL")
```

- [ ] **Step 2: Run the schema check and verify failure**

Run:

```powershell
python tests/check_skill_schema.py
```

Expected: FAIL because schema version 5 and the Skill tables do not exist.

- [ ] **Step 3: Pin PyYAML and add bounded configuration**

Add:

```text
PyYAML==6.0.2
```

Add these resolved settings in `config.py`:

```python
def bounded_env_int(
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    return max(minimum, min(maximum, env_int(name, default)))


SKILL_DIR = Path(
    os.getenv("KNOWFLOW_SKILL_DIR", str(DATA_DIR / "skills"))
).expanduser()
if not SKILL_DIR.is_absolute():
    SKILL_DIR = (PROJECT_DIR / SKILL_DIR).resolve()
SKILL_IMPORT_DIR = DATA_DIR / "skill-imports"
SKILL_MAX_ARCHIVE_BYTES = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_ARCHIVE_BYTES", 5 * 1024 * 1024, 1024, 20 * 1024 * 1024
)
SKILL_MAX_EXTRACTED_BYTES = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_EXTRACTED_BYTES", 20 * 1024 * 1024, 1024, 100 * 1024 * 1024
)
SKILL_MAX_FILES = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_FILES", 200, 1, 1000
)
SKILL_MAX_FILE_BYTES = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_FILE_BYTES", 2 * 1024 * 1024, 1024, 10 * 1024 * 1024
)
SKILL_MAX_DEPTH = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_DEPTH", 8, 1, 16
)
SKILL_MAX_BODY_CHARS = bounded_env_int(
    "KNOWFLOW_SKILL_MAX_BODY_CHARS", 50_000, 1000, 200_000
)
SKILL_IMPORT_TTL = bounded_env_int(
    "KNOWFLOW_SKILL_IMPORT_TTL", 900, 60, 3600
)
SKILL_GITHUB_TIMEOUT = bounded_env_int(
    "KNOWFLOW_SKILL_GITHUB_TIMEOUT", 15, 1, 60
)
SKILL_DIR.mkdir(parents=True, exist_ok=True)
SKILL_IMPORT_DIR.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Add SQLite and MySQL tables**

Add equivalent DDL for:

```sql
CREATE TABLE IF NOT EXISTS skill_package (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_user_id INTEGER,
  slug TEXT NOT NULL,
  display_name TEXT NOT NULL,
  description TEXT NOT NULL,
  version TEXT NOT NULL,
  source_kind TEXT NOT NULL,
  source_url TEXT,
  source_ref TEXT,
  source_subpath TEXT,
  content_hash TEXT NOT NULL,
  package_path TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (owner_user_id, slug, content_hash)
);
CREATE TABLE IF NOT EXISTS user_skill (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  skill_package_id INTEGER NOT NULL,
  skill_slug TEXT NOT NULL,
  enabled INTEGER DEFAULT 0,
  installed_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (user_id, skill_slug)
);
CREATE TABLE IF NOT EXISTS skill_import (
  id TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  source_kind TEXT NOT NULL,
  staged_path TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  preview_json TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

Use `BIGINT AUTO_INCREMENT`, bounded `VARCHAR`, `LONGTEXT`, and `TINYINT` equivalents in the MySQL block. Add `skill_id`, `skill_slug`, `skill_version`, and `skill_content_hash` to `chat_message` and `agent_tool_call`. The denormalized `user_skill.skill_slug` is the database-enforced current-installation identity; it must always match the referenced package slug.

- [ ] **Step 5: Add existing-database migration**

Set:

```python
CURRENT_SCHEMA_VERSION = 5
```

Use `add_column_if_missing()` for the eight message/tool-call columns and update the recorded description to:

```python
"Add per-user Skill packages, installations, staged imports, and run snapshots."
```

The three new tables are already created by the idempotent top-level DDL before migration runs.

- [ ] **Step 6: Run schema checks**

Run:

```powershell
python tests/check_skill_schema.py
python tests/check_schema_versioning.py
```

Expected: PASS. Update `check_schema_versioning.py` to expect version `5` and a description containing `skill`.

- [ ] **Step 7: Commit**

```powershell
git add backend/requirements.txt backend/knowflow/config.py backend/knowflow/db_schema.py backend/knowflow/database.py tests/check_skill_schema.py tests/check_schema_versioning.py
git commit -m "feat: add per-user skill persistence"
```

## Task 2: Parse and validate Skill packages securely

**Files:**

- Create: `backend/knowflow/services/skill_manifest.py`
- Create: `backend/knowflow/services/skill_archive.py`
- Create: `tests/check_skill_manifest.py`
- Create: `tests/check_skill_archive_security.py`

- [ ] **Step 1: Write manifest parser checks**

Cover required fields, stable defaults, extension metadata, body length, safe YAML, slug validation, and deterministic hashes:

```python
valid = """---
name: notion-research
description: Research Notion and public sources.
metadata:
  knowflow:
    display_name: Notion 调研整理
    version: 1.2.0
    required_tools: [web_search]
    required_mcp: [notion]
---
Follow the requested research workflow.
"""
parsed = parse_skill_markdown(valid, max_body_chars=50_000)
assert parsed.slug == "notion-research"
assert parsed.display_name == "Notion 调研整理"
assert parsed.version == "1.2.0"
assert parsed.required_tools == ("web_search",)
assert parsed.required_mcp == ("notion",)
assert parsed.body.startswith("Follow")
assert parsed.content_hash == parse_skill_markdown(
    valid, max_body_chars=50_000
).content_hash

for invalid in (
    "---\ndescription: missing name\n---\nBody",
    "---\nname: ../escape\ndescription: bad\n---\nBody",
    "---\nname: ok\ndescription: [not, text]\n---\nBody",
):
    try:
        parse_skill_markdown(invalid, max_body_chars=50_000)
    except SkillManifestError:
        pass
    else:
        raise AssertionError(invalid)
```

- [ ] **Step 2: Run and verify manifest failure**

```powershell
python tests/check_skill_manifest.py
```

Expected: FAIL because `skill_manifest.py` does not exist.

- [ ] **Step 3: Implement the manifest model and parser**

Use these public interfaces:

```python
@dataclass(frozen=True)
class SkillManifest:
    slug: str
    display_name: str
    description: str
    version: str
    required_tools: tuple[str, ...]
    required_mcp: tuple[str, ...]
    body: str
    raw_metadata: dict[str, Any]
    content_hash: str


class SkillManifestError(ValueError):
    code = "skill_invalid_manifest"


def parse_skill_markdown(
    content: str,
    *,
    max_body_chars: int,
) -> SkillManifest:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillManifestError("missing front matter")
    try:
        closing = next(
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration as exc:
        raise SkillManifestError("unterminated front matter") from exc
    raw = yaml.safe_load("\n".join(lines[1:closing])) or {}
    if not isinstance(raw, dict):
        raise SkillManifestError("front matter must be a mapping")
    slug = raw.get("name")
    description = raw.get("description")
    if not isinstance(slug, str) or not SLUG_PATTERN.fullmatch(slug):
        raise SkillManifestError("invalid name")
    if not isinstance(description, str) or not description.strip():
        raise SkillManifestError("invalid description")
    knowflow = (raw.get("metadata") or {}).get("knowflow") or {}
    if not isinstance(knowflow, dict):
        raise SkillManifestError("invalid knowflow metadata")

    def dependency_list(key: str) -> tuple[str, ...]:
        value = knowflow.get(key) or []
        if not isinstance(value, list) or not all(
            isinstance(item, str) and DEPENDENCY_PATTERN.fullmatch(item)
            for item in value
        ):
            raise SkillManifestError(f"invalid {key}")
        return tuple(dict.fromkeys(value))

    body = "\n".join(lines[closing + 1:]).strip()
    if len(body) > max_body_chars:
        raise SkillManifestError("body too large")
    return SkillManifest(
        slug=slug,
        display_name=str(knowflow.get("display_name") or slug)[:120],
        description=description.strip(),
        version=str(knowflow.get("version") or "0.0.0")[:64],
        required_tools=dependency_list("required_tools"),
        required_mcp=dependency_list("required_mcp"),
        body=body,
        raw_metadata=raw,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
```

Implementation requirements:

- Require an opening and closing `---`.
- Call `yaml.safe_load()` only on bounded front matter text.
- Require a mapping and string `name`/`description`.
- Match slug with `^[a-z0-9]+(?:-[a-z0-9]+)*$`.
- Normalize dependency lists into unique tuples of safe slugs/tool names.
- Default `display_name` to slug and version to `0.0.0`.
- Hash the exact UTF-8 content with SHA-256.
- Never interpolate YAML values into paths.

- [ ] **Step 4: Write malicious ZIP checks**

Build ZIPs in memory and assert rejection codes for traversal, absolute paths, links, nested archives, count, depth, member size, total size, executable binaries, and missing root `SKILL.md`:

```python
cases = {
    "traversal": {"../escape.txt": b"x"},
    "absolute": {"/escape.txt": b"x"},
    "nested_archive": {"SKILL.md": VALID, "payload.zip": b"PK"},
    "binary": {"SKILL.md": VALID, "payload.exe": b"MZ"},
    "missing_manifest": {"README.md": b"x"},
}
for expected, members in cases.items():
    archive = make_zip(members)
    try:
        inspect_and_extract_zip(
            archive,
            destination=tmp_path / expected,
            limits=TEST_LIMITS,
        )
    except SkillArchiveError as exc:
        assert exc.reason == expected, (expected, exc.reason)
    else:
        raise AssertionError(expected)
```

Construct a Unix symlink member by setting `ZipInfo.external_attr` and assert `link` rejection.

- [ ] **Step 5: Implement bounded ZIP inspection**

Expose:

```python
@dataclass(frozen=True)
class SkillArchiveLimits:
    max_archive_bytes: int
    max_extracted_bytes: int
    max_files: int
    max_file_bytes: int
    max_depth: int


@dataclass(frozen=True)
class ExtractedSkill:
    root: Path
    manifest_path: Path
    file_count: int
    extracted_bytes: int


class SkillArchiveError(ValueError):
    code = "skill_import_rejected"


def inspect_and_extract_zip(
    archive: bytes,
    *,
    destination: Path,
    limits: SkillArchiveLimits,
) -> ExtractedSkill:
    if len(archive) > limits.max_archive_bytes:
        raise SkillArchiveError("archive_size")
    destination = destination.resolve()
    total = 0
    files = 0
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        members = bundle.infolist()
        for info in members:
            path = PurePosixPath(info.filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise SkillArchiveError("traversal")
            if len(path.parts) > limits.max_depth:
                raise SkillArchiveError("depth")
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type in {
                stat.S_IFLNK, stat.S_IFBLK, stat.S_IFCHR,
                stat.S_IFIFO, stat.S_IFSOCK,
            }:
                raise SkillArchiveError("link")
            if info.is_dir():
                continue
            files += 1
            total += info.file_size
            if files > limits.max_files:
                raise SkillArchiveError("file_count")
            if info.file_size > limits.max_file_bytes:
                raise SkillArchiveError("file_size")
            if total > limits.max_extracted_bytes:
                raise SkillArchiveError("extracted_size")
            suffix = path.suffix.lower()
            if suffix in ARCHIVE_SUFFIXES:
                raise SkillArchiveError("nested_archive")
            if suffix not in ALLOWED_SKILL_SUFFIXES:
                raise SkillArchiveError("binary")

        try:
            destination.mkdir(parents=True, exist_ok=False)
            for info in members:
                if info.is_dir():
                    continue
                path = PurePosixPath(info.filename.replace("\\", "/"))
                target = destination.joinpath(*path.parts).resolve()
                if destination not in target.parents:
                    raise SkillArchiveError("traversal")
                target.parent.mkdir(parents=True, exist_ok=True)
                remaining = min(info.file_size, limits.max_file_bytes)
                with bundle.open(info) as source, target.open("wb") as output:
                    while remaining:
                        chunk = source.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        output.write(chunk)
                        remaining -= len(chunk)
                    if source.read(1):
                        raise SkillArchiveError("file_size")
            manifests = list(destination.rglob("SKILL.md"))
            if not manifests:
                raise SkillArchiveError("missing_manifest")
            return ExtractedSkill(
                root=destination,
                manifest_path=manifests[0],
                file_count=files,
                extracted_bytes=total,
            )
        except Exception:
            shutil.rmtree(destination, ignore_errors=True)
            raise
```

Validate every member before writing any member. Use `PurePosixPath`, reject empty/absolute/`..` components, reject link/device mode bits with `stat.S_IFMT(info.external_attr >> 16)`, enforce the extension allowlist, and use `shutil.copyfileobj()` with a remaining-byte counter rather than `ZipFile.extractall()`. Delete the destination on any failure.

- [ ] **Step 6: Run parser and archive checks**

```powershell
python tests/check_skill_manifest.py
python tests/check_skill_archive_security.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add backend/knowflow/services/skill_manifest.py backend/knowflow/services/skill_archive.py tests/check_skill_manifest.py tests/check_skill_archive_security.py
git commit -m "feat: validate skill packages securely"
```

## Task 3: Add per-user staged import and management API

**Files:**

- Create: `backend/knowflow/services/skill_store.py`
- Create: `backend/knowflow/routers/skills.py`
- Create: `backend/knowflow/builtin_skills/deep-research/SKILL.md`
- Create: `backend/knowflow/builtin_skills/notion-research/SKILL.md`
- Modify: `backend/knowflow/runtime.py`
- Modify: `backend/knowflow/schemas.py`
- Modify: `backend/knowflow/routers/__init__.py`
- Modify: `backend/knowflow/app.py`
- Modify: `backend/knowflow/responses.py`
- Create: `tests/check_skill_github_source.py`
- Create: `tests/check_skill_import_api.py`
- Create: `tests/check_skill_api.py`

- [ ] **Step 1: Write GitHub source policy checks**

Test:

```python
source = parse_github_source(
    "https://github.com/example/agent-skills",
    ref="main",
    subpath="skills/notion-research",
)
assert source.owner == "example"
assert source.repo == "agent-skills"
assert source.ref == "main"
assert source.subpath == "skills/notion-research"

for rejected in (
    "http://github.com/example/repo",
    "https://github.com@example.invalid/repo",
    "https://raw.githubusercontent.com/example/repo/main/file",
    "https://github.com/../repo",
    "https://user:token@github.com/example/repo",
):
    assert_github_rejected(rejected)
```

Fake the HTTP session and assert download rejects non-GitHub redirect targets and bodies exceeding `SKILL_MAX_ARCHIVE_BYTES`.

- [ ] **Step 2: Implement GitHub normalization and bounded download**

Add to `skill_store.py`:

```python
@dataclass(frozen=True)
class GitHubSkillSource:
    owner: str
    repo: str
    ref: str
    subpath: str


class SkillStoreError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


GITHUB_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
GITHUB_REF = re.compile(r"^[A-Za-z0-9_./-]+$")


def parse_github_source(
    url: str,
    *,
    ref: str = "main",
    subpath: str = "",
) -> GitHubSkillSource:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise SkillStoreError("skill_import_rejected")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2:
        raise SkillStoreError("skill_import_rejected")
    owner, repo = parts
    repo = repo.removesuffix(".git")
    if not GITHUB_PART.fullmatch(owner) or not GITHUB_PART.fullmatch(repo):
        raise SkillStoreError("skill_import_rejected")
    if not GITHUB_REF.fullmatch(ref):
        raise SkillStoreError("skill_import_rejected")
    clean_subpath = PurePosixPath(subpath or ".")
    if clean_subpath.is_absolute() or ".." in clean_subpath.parts:
        raise SkillStoreError("skill_import_rejected")
    return GitHubSkillSource(
        owner=owner,
        repo=repo,
        ref=ref,
        subpath="" if str(clean_subpath) == "." else str(clean_subpath),
    )
```

Construct the codeload URL from validated owner/repo/ref. Call Requests with `allow_redirects=False`, `stream=True`, `trust_env=False`, the configured timeout, and a bounded chunk loop. Do not accept user headers or credentials.

- [ ] **Step 3: Write staged import API checks**

Use Alice and Bob `TestClient`s and a fake GitHub downloader. Assert:

```python
inspection = alice.post(
    "/api/skills/import/github/inspect",
    json={
        "url": "https://github.com/example/agent-skills",
        "ref": "main",
        "subpath": "skills/notion-research",
    },
)
assert inspection.status_code == 200, inspection.text
preview = inspection.json()["data"]
assert preview["name"] == "Notion 调研整理"
assert preview["scriptsExecutable"] is False

assert bob.post(
    f"/api/skills/import/{preview['importId']}/install",
    json={"enabled": True},
).status_code == 404

installed = alice.post(
    f"/api/skills/import/{preview['importId']}/install",
    json={"enabled": True},
)
assert installed.status_code == 200, installed.text
assert installed.json()["data"]["owner"] == "personal"
```

Also assert expired IDs return `410 skill_import_expired`, malformed packages leave no `skill_package` row, and a second install of the same slug replaces the installation only after the new snapshot succeeds.

- [ ] **Step 4: Implement `SkillStore`**

Use a constructor that stores the injected database helpers, engine, clock, roots, limits, TTL, body limit, and `dependency_resolver(user_id, manifest)` as private fields. The resolver derives native availability from the current user's enabled `tool_config` and MCP availability from enabled, connected `mcp_server.slug` rows; manifest declarations never create availability. Implement the following concrete methods: `list_for_user`, `get_for_user`, `inspect_github`, `inspect_upload`, `install`, `set_enabled`, `check_update`, `update`, and `delete`.

```python
with self.engine.begin() as conn:
    package_result = conn.execute(
        text(
            """
            INSERT INTO skill_package(
                owner_user_id, slug, display_name, description, version,
                source_kind, source_url, source_ref, source_subpath,
                content_hash, package_path, manifest_json, created_at
            )
            VALUES(
                :user_id, :slug, :display_name, :description, :version,
                :source_kind, :source_url, :source_ref, :source_subpath,
                :content_hash, :package_path, :manifest_json, :now
            )
            """
        ),
        {
            "user_id": user_id,
            "slug": preview["slug"],
            "display_name": preview["name"],
            "description": preview["description"],
            "version": preview["version"],
            "source_kind": preview["sourceKind"],
            "source_url": preview.get("sourceUrl"),
            "source_ref": preview.get("sourceRef"),
            "source_subpath": preview.get("sourceSubpath"),
            "content_hash": preview["contentHash"],
            "package_path": final_relative_path.as_posix(),
            "manifest_json": json.dumps(preview["manifest"], ensure_ascii=False),
            "now": self.now(),
        },
    )
    package_id = int(package_result.lastrowid)
    conn.execute(
        text(
            """
            INSERT INTO user_skill(
                user_id, skill_package_id, skill_slug, enabled,
                installed_at, updated_at
            )
            VALUES(
                :user_id, :package_id, :slug, :enabled, :now, :now
            )
            ON CONFLICT(user_id, skill_slug) DO UPDATE SET
                skill_package_id=excluded.skill_package_id,
                enabled=excluded.enabled,
                updated_at=excluded.updated_at
            """
        ),
        {
            "user_id": user_id,
            "package_id": package_id,
            "slug": preview["slug"],
            "enabled": int(enabled and preview["available"]),
            "now": self.now(),
        },
    )
    conn.execute(
        text("DELETE FROM skill_import WHERE id=:id AND user_id=:user_id"),
        {"id": import_id, "user_id": user_id},
    )
```

Use the shown transaction for SQLite and the equivalent `ON DUPLICATE KEY UPDATE` statement for MySQL. Move the validated directory to its server-generated final location before entering the transaction; if the transaction fails, remove only that new directory. Commit database deletion before best-effort file cleanup. Serialize only relative package paths. Return dependency fields but never raw filesystem paths.

Resolve package paths by `source_kind`: built-ins are relative to `backend/knowflow/builtin_skills`, while personal snapshots are relative to `SKILL_DIR`. Never accept or persist an absolute path. On startup, sync the two bundled Skills and lazily create disabled `user_skill` rows for each user; built-ins are disabled by default until that user enables them.

For GitHub archives, securely extract the bounded repository archive first, resolve the validated `subpath` below the extracted repository root, and require exactly one `SKILL.md` at that selected Skill root. An empty subpath is valid only when the repository resolves to one Skill root. Never search outside the selected subpath or silently choose the first of several manifests.

- [ ] **Step 5: Add request models and router**

Add strict models:

```python
class SkillGitHubInspect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=500)
    ref: str = Field(default="main", min_length=1, max_length=200)
    subpath: str = Field(default="", max_length=500)


class SkillInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False


class SkillUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
```

Register routes exactly as specified in the design. Map `SkillStoreError` codes to 400/404/409/410/413 without returning `str(exc)` when it could contain paths. Use `UploadFile` and a bounded read for ZIP inspection.

Add a `Skills` entry to `OPENAPI_TAGS`. Change the shared API response helpers so their `code` type is `int | str` and remove any forced `int(code)` conversion; existing numeric success/error codes must remain unchanged.

- [ ] **Step 6: Add API ownership and lifecycle checks**

In `check_skill_api.py`, assert:

- Alice and Bob receive only their own personal rows plus built-ins.
- Wrong-owner detail, content, patch, update, and delete return the same 404 as missing IDs.
- Built-ins cannot be deleted but can be independently enabled.
- Missing dependencies prevent enabling with 409.
- Update failure keeps the old `skill_package_id`.
- Content returns bounded plain text, not HTML.
- Delete commits before file cleanup and remains successful when cleanup raises.

- [ ] **Step 7: Run API checks**

```powershell
python tests/check_skill_github_source.py
python tests/check_skill_import_api.py
python tests/check_skill_api.py
```

Expected: PASS with no real network calls.

- [ ] **Step 8: Commit**

```powershell
git add backend/knowflow/services/skill_store.py backend/knowflow/routers/skills.py backend/knowflow/builtin_skills/deep-research/SKILL.md backend/knowflow/builtin_skills/notion-research/SKILL.md backend/knowflow/runtime.py backend/knowflow/schemas.py backend/knowflow/routers/__init__.py backend/knowflow/app.py backend/knowflow/responses.py tests/check_skill_github_source.py tests/check_skill_import_api.py tests/check_skill_api.py
git commit -m "feat: add per-user skill management api"
```

## Task 4: Activate one Skill inside the Agent loop

**Files:**

- Create: `backend/knowflow/services/skill_runtime.py`
- Modify: `backend/knowflow/services/agent_loop.py`
- Modify: `backend/knowflow/services/approval.py`
- Modify: `backend/knowflow/routers/chat.py`
- Modify: `backend/knowflow/routers/extensions.py`
- Modify: `backend/knowflow/runtime.py`
- Modify: `backend/knowflow/schemas.py`
- Create: `tests/check_skill_runtime.py`
- Create: `tests/check_skill_trace.py`

- [ ] **Step 1: Write explicit and automatic activation checks**

Use a fake model gateway and installed Skill. Assert explicit activation adds instructions before the first gateway call:

```python
response = alice.post(
    "/api/chat",
    json={
        "question": "整理项目进展",
        "chatModelConfigId": model_id,
        "enableTools": True,
        "skillId": skill_id,
    },
)
assert response.status_code == 200, response.text
first_messages = fake_gateway.calls[0]["messages"]
assert any(
    message["role"] == "system"
    and "ACTIVATED SKILL" in str(message["content"])
    and "Notion 调研整理" in str(message["content"])
    for message in first_messages
)
assert not any("scripts/" in str(message["content"]) for message in first_messages)
```

For automatic activation, return an `activate_skill` tool call first, then a normal tool call, then an answer. Assert the second gateway call contains the bounded Skill body and that another activation returns `skill_already_active`.

- [ ] **Step 2: Add Skill runtime interfaces**

Create:

```python
@dataclass(frozen=True)
class ActivatedSkill:
    installation_id: int
    package_id: int
    slug: str
    display_name: str
    version: str
    content_hash: str
    source_kind: str
    required_tools: tuple[str, ...]
    required_mcp: tuple[str, ...]
    system_message: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "skillId": self.installation_id,
            "skillSlug": self.slug,
            "skillVersion": self.version,
            "skillContentHash": self.content_hash,
        }


class ActivateSkillArguments(BaseModel):
    skill: str = Field(min_length=1, max_length=120)


class ReadSkillResourceArguments(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class SkillRuntimeError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class SkillActivationSession:
    def __init__(self, *, store: SkillStore, user_id: int, available_tools: set[str]) -> None:
        self.store = store
        self.user_id = user_id
        self.available_tools = set(available_tools)
        self.active: ActivatedSkill | None = None

    def catalog(self) -> list[dict[str, str]]:
        return self.store.activation_candidates(
            self.user_id,
            available_tools=self.available_tools,
        )

    def activate(self, skill: str | int) -> ToolHandlerResult:
        if self.active is not None:
            raise SkillRuntimeError("skill_already_active")
        self.active = self.store.resolve_for_activation(
            self.user_id,
            skill,
            available_tools=self.available_tools,
        )
        audit = {
            **self.active.snapshot(),
            "displayName": self.active.display_name,
            "sourceKind": self.active.source_kind,
            "requiredTools": list(self.active.required_tools),
            "requiredMcp": list(self.active.required_mcp),
        }
        return ToolHandlerResult(
            output={"instructions": self.active.system_message},
            audit_output=audit,
            skill_snapshot=self.active.snapshot(),
        )

    def read_resource(self, path: str) -> ToolHandlerResult:
        if self.active is None:
            raise SkillRuntimeError("skill_not_active")
        content = self.store.read_text_resource(
            self.user_id,
            self.active.package_id,
            path,
            max_chars=20_000,
        )
        return ToolHandlerResult(
            output={"path": path, "content": content},
            audit_output={"path": path, "characterCount": len(content)},
            skill_snapshot=self.active.snapshot(),
        )
```

`catalog()` returns only ID/slug/name/description. `activate()` rechecks ownership, enabled state, dependency availability, file existence, and hash. The returned tool result contains the wrapped instructions, but no paths.

Before adding `SkillActivationSession`, add the `ToolHandlerResult` dataclass shown in Step 3 to `agent_loop.py` and import it into `skill_runtime.py`; this keeps existing dictionary-returning tools source-compatible while giving activation a separate private model output and public audit output.

`read_resource()` is available only after activation. Resolve the requested relative path below the immutable package root, allow only UTF-8 text below `references/`, reject `scripts/`, traversal, links, binary files, and content over 20,000 characters. Imported images/PDFs remain stored and visible in package metadata but are not injected into the current text-only model gateway.

- [ ] **Step 3: Extend `ToolRegistry` and Agent parenting**

Add:

```python
def names(self) -> set[str]:
    return set(self._definitions)

def unregister(self, name: str) -> None:
    self._definitions.pop(name, None)
```

Recompute `registry.schemas()` at the start of every model round so activation can remove `activate_skill` and add `read_skill_resource`.

Introduce a safe handler result boundary:

```python
@dataclass
class ToolHandlerResult:
    output: dict[str, Any]
    audit_output: dict[str, Any] | None = None
    skill_snapshot: dict[str, Any] | None = None
```

`ToolExecution.model_content()` uses `output`; trace and database logging use `audit_output` (falling back to output for existing tools). The activation handler returns the full wrapped instructions only in `output`; `audit_output` contains name, version, source, hash, and dependency names. This prevents instructions from entering public trace or `agent_tool_call`.

Add `becomes_parent_on_success` and `remove_after_success` flags to `ToolDefinition`. In `AgentRunner.run()`, maintain:

```python
current_parent_step_id = parent_step_id
```

Use it for model and ordinary tool steps. Parent an activation tool step to the model step that selected it. After a successful execution whose definition has `becomes_parent_on_success`, set:

```python
current_parent_step_id = tool_step or current_parent_step_id
```

This makes later MCP/Tool/Model steps children of the activated Skill without changing approval behavior.

When `remove_after_success` is true, call `registry.unregister(prepared.tool_name)`. Update `AgentApprovalGate` with `set_parent_step_id()` and call it after automatic activation so later write approvals appear under the active Skill.

- [ ] **Step 4: Integrate explicit and automatic activation**

Add `skillId: int | None = None` to `ChatRequest`.

In `execute_agent_chat()`:

1. Build the normal native/MCP registry.
2. Create `SkillActivationSession`.
3. If `payload.skillId` is present, activate it before the first model call, emit and finish a `kind="skill"` trace step, inject the wrapped system message immediately after the base system message, and pass the Skill step as `parent_step_id`.
4. Otherwise, if the catalog is non-empty, register `activate_skill` as a read-only internal definition with `trace_kind="skill"`.
5. Successful activation removes `activate_skill` and registers the bounded `read_skill_resource` internal tool.
6. Add only the compact catalog to the base Agent system prompt.
7. After the run, obtain `activation.active.snapshot()` and pass it to message/tool-call persistence.

In `routers/chat.py`, return true from `should_route_to_agent()` whenever `payload.skillId is not None`, even if no normal tool is enabled. Validate an explicit Skill before saving the user message so an invalid/foreign/disabled ID does not leave an orphaned chat turn.

Public trace details must be:

```python
{
    "displayName": activated.display_name,
    "version": activated.version,
    "sourceKind": activated.source_kind,
    "requiredTools": list(activated.required_tools),
    "requiredMcp": list(activated.required_mcp),
}
```

Never put `system_message`, body, package path, or raw manifest in trace details.

- [ ] **Step 5: Persist used snapshot metadata**

Extend:

```python
def save_message(
    session_id: str,
    role: str,
    content: str,
    trace: list[dict[str, Any]] | None = None,
    skill_snapshot: dict[str, Any] | None = None,
) -> int:
    snapshot = skill_snapshot or {}
    return int(execute(
        """
        INSERT INTO chat_message(
            session_id, role, content, trace_json,
            skill_id, skill_slug, skill_version,
            skill_content_hash, created_at
        )
        VALUES(
            :session_id, :role, :content, :trace_json,
            :skill_id, :skill_slug, :skill_version,
            :skill_content_hash, :created_at
        )
        """,
        {
            "session_id": session_id,
            "role": role,
            "content": content,
            "trace_json": json.dumps(trace, ensure_ascii=False) if trace else None,
            "skill_id": snapshot.get("skillId"),
            "skill_slug": snapshot.get("skillSlug"),
            "skill_version": snapshot.get("skillVersion"),
            "skill_content_hash": snapshot.get("skillContentHash"),
            "created_at": now_str(),
        },
    ) or 0)
```

And `log_tool_call()` with the same optional snapshot. Bind the four explicit columns. Extend `normalize_chat_message()` to return a public `skill` summary only when all snapshot fields are present.

- [ ] **Step 6: Test security and trace behavior**

Assert:

- Bob cannot activate Alice's ID and receives the same 404 as a missing ID.
- Disabled, missing-dependency, missing-file, and hash-mismatch Skills fail with stable codes.
- Skill-required tool names are checked against the existing registry/MCP configuration; the Skill cannot register a new tool.
- A Skill attempting to say “skip approval” still encounters `AgentApprovalGate` for a write MCP tool.
- Trace shows `skill` and children using its `stepId` as `parentId`.
- Trace and API output do not contain the body, local path, email, key, or token.
- Historical messages retain name/version/hash after the installed version changes.

- [ ] **Step 7: Run Agent checks**

```powershell
python tests/check_skill_runtime.py
python tests/check_skill_trace.py
python tests/check_agent_loop.py
python tests/check_agent_approval.py
python tests/check_agent_trace_stream.py
python tests/check_agent_web_search_flow.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add backend/knowflow/services/skill_runtime.py backend/knowflow/services/agent_loop.py backend/knowflow/services/approval.py backend/knowflow/routers/chat.py backend/knowflow/routers/extensions.py backend/knowflow/runtime.py backend/knowflow/schemas.py tests/check_skill_runtime.py tests/check_skill_trace.py
git commit -m "feat: activate skills in agent runs"
```

## Task 5: Build the lightweight Skill management interface

**Files:**

- Create: `frontend/react/src/components/SkillsPage.jsx`
- Create: `frontend/react/src/components/SkillInstallDialog.jsx`
- Create: `frontend/react/src/components/SkillDetailDrawer.jsx`
- Modify: `frontend/react/src/api/client.js`
- Modify: `frontend/react/src/App.jsx`
- Modify: `frontend/react/src/data/navigation.js`
- Modify: `frontend/react/src/components/Sidebar.jsx`
- Modify: `frontend/styles.css`
- Create: `tests/check_frontend_skills_page_react.py`
- Modify: `tests/check_frontend_page_navigation_react.py`

- [ ] **Step 1: Write failing frontend contracts**

Require exact component/API/navigation contracts:

```python
require("frontend/react/src/App.jsx", '<SkillsPage active={activePage === "skills"}', "mounted Skills page")
require("frontend/react/src/data/navigation.js", 'page: "skills"', "Skills navigation")
require("frontend/react/src/api/client.js", "inspectGitHub", "GitHub inspect API")
require("frontend/react/src/api/client.js", "inspectUpload", "ZIP inspect API")
require("frontend/react/src/components/SkillsPage.jsx", 'statusFilter', "status filter")
require("frontend/react/src/components/SkillsPage.jsx", 'rowErrorById', "inline mutation error")
require("frontend/react/src/components/SkillInstallDialog.jsx", 'phase === "preview"', "same-modal preview")
require("frontend/react/src/components/SkillDetailDrawer.jsx", "<pre", "safe raw Markdown viewer")
require("frontend/styles.css", ".skills-list-row", "flat Skill list")
forbid("frontend/react/src/components/SkillsPage.jsx", "skills-overview", "dashboard statistic cards")
```

- [ ] **Step 2: Run and verify frontend contract failure**

```powershell
python tests/check_frontend_skills_page_react.py
python tests/check_frontend_page_navigation_react.py
```

Expected: FAIL because the Skills page is absent.

- [ ] **Step 3: Add `skillApi`**

Add:

```javascript
export const skillApi = {
  list: () => apiRequest("/api/skills"),
  get: (id) => apiRequest(`/api/skills/${id}`),
  content: (id) => apiRequest(`/api/skills/${id}/content`),
  inspectGitHub: (payload) =>
    apiRequest("/api/skills/import/github/inspect", {
      method: "POST",
      body: payload,
    }),
  inspectUpload: (file) => {
    const body = new FormData();
    body.append("file", file);
    return apiRequest("/api/skills/import/upload/inspect", {
      method: "POST",
      body,
    });
  },
  install: (importId, enabled) =>
    apiRequest(`/api/skills/import/${importId}/install`, {
      method: "POST",
      body: { enabled },
    }),
  setEnabled: (id, enabled) =>
    apiRequest(`/api/skills/${id}`, {
      method: "PATCH",
      body: { enabled },
    }),
  checkUpdate: (id) =>
    apiRequest(`/api/skills/${id}/check-update`, { method: "POST" }),
  update: (id) =>
    apiRequest(`/api/skills/${id}/update`, { method: "POST" }),
  delete: (id) =>
    apiRequest(`/api/skills/${id}`, { method: "DELETE" }),
};
```

- [ ] **Step 4: Add page navigation**

Add `"skills"` to `pageKeys`, mount `SkillsPage`, add the sidebar data item between knowledge and tools, and render a simple sparkle/cube SVG for `icon === "skills"`.

- [ ] **Step 5: Implement the flat list**

`SkillsPage` owns:

```javascript
const [skills, setSkills] = useState([]);
const [activeTab, setActiveTab] = useState("installed");
const [query, setQuery] = useState("");
const [statusFilter, setStatusFilter] = useState("all");
const [loading, setLoading] = useState(false);
const [busySkillId, setBusySkillId] = useState(null);
const [rowErrorById, setRowErrorById] = useState({});
const [installOpen, setInstallOpen] = useState(false);
const [selectedSkill, setSelectedSkill] = useState(null);
```

Load only when active. Filter “installed” to personal and “built-in” to `sourceKind === "builtin"`. The status rules are mutually exclusive: unavailable first, then enabled, then disabled. Do not optimistically flip the switch; disable it while awaiting `setEnabled()`, replace the row only on success, and set a one-line row error on failure. Dispatch `knowflow:react-skills-updated` after every successful mutation.

- [ ] **Step 6: Implement one compact install modal**

Keep state inside `SkillInstallDialog`:

```javascript
const [sourceTab, setSourceTab] = useState("github");
const [phase, setPhase] = useState("input");
const [preview, setPreview] = useState(null);
const [importId, setImportId] = useState(null);
const [inlineError, setInlineError] = useState("");
```

Phases are `input`, `inspecting`, `preview`, and `installing`; all render in the same modal. Preview name/version/file count/bytes/dependencies and the fixed message “脚本只保存，不执行”. A missing dependency permits install but clears “安装后启用”. Clear the selected `File` and `importId` on close.

- [ ] **Step 7: Implement the on-demand detail drawer**

Load summary on open and content only when the user chooses “查看 SKILL.md”. Render the content as:

```jsx
<pre className={"skill-source-view"}>{content}</pre>
```

Do not use `dangerouslySetInnerHTML`. Hide delete for built-ins and show update only for GitHub sources.

- [ ] **Step 8: Add canonical lightweight styles**

Add flat row styles to `frontend/styles.css`, not the generated React copy. Requirements:

- no overview statistic cards;
- 1px separators rather than boxed rows;
- one monochrome primary button;
- visible `:focus-visible`;
- modal and drawer use existing overlay primitives;
- no permanent right column;
- `@media (max-width: 760px)` keeps rows and controls within the viewport.

Run the existing asset sync through build rather than editing `frontend/react/src/styles.css` manually.

- [ ] **Step 9: Run management page checks and build**

```powershell
python tests/check_frontend_skills_page_react.py
python tests/check_frontend_page_navigation_react.py
Push-Location frontend
npm run build
Pop-Location
```

Expected: PASS.

- [ ] **Step 10: Commit**

```powershell
git add frontend/react/src/api/client.js frontend/react/src/App.jsx frontend/react/src/data/navigation.js frontend/react/src/components/Sidebar.jsx frontend/react/src/components/SkillsPage.jsx frontend/react/src/components/SkillInstallDialog.jsx frontend/react/src/components/SkillDetailDrawer.jsx frontend/styles.css frontend/react/src/styles.css tests/check_frontend_skills_page_react.py tests/check_frontend_page_navigation_react.py
git commit -m "feat: add skill management interface"
```

## Task 6: Add the Codex-style `/` Skill picker

**Files:**

- Create: `frontend/react/src/components/SkillPicker.jsx`
- Modify: `frontend/react/src/components/ChatComposerForm.jsx`
- Modify: `frontend/react/src/controller/bridgeBindings.js`
- Modify: `frontend/react/src/controller/chatFlow.js`
- Modify: `frontend/styles.css`
- Create: `tests/check_frontend_skill_picker_react.py`
- Modify: `tests/check_frontend_chat_flow_module.py`

- [ ] **Step 1: Write failing picker contracts**

Require:

```python
require("frontend/react/src/components/SkillPicker.jsx", 'role={"listbox"}', "accessible listbox")
require("frontend/react/src/components/SkillPicker.jsx", 'role={"option"}', "accessible options")
require("frontend/react/src/components/ChatComposerForm.jsx", r"/(^|\\s)\\/([^\\s/]*)$/", "word-boundary slash match")
for key in ("ArrowUp", "ArrowDown", "Enter", "Escape", "Backspace"):
    require("frontend/react/src/components/ChatComposerForm.jsx", key, f"{key} behavior")
require("frontend/react/src/controller/chatFlow.js", "payload.skillId = skillId", "stable Skill ID payload")
require("frontend/react/src/controller/chatFlow.js", "retryRequest?.payload?.skillId", "Skill retry snapshot")
require("frontend/styles.css", ".skill-picker", "picker layout")
require("frontend/styles.css", "@media (max-width: 760px)", "narrow-screen picker")
```

- [ ] **Step 2: Run and verify picker failure**

```powershell
python tests/check_frontend_skill_picker_react.py
python tests/check_frontend_chat_flow_module.py
```

Expected: FAIL.

- [ ] **Step 3: Implement `SkillPicker`**

Accept:

```javascript
export function SkillPicker({
  skills,
  activeIndex,
  onSelect,
  onManage,
}) {
  return (
    <div className={"skill-picker"} role={"listbox"} aria-label={"Skills"}>
      {skills.length ? skills.map((skill, index) => (
        <button
          type={"button"}
          role={"option"}
          aria-selected={index === activeIndex}
          className={index === activeIndex ? "active" : ""}
          id={`skill-option-${skill.id}`}
          key={skill.id}
          onMouseDown={(event) => {
            event.preventDefault();
            onSelect(skill);
          }}
        >
          <span className={"skill-picker-icon"} aria-hidden={"true"}>✦</span>
          <span className={"skill-picker-copy"}>
            <strong>{skill.name}</strong>
            <small>{skill.description}</small>
          </span>
          <span>{skill.sourceKind === "builtin" ? "内置" : "个人"}</span>
        </button>
      )) : (
        <button type={"button"} onMouseDown={onManage}>
          前往安装 Skill
        </button>
      )}
      <button type={"button"} className={"skill-picker-manage"} onMouseDown={onManage}>
        管理 Skills
      </button>
    </div>
  );
}
```

Use `role="listbox"`, stable `id` values, `aria-selected`, personal/built-in source text, one-line ellipsized descriptions, mouse-down selection that does not blur the textarea, and a footer that calls `onManage`.

- [ ] **Step 4: Add slash-query and selection state**

In `ChatComposerForm` add:

```javascript
const slashPattern = /(^|\s)\/([^\s/]*)$/;
const [availableSkills, setAvailableSkills] = useState([]);
const [selectedSkill, setSelectedSkill] = useState(null);
const [pickerOpen, setPickerOpen] = useState(false);
const [pickerQuery, setPickerQuery] = useState("");
const [activeIndex, setActiveIndex] = useState(0);
const [slashRange, setSlashRange] = useState(null);
```

Match only the text before `selectionStart`. Load Skills lazily on first open and refresh on `knowflow:react-skills-updated`. Filter only `enabled && available`. Selection removes the `/query` substring by range and renders a non-editable pill above the textarea. Backspace on empty text removes the pill. Composer reset clears the pill and picker.

- [ ] **Step 5: Give picker keys priority**

When open:

- ArrowUp/ArrowDown wrap through results.
- Enter selects and does not send.
- Escape closes and leaves the typed text.

When closed, preserve the current Enter-to-send and Shift+Enter newline behavior. Add `aria-controls`, `aria-expanded`, and `aria-activedescendant` to the textarea.

- [ ] **Step 6: Submit and retry by stable ID**

Dispatch both submit events as:

```javascript
{
  question: question.trim(),
  skillId: selectedSkill?.id ?? null,
}
```

Forward `skillId` through `bridgeBindings`. In `submitChat()`:

```javascript
const skillId =
  retryRequest?.payload?.skillId ??
  options.skillId ??
  null;
if (skillId) payload.skillId = skillId;
```

Keep the value inside `requestSnapshot.payload` so retries use the original Skill version reference without storing selection in the legacy controller state.

- [ ] **Step 7: Add picker/pill styles**

Position the picker above `.composer-shell`, cap its height, use the same subtle border/shadow as existing composer surfaces, keep the selected option visibly highlighted, and use `left: 0; right: 0` inside the composer at narrow widths.

- [ ] **Step 8: Run picker checks and build**

```powershell
python tests/check_frontend_skill_picker_react.py
python tests/check_frontend_chat_flow_module.py
Push-Location frontend
npm run build
Pop-Location
```

Expected: PASS.

- [ ] **Step 9: Commit**

```powershell
git add frontend/react/src/components/SkillPicker.jsx frontend/react/src/components/ChatComposerForm.jsx frontend/react/src/controller/bridgeBindings.js frontend/react/src/controller/chatFlow.js frontend/styles.css frontend/react/src/styles.css tests/check_frontend_skill_picker_react.py tests/check_frontend_chat_flow_module.py
git commit -m "feat: add slash skill picker"
```

## Task 7: Polish Skill trace details and history replay

**Files:**

- Modify: `frontend/react/src/components/AgentTraceView.jsx`
- Modify: `tests/check_frontend_agent_trace_react.py`

- [ ] **Step 1: Extend the failing trace contract**

Require explicit Skill status copy and safe details:

```python
require("frontend/react/src/components/AgentTraceView.jsx", 'step.kind === "skill"', "Skill title branch")
require("frontend/react/src/components/AgentTraceView.jsx", "displayName", "Skill display name")
require("frontend/react/src/components/AgentTraceView.jsx", "requiredTools", "Skill tool dependencies")
require("frontend/react/src/components/AgentTraceView.jsx", "requiredMcp", "Skill MCP dependencies")
forbid("frontend/react/src/components/AgentTraceView.jsx", "systemMessage", "private Skill instructions")
```

- [ ] **Step 2: Implement safe Skill trace presentation**

For `kind === "skill"`:

- running: `正在激活 <name>`
- success: `已激活 <name>`
- failed: `Skill 激活失败`

In the detail panel show version, personal/built-in source, required tool names, and required MCP names from `step.details`. Do not render body, raw manifest, filesystem path, or system message.

- [ ] **Step 3: Run trace and build checks**

```powershell
python tests/check_frontend_agent_trace_react.py
python tests/check_skill_trace.py
Push-Location frontend
npm run build
Pop-Location
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add frontend/react/src/components/AgentTraceView.jsx tests/check_frontend_agent_trace_react.py
git commit -m "feat: show skill activation in agent traces"
```

## Task 8: Document deployment limits and protect user Skill data

**Files:**

- Modify: `backend/.env.example`
- Modify: `README.md`
- Modify: `.gitignore`
- Modify: `tests/check_release_hygiene.py`
- Create: `tests/check_skill_docs.py`

- [ ] **Step 1: Write failing documentation and hygiene checks**

Assert all environment names are documented, user Skill directories are ignored, README states scripts are not executed, and release hygiene rejects tracked user packages:

```python
for name in (
    "KNOWFLOW_SKILL_DIR",
    "KNOWFLOW_SKILL_MAX_ARCHIVE_BYTES",
    "KNOWFLOW_SKILL_MAX_EXTRACTED_BYTES",
    "KNOWFLOW_SKILL_MAX_FILES",
    "KNOWFLOW_SKILL_MAX_FILE_BYTES",
    "KNOWFLOW_SKILL_MAX_DEPTH",
    "KNOWFLOW_SKILL_MAX_BODY_CHARS",
    "KNOWFLOW_SKILL_IMPORT_TTL",
    "KNOWFLOW_SKILL_GITHUB_TIMEOUT",
):
    assert name in env_example, name
assert "data/skills/" in gitignore
assert "data/skill-imports/" in gitignore
assert "不会执行" in readme and "scripts/" in readme
```

- [ ] **Step 2: Add safe example configuration**

Append:

```text
# Per-user Skill packages. Skill scripts are stored for inspection and never executed.
KNOWFLOW_SKILL_DIR=./data/skills
KNOWFLOW_SKILL_MAX_ARCHIVE_BYTES=5242880
KNOWFLOW_SKILL_MAX_EXTRACTED_BYTES=20971520
KNOWFLOW_SKILL_MAX_FILES=200
KNOWFLOW_SKILL_MAX_FILE_BYTES=2097152
KNOWFLOW_SKILL_MAX_DEPTH=8
KNOWFLOW_SKILL_MAX_BODY_CHARS=50000
KNOWFLOW_SKILL_IMPORT_TTL=900
KNOWFLOW_SKILL_GITHUB_TIMEOUT=15
```

- [ ] **Step 3: Update README and ignore rules**

Document:

- `SKILL.md` minimum front matter and optional `metadata.knowflow`;
- GitHub/ZIP import sources and size limits;
- per-user isolation and one Skill per Agent run;
- `/` selection and automatic activation;
- existing tool/MCP approval remains authoritative;
- `scripts/` storage-only rule;
- database plus `data/skills` backup/persistence and service-user write permissions.

Ignore:

```text
data/skills/
data/skill-imports/
```

Extend release hygiene forbidden-path checks with both directories.

- [ ] **Step 4: Run documentation and hygiene checks**

```powershell
python tests/check_skill_docs.py
python tests/check_release_hygiene.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/.env.example README.md .gitignore tests/check_skill_docs.py tests/check_release_hygiene.py
git commit -m "docs: document skill safety and deployment"
```

## Task 9: Full verification, security scan, and GitHub synchronization

**Files:**

- Verify all modified files
- No new implementation files unless a failing check identifies a scoped defect

- [ ] **Step 1: Install the pinned backend dependency**

```powershell
python -m pip install -r backend/requirements.txt
```

Expected: exit code 0 without exposing environment values.

- [ ] **Step 2: Perform a clean frontend install and build**

```powershell
Push-Location frontend
npm ci
npm run build
Pop-Location
```

Expected: Vite build succeeds. `frontend/dist` remains ignored.

- [ ] **Step 3: Run every executable check in sorted order**

```powershell
$failed = @()
Get-ChildItem tests -Filter "check_*.py" |
  Sort-Object Name |
  ForEach-Object {
    python $_.FullName
    if ($LASTEXITCODE -ne 0) {
      $failed += $_.Name
    }
  }
if ($failed.Count) {
  throw "FAILED: $($failed -join ', ')"
}
```

Expected: every existing and new check passes.

- [ ] **Step 4: Run diff and tracked-artifact checks**

```powershell
git diff --check
git status --short
git ls-files |
  Select-String -Pattern '(^|/)(backend/\.env|.*\.db|data/skills/|data/skill-imports/|frontend/dist/)' |
  ForEach-Object { throw "Forbidden tracked artifact: $($_.Line)" }
```

Expected: no whitespace errors and no forbidden artifact.

- [ ] **Step 5: Scan the staged diff for credentials**

Inspect names and values without printing any real environment file:

```powershell
git diff --name-only origin/main...HEAD
git diff origin/main...HEAD |
  Select-String -Pattern '(?i)(api[_-]?key|client[_-]?secret|access[_-]?token|bearer\s+[a-z0-9._-]{16,})'
```

Expected: only placeholders, test fixtures, field names, and documentation labels. Do not add `backend/.env`, databases, uploaded packages, build output, or real tokens.

- [ ] **Step 6: Review commits and working tree**

```powershell
git status -sb
git log --oneline origin/main..HEAD
```

Expected: intentional Skill commits only; worktree clean after any final scoped fix commit.

- [ ] **Step 7: Push main**

```powershell
git push origin main
```

Expected: `origin/main` advances to the verified local HEAD.

- [ ] **Step 8: Report server synchronization requirements**

Report the pushed commit, all validation results, and the server steps:

1. pull `origin/main`;
2. install the updated backend requirements;
3. preserve the production environment file and existing secret;
4. ensure the service user can write `data/skills` and `data/skill-imports`;
5. run all `tests/check_*.py` and the frontend build;
6. restart only after all checks pass;
7. verify login, Skill install, `/` selection, automatic activation, MCP dependency handling, and trace replay without echoing secrets.
