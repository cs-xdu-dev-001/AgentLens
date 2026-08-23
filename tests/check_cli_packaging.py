from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


configuration = tomllib.loads(
    (BACKEND / "pyproject.toml").read_text(encoding="utf-8")
)
project = configuration["project"]
assert project["name"] == "knowflow-ai"
assert project["requires-python"] == ">=3.10"
assert project["scripts"]["knowflow"] == "knowflow.cli:main"
assert "--version" in (BACKEND / "knowflow/cli.py").read_text(encoding="utf-8")
assert project["version"] == "0.29.0"
assert 'version="0.29.0"' in (ROOT / "backend" / "knowflow" / "app.py").read_text(encoding="utf-8")
package_data = configuration["tool"]["setuptools"]["package-data"]["knowflow"]
assert "ink_tui/*.mjs" in package_data
assert "ink_tui/*.txt" in package_data

dependencies = set(project["dependencies"])
for required in {
    "beautifulsoup4==4.12.3",
    "httpx==0.28.1",
    "jsonschema==4.23.0",
    "langgraph==1.2.10",
    "langgraph-checkpoint-sqlite==3.1.0",
    "prompt-toolkit==3.0.53",
    "pydantic==2.13.4",
    "requests==2.32.3",
    "rich==15.0.0",
    "textual==8.2.8",
    "tomli==2.2.1; python_version < '3.11'",
    "typer==0.27.1",
}:
    assert required in dependencies

requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
assert 'tomli==2.2.1; python_version < "3.11"' in requirements

local_dependencies = set(project["optional-dependencies"]["local"])
for required in {
    "fastapi==0.115.6",
    "langgraph==1.2.10",
    "mem0ai==2.0.14",
}:
    assert required in local_dependencies

agent_dependencies = set(project["optional-dependencies"]["agent"])
assert agent_dependencies == {"mcp==1.28.1", "mem0ai==2.0.14"}

probe = subprocess.run(
    [
        sys.executable,
        "-c",
        (
            "import sys; import knowflow.cli; "
            "heavy={'fastapi','mem0','chromadb'}; "
            "found=heavy.intersection(sys.modules); "
            "assert not found, sorted(found)"
        ),
    ],
    cwd=BACKEND,
    check=False,
    capture_output=True,
    text=True,
)
assert probe.returncode == 0, probe.stderr or probe.stdout

installer = (ROOT / "install.sh").read_text(encoding="utf-8")
assert 'run_pipx install --force "$PACKAGE_SPEC"' in installer
assert "knowflow-ai[agent] @ git+" in installer
assert "KNOWFLOW_CLI_SPEC" in installer
assert '"pipx==1.16.1"' in installer
assert "sudo" not in installer
assert "Node.js 22+" in installer

cli_source = (BACKEND / "knowflow/cli.py").read_text(encoding="utf-8")
assert 'def update() -> None:' in cli_source
assert '[*pipx, "install", "--force", package_spec]' in cli_source
assert "knowflow-ai[agent] @ git+" in cli_source
assert 'os.getenv("KNOWFLOW_CLI_SPEC", "").strip()' in cli_source

workflow = (ROOT / ".github/workflows/release-cli.yml").read_text(
    encoding="utf-8"
)
assert "pypa/gh-action-pypi-publish@106e0b0" in workflow
assert "actions/checkout@v4" not in workflow
assert "actions/setup-python@v5" not in workflow
assert "build==1.4.0" in workflow
assert "twine==6.2.0" in workflow
assert "id-token: write" in workflow
assert "gh release create" in workflow
assert "Build and test Ink CLI" in workflow

ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
assert "package_version=" in ci_workflow
assert '"${package_version}"' in ci_workflow
assert 'knowflow" --version)" = "0.5.0"' not in ci_workflow

print("cli packaging checks passed")
