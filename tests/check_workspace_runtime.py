from pathlib import Path
import json
import subprocess
import sys
import tempfile
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.workspace_runtime import (
    SrtSandboxRunner,
    WorkspaceRuntime,
    WorkspaceRuntimeError,
    register_workspace_tools,
)


def expect_error(code: str, callback) -> None:
    try:
        callback()
        raise AssertionError(f"expected {code}")
    except WorkspaceRuntimeError as exc:
        assert exc.code == code


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir) / "workspaces"
        workspace = WorkspaceRuntime(base, user_id=7, max_file_bytes=10_000)
        other = WorkspaceRuntime(base, user_id=8, max_file_bytes=10_000)
        assert workspace.root != other.root

        write = workspace.write_text(
            "src/main.py",
            "print('hello')\n",
            overwrite=False,
        )
        assert write.output["writtenBytes"] > 0
        assert workspace.read_text("src/main.py")["content"] == "print('hello')\n"
        assert other.list_entries()["entries"] == []
        assert workspace.list_entries("src")["entries"] == [
            {"path": "src/main.py", "kind": "file"}
        ]

        expect_error(
            "workspace_path_invalid",
            lambda: workspace.read_text("../secret.txt"),
        )
        expect_error(
            "workspace_path_invalid",
            lambda: workspace.read_text("C:/secret.txt"),
        )
        expect_error(
            "workspace_path_invalid",
            lambda: workspace.read_text("src\\main.py"),
        )
        expect_error(
            "workspace_path_invalid",
            lambda: workspace.write_text("CON.txt", "x", overwrite=False),
        )
        expect_error(
            "workspace_path_denied",
            lambda: workspace.write_text(".env", "secret", overwrite=False),
        )
        expect_error(
            "workspace_file_exists",
            lambda: workspace.write_text("src/main.py", "x", overwrite=False),
        )
        sensitive = workspace.root / ".env"
        sensitive.write_text("secret", encoding="utf-8")
        link = workspace.root / "linked-secret"
        try:
            link.symlink_to(sensitive)
        except OSError:
            pass
        else:
            expect_error(
                "workspace_path_denied",
                lambda: workspace.read_text("linked-secret"),
            )

        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            settings_path = Path(argv[2])
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            assert settings["network"]["allowedDomains"] == []
            assert str(workspace.root) in settings["filesystem"]["allowWrite"]
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        runner = SrtSandboxRunner(
            workspace,
            command=sys.executable,
            run_factory=fake_run,
        )
        result = runner.run("Get-ChildItem", timeout_seconds=10)
        assert result.exit_code == 0 and result.stdout == "ok"
        assert captured["kwargs"]["cwd"] == workspace.root
        assert "KNOWFLOW_SECRET_KEY" not in captured["kwargs"]["env"]

        registry = ToolRegistry()
        names = register_workspace_tools(registry, workspace, sandbox=runner)
        assert names == (
            "list_workspace",
            "read_workspace_file",
            "write_workspace_file",
            "run_sandbox_command",
        )
        assert registry.definition("read_workspace_file").read_only is True
        assert registry.definition("write_workspace_file").requires_approval is True
        assert registry.definition("run_sandbox_command").requires_approval is True

        timeout_runner = SrtSandboxRunner(
            workspace,
            command=sys.executable,
            run_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("srt", 1, output="partial")
            ),
        )
        timeout = timeout_runner.run("slow", timeout_seconds=1)
        assert timeout.timed_out is True and timeout.exit_code == 124

    print("workspace tools enforce user isolation and sandbox-only shell execution")


if __name__ == "__main__":
    main()
