import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".html", ".css", ".md", ".txt", ".json", ".yml", ".yaml", ".toml", ".cmd", ".sql"}
IGNORED_PARTS = {".git", "node_modules", "dist", "__pycache__"}
FORBIDDEN_TEXT = ["?" * 4, "\ufeff"]
FORBIDDEN_TRACKED_PATTERNS = [
    "backend/.env",
    "frontend/.env",
    "data/knowflow.db",
    "data/skills/",
    "data/skill-imports/",
    "backend/data/skills/",
    "backend/data/skill-imports/",
    "data/test-dbs/",
    "data/test-uploads/",
    "frontend/react/public/vendor/",
    "frontend/node_modules/",
    "frontend/dist/",
]
TESTCLIENT_COOKIE_EXEMPT = {"tests/check_backend_static_frontend.py"}


def normalize_repo_path(path: str) -> str:
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized.casefold()


def is_forbidden_tracked_path(path: str) -> bool:
    normalized = normalize_repo_path(path)
    for pattern in FORBIDDEN_TRACKED_PATTERNS:
        if not pattern.endswith("/"):
            continue
        expected = normalize_repo_path(pattern)
        expected = expected.rstrip("/")
        if normalized == expected or normalized.startswith(expected + "/"):
            return True
    if normalized.endswith(".env.example"):
        return False
    return any(
        normalized.startswith(normalize_repo_path(pattern))
        for pattern in FORBIDDEN_TRACKED_PATTERNS
        if not pattern.endswith("/")
    )


def check_forbidden_path_contract() -> None:
    forbidden = [
        "backend/.env.local",
        "data/knowflow.db-wal",
        "data/skills/user-1/example/SKILL.md",
        "data/skills/user-1/example/.env.example",
        r"data\skill-imports\preview-1\archive.zip",
        "backend/data/skills/user-2/example/SKILL.md",
        r"backend\data\skill-imports\preview-2\SKILL.md",
    ]
    allowed = [
        "backend/.env.example",
        "frontend/.env.example",
        "data/skills-notes/readme.md",
        "data/skill-imports.md",
        "backend/knowflow/builtin_skills/deep-research/SKILL.md",
        "docs/data/skills/example.md",
    ]
    assert all(is_forbidden_tracked_path(path) for path in forbidden)
    assert not any(is_forbidden_tracked_path(path) for path in allowed)


def iter_text_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if any(part in IGNORED_PARTS for part in relative.split("/")):
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in {".gitignore", ".gitattributes"}:
            yield path


def tracked_files() -> list[str]:
    git_dir = ROOT / ".git"
    if not git_dir.exists():
        return []
    import subprocess

    result = subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "-C", str(ROOT), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def authenticated_testclient_files() -> list[Path]:
    result = []
    for path in (ROOT / "tests").glob("check_*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        relative = path.relative_to(ROOT).as_posix()
        imports_testclient = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "fastapi.testclient"
            and any(alias.name == "TestClient" for alias in node.names)
            for node in ast.walk(tree)
        )
        instantiates_testclient = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "TestClient"
            for node in ast.walk(tree)
        )
        if (
            imports_testclient
            and instantiates_testclient
            and relative not in TESTCLIENT_COOKIE_EXEMPT
        ):
            result.append(path)
    return result


def isolates_secure_cookie_before_app_import(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    cookie_lines = []
    app_import_lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Attribute)
                    and isinstance(target.value.value, ast.Name)
                    and target.value.value.id == "os"
                    and target.value.attr == "environ"
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "KNOWFLOW_COOKIE_SECURE"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value == "0"
                ):
                    cookie_lines.append(node.lineno)
        elif isinstance(node, ast.Import):
            if any(
                alias.name == "main" or alias.name.startswith("knowflow")
                for alias in node.names
            ):
                app_import_lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            if node.module and (
                node.module == "main" or node.module.startswith("knowflow")
            ):
                app_import_lines.append(node.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "importlib"
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and (
                node.args[0].value == "main"
                or node.args[0].value.startswith("knowflow")
            )
        ):
            app_import_lines.append(node.lineno)
    return bool(
        cookie_lines
        and app_import_lines
        and min(cookie_lines) < min(app_import_lines)
    )


def main() -> None:
    check_forbidden_path_contract()
    text_offenders = []
    for path in iter_text_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in FORBIDDEN_TEXT:
            if token in text:
                text_offenders.append(f"{path.relative_to(ROOT).as_posix()}: contains {token!r}")
    if text_offenders:
        raise AssertionError("release hygiene text issues:\n" + "\n".join(text_offenders[:80]))

    tracked = tracked_files()
    tracked_offenders = [path for path in tracked if is_forbidden_tracked_path(path)]
    if tracked_offenders:
        raise AssertionError("sensitive or generated files are tracked:\n" + "\n".join(sorted(set(tracked_offenders))))

    cookie_env_offenders = [
        path.relative_to(ROOT).as_posix()
        for path in authenticated_testclient_files()
        if not isolates_secure_cookie_before_app_import(path)
    ]
    if cookie_env_offenders:
        raise AssertionError(
            "authenticated TestClient checks must isolate secure-cookie config:\n"
            + "\n".join(cookie_env_offenders)
        )

    print("release hygiene checks passed")


if __name__ == "__main__":
    main()
