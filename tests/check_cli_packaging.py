from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]
assert project["name"] == "knowflow-ai"
assert project["requires-python"] == ">=3.10"
assert project["scripts"]["knowflow"] == "knowflow.cli:main"
assert "--version" in (BACKEND / "knowflow/cli.py").read_text(encoding="utf-8")

dependencies = set(project["dependencies"])
for required in {
    "jsonschema==4.23.0",
    "langgraph==1.2.10",
    "langgraph-checkpoint-sqlite==3.1.0",
    "prompt-toolkit==3.0.53",
    "pydantic==2.13.4",
    "requests==2.32.3",
    "rich==15.0.0",
    "textual==8.2.8",
    "typer==0.27.1",
}:
    assert required in dependencies

local_dependencies = set(project["optional-dependencies"]["local"])
for required in {
    "fastapi==0.115.6",
    "langgraph==1.2.10",
    "mem0ai==2.0.14",
}:
    assert required in local_dependencies

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
assert "KNOWFLOW_CLI_SPEC" in installer
assert '"pipx==1.16.1"' in installer
assert "sudo" not in installer

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

print("cli packaging checks passed")
