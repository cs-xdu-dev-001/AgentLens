from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from typer.testing import CliRunner


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import knowflow.cli as cli  # noqa: E402


runner = CliRunner()
calls: list[list[str]] = []


def fake_run(command, **kwargs):
    calls.append(list(command))
    assert kwargs == {
        "check": False,
        "capture_output": True,
        "text": True,
    }
    return subprocess.CompletedProcess(command, 0, "", "")


original_pipx = cli._pipx_command
original_run = cli.subprocess.run
original_version = cli._installed_cli_version
try:
    cli._pipx_command = lambda: ["/opt/pipx/bin/pipx"]
    cli.subprocess.run = fake_run
    cli._installed_cli_version = lambda: "0.6.0"
    result = runner.invoke(cli.app, ["update"])
finally:
    cli._pipx_command = original_pipx
    cli.subprocess.run = original_run
    cli._installed_cli_version = original_version

assert result.exit_code == 0, result.output
assert "当前版本" in result.output
assert "更新完成" in result.output
assert calls == [
    [
        "/opt/pipx/bin/pipx",
        "install",
        "--force",
        cli.DEFAULT_CLI_PACKAGE_SPEC,
    ]
]

help_result = runner.invoke(cli.app, ["--help"])
assert help_result.exit_code == 0, help_result.output
assert "update" in help_result.output
assert "更新KnowFlow CLI到最新版" in help_result.output

print("cli update checks passed")
