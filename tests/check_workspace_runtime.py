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
        uploaded = workspace.write_bytes(
            "artifacts/result.bin",
            b"\x00\x01result",
            overwrite=False,
        )
        assert uploaded["writtenBytes"] == 8
        assert workspace.file_path("artifacts/result.bin").read_bytes() == b"\x00\x01result"
        workspace.delete_file("artifacts/result.bin")
        assert not (workspace.root / "artifacts" / "result.bin").exists()

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
            assert "/proc" in settings["filesystem"]["denyRead"]
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        runner = SrtSandboxRunner(
            workspace,
            command=sys.executable,
            shell="bash",
            platform="linux",
            run_factory=fake_run,
        )
        result = runner.run("ls -la", timeout_seconds=10)
        assert result.exit_code == 0 and result.stdout == "ok"
        assert captured["kwargs"]["cwd"] == workspace.root
        assert "KNOWFLOW_SECRET_KEY" not in captured["kwargs"]["env"]
        assert captured["kwargs"]["env"]["HOME"] == str(workspace.root)
        assert captured["kwargs"]["env"]["TMPDIR"].startswith(str(workspace.root))
        assert "prlimit" in captured["argv"]
        assert captured["argv"][-4:] == [
            "--noprofile",
            "--norc",
            "-c",
            "ls -la",
        ]

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
        assert registry.definition("write_workspace_file").risk == "write"
        assert registry.definition("run_sandbox_command").risk == "execute"
        assert registry.definition("write_workspace_file").destructive is False
        assert registry.definition("run_sandbox_command").destructive is True

        timeout_runner = SrtSandboxRunner(
            workspace,
            command=sys.executable,
            platform="linux",
            run_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("srt", 1, output="partial")
            ),
        )
        timeout = timeout_runner.run("slow", timeout_seconds=1)
        assert timeout.timed_out is True and timeout.exit_code == 124

        unsupported = SrtSandboxRunner(
            workspace,
            command=sys.executable,
            platform="win32",
        )
        assert unsupported.available() is False

    print("workspace tools enforce user isolation and sandbox-only shell execution")


if __name__ == "__main__":
    main()
