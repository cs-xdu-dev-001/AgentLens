from pathlib import Path
from io import StringIO
import json
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_loop import ToolRegistry
from knowflow.services.workspace_runtime import (
    SrtSandboxRunner,
    WorkspaceContext,
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


def run_git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip()


def main() -> None:
    assert WorkspaceContext._safe_git_label("main\u202eevil\x1b") == "mainevil"
    assert len(WorkspaceContext._safe_git_label("x" * 500)) == 160

    with tempfile.TemporaryDirectory() as temp_dir:
        repository = Path(temp_dir) / "repo"
        repository.mkdir()
        run_git(repository, "init", "--initial-branch=main")
        (repository / "staged.txt").write_text("base\n", encoding="utf-8")
        (repository / "modified.txt").write_text("base\n", encoding="utf-8")
        run_git(repository, "add", "staged.txt", "modified.txt")
        run_git(
            repository,
            "-c",
            "user.name=AgentLens Tests",
            "-c",
            "user.email=agentlens@example.invalid",
            "commit",
            "-m",
            "baseline",
        )
        run_git(repository, "remote", "add", "origin", ".")
        run_git(repository, "fetch", "origin", "main")
        run_git(repository, "branch", "--set-upstream-to=origin/main", "main")
        (repository / "ahead.txt").write_text("ahead\n", encoding="utf-8")
        run_git(repository, "add", "ahead.txt")
        run_git(
            repository,
            "-c",
            "user.name=AgentLens Tests",
            "-c",
            "user.email=agentlens@example.invalid",
            "commit",
            "-m",
            "ahead",
        )
        (repository / "staged.txt").write_text("staged\n", encoding="utf-8")
        run_git(repository, "add", "staged.txt")
        (repository / "modified.txt").write_text("modified\n", encoding="utf-8")
        (repository / "untracked.txt").write_text("new\n", encoding="utf-8")

        status = WorkspaceContext(repository).status()
        assert status["branch"] == "main"
        assert status["dirty"] is True
        assert status["changedFiles"] == 3
        assert status["git"] == {
            "repository": True,
            "rootName": "repo",
            "branch": "main",
            "detached": False,
            "head": run_git(repository, "rev-parse", "--short=8", "HEAD"),
            "upstream": "origin/main",
            "ahead": 1,
            "behind": 0,
            "changedFiles": 3,
            "stagedFiles": 1,
            "modifiedFiles": 1,
            "untrackedFiles": 1,
            "conflictedFiles": 0,
            "clean": False,
        }

        nested = repository / "nested"
        nested.mkdir()
        nested_status = WorkspaceContext(nested).status()
        assert nested_status["git"]["repository"] is False
        assert nested_status["branch"] is None

        run_git(repository, "checkout", "--detach")
        detached = WorkspaceContext(repository).status()["git"]
        assert detached["detached"] is True
        assert detached["branch"].startswith("detached@")

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
        (workspace.root / "src" / "nested").mkdir()
        (workspace.root / "src" / "nested" / "feature.py").write_text(
            "pass\n",
            encoding="utf-8",
        )
        (workspace.root / "node_modules").mkdir()
        (workspace.root / "node_modules" / "ignored.js").write_text(
            "ignored\n",
            encoding="utf-8",
        )
        (workspace.root / ".env.local").write_text("secret", encoding="utf-8")
        mentions = workspace.mention_paths()
        assert mentions["source"] in {"git", "filesystem"}
        assert mentions["truncated"] is False
        assert "src/" in mentions["paths"]
        assert "src/nested/" in mentions["paths"]
        assert "src/main.py" in mentions["paths"]
        assert "src/nested/feature.py" in mentions["paths"]
        assert not any("node_modules" in path for path in mentions["paths"])
        assert not any(".env" in path for path in mentions["paths"])
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

        class FakeProcess:
            def __init__(self, stdout: str, stderr: str, returncode: int = 0):
                self.stdout = StringIO(stdout)
                self.stderr = StringIO(stderr)
                self.returncode = returncode

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                return self.returncode

            def terminate(self):
                self.returncode = -15

            def kill(self):
                self.returncode = -9

        def fake_process(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            settings_path = Path(argv[2])
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            assert settings["network"]["allowedDomains"] == []
            assert str(workspace.root) in settings["filesystem"]["allowWrite"]
            assert "/proc" in settings["filesystem"]["denyRead"]
            return FakeProcess("ok", "")

        runner = SrtSandboxRunner(
            workspace,
            command=sys.executable,
            shell="bash",
            platform="linux",
            process_factory=fake_process,
        )
        progress = []
        result = runner.run(
            "ls -la",
            timeout_seconds=10,
            progress_callback=progress.append,
        )
        assert result.exit_code == 0 and result.stdout == "ok"
        assert result.total_bytes == 2
        assert progress[-1]["output"] == "ok"
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
            "edit_workspace_file",
            "run_sandbox_command",
        )
        assert registry.definition("read_workspace_file").read_only is True
        assert registry.definition("write_workspace_file").requires_approval is True
        assert registry.definition("run_sandbox_command").requires_approval is True
        assert registry.definition("write_workspace_file").risk == "write"
        assert registry.definition("run_sandbox_command").risk == "execute"
        assert registry.definition("write_workspace_file").destructive is False
        assert registry.definition("edit_workspace_file").requires_approval is True
        assert registry.definition("run_sandbox_command").destructive is True
        assert registry.definition("run_sandbox_command").interrupt_behavior == "cancel"

        class SlowProcess(FakeProcess):
            def __init__(self):
                super().__init__("partial", "", 0)
                self.returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                if self.returncode is None:
                    raise subprocess.TimeoutExpired("srt", timeout or 0)
                return self.returncode

        timeout_runner = SrtSandboxRunner(
            workspace,
            command=sys.executable,
            platform="linux",
            process_factory=lambda *_args, **_kwargs: SlowProcess(),
        )
        timeout = timeout_runner.run("slow", timeout_seconds=1)
        assert timeout.timed_out is True and timeout.exit_code == 124

        cancelled_runner = SrtSandboxRunner(
            workspace,
            command=sys.executable,
            platform="linux",
            process_factory=lambda *_args, **_kwargs: SlowProcess(),
        )
        cancelled = cancelled_runner.run(
            "slow",
            timeout_seconds=10,
            cancel_check=lambda: True,
        )
        assert cancelled.cancelled is True and cancelled.exit_code == 130

        unsupported = SrtSandboxRunner(
            workspace,
            command=sys.executable,
            platform="win32",
        )
        assert unsupported.available() is False
        assert unsupported.diagnostics(smoke=False)[0]["ready"] is False

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        project = root / "project"
        extra = root / "notes"
        project.mkdir()
        extra.mkdir()
        context = WorkspaceContext(project, state_root=root / "state")
        workspace = WorkspaceRuntime(
            project,
            user_id=1,
            isolated_namespace=False,
            manage_root_permissions=False,
            context=context,
        )
        context.begin_turn("run_workspace")
        workspace.write_text("report.md", "old\n", overwrite=False)
        edited = workspace.edit_text(
            "report.md",
            "old",
            "new",
            replace_all=False,
        )
        assert edited.output["addedLines"] == 1
        diff = context.diff()
        assert diff["files"] == [
            {
                "path": "report.md",
                "added": 1,
                "removed": 0,
                "operation": "edit",
                "operationId": edited.output["operationId"],
                "diffAvailable": True,
                "reverted": False,
            }
        ]
        assert "+new" in diff["patch"]
        outside = root / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        tampered_change = {
            "id": "tampered_change",
            "runId": "run_workspace",
            "path": str(outside),
            "displayPath": "outside.txt",
            "operation": "write",
            "beforeHash": None,
            "afterHash": context._digest(outside.read_bytes()),
            "beforeSnapshot": None,
            "created": True,
            "undone": False,
        }
        context._append_record(tampered_change)
        expect_error(
            "workspace_diff_denied",
            lambda: context.diff(run_id="run_workspace"),
        )
        context._append_record({**tampered_change, "undone": True})
        snapshot_target = project / "snapshot-target.txt"
        snapshot_target.write_text("current\n", encoding="utf-8")
        tampered_snapshot = {
            "id": "tampered_snapshot",
            "runId": "run_workspace",
            "path": str(snapshot_target),
            "displayPath": "snapshot-target.txt",
            "operation": "edit",
            "beforeHash": context._digest(b"outside\n"),
            "afterHash": context._digest(snapshot_target.read_bytes()),
            "beforeSnapshot": "../../outside.txt",
            "created": False,
            "undone": False,
        }
        context._append_record(tampered_snapshot)
        expect_error(
            "workspace_snapshot_denied",
            lambda: context.diff(run_id="run_workspace"),
        )
        context._append_record({**tampered_snapshot, "undone": True})
        assert context.undo_last()["path"] == "report.md"
        assert (project / "report.md").read_text(encoding="utf-8") == "old\n"
        latest_change = context.changes("run_workspace")[-1]
        (project / "report.md").write_text("user change\n", encoding="utf-8")
        expect_error("workspace_undo_conflict", context.undo_last)
        expect_error(
            "workspace_undo_conflict",
            lambda: context.undo(
                operation_id=latest_change["id"],
                run_id="run_workspace",
            ),
        )
        (project / "multi.md").write_text("old\n", encoding="utf-8")
        workspace.edit_text("multi.md", "old", "middle", replace_all=False)
        workspace.edit_text("multi.md", "middle", "final", replace_all=False)
        report_change = context.changes("run_workspace")[-1]
        reverted = context.undo_file(
            operation_id=report_change["id"],
            run_id="run_workspace",
        )
        assert len(reverted["operationIds"]) == 2
        assert (project / "multi.md").read_text(encoding="utf-8") == "old\n"
        added = context.add_directory(str(extra))
        assert str(extra) in added["allowedDirectories"]
        protected = extra / ".git"
        protected.mkdir()
        (protected / "config").write_text("secret", encoding="utf-8")
        protected_link = project / "linked-git-config"
        try:
            protected_link.symlink_to(protected / "config")
        except OSError:
            pass
        else:
            expect_error(
                "workspace_path_denied",
                lambda: workspace.read_text("linked-git-config"),
            )
        context.change_directory(str(extra))
        workspace.write_text("note.md", "ok\n", overwrite=False)
        assert (extra / "note.md").is_file()
        note_change = context.changes("run_workspace")[-1]
        undone = context.undo(
            operation_id=note_change["id"],
            run_id="run_workspace",
        )
        assert undone["reverted"] is True
        assert not (extra / "note.md").exists()
        oversized = extra / "oversized.txt"
        oversized.write_bytes(b"x" * (workspace.max_file_bytes + 1))
        expect_error(
            "workspace_file_too_large",
            lambda: workspace.write_text("oversized.txt", "small", overwrite=True),
        )
        status = context.status()
        assert status["projectRoot"] == str(project)
        assert status["cwd"] == str(extra)
        assert status["workspaceKind"] == "directory"
        assert status["warnings"]
        (project / "README.md").write_text("project\n", encoding="utf-8")
        status = context.status()
        assert status["workspaceKind"] == "project"
        assert status["warnings"] == []

    print("workspace tools enforce user isolation and sandbox-only shell execution")


if __name__ == "__main__":
    main()
