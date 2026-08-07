from pathlib import Path
import sys
from contextlib import nullcontext
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_application import (
    AgentApplicationService,
    AgentExecution,
)
from typer.testing import CliRunner
from knowflow import cli


class FakeRunStore:
    def __init__(self):
        self.snapshot = {
            "id": "run_cli",
            "sessionId": "session-cli",
            "assistantMessageId": 9,
            "status": "completed",
            "trace": [],
        }

    def get_snapshot(self, user_id, run_id):
        assert user_id == 7
        assert run_id == "run_cli"
        return dict(self.snapshot)


class FakeApprovalStore:
    def resolve(self, user_id, approval_id, decision):
        assert (user_id, approval_id) == (7, "approval_cli")
        assert decision == "allow_once"
        return {
            "approvalId": approval_id,
            "runId": "run_cli",
        }


def main() -> None:
    emitted = []

    def execute_agent(payload, user_id, *, event_emit):
        assert payload == {"question": "hello"}
        assert user_id == 7
        event_emit(
            "approval_required",
            {
                "approvalId": "approval_cli",
                "runId": "run_cli",
                "toolName": "shell",
            },
        )
        return {
            "paused": True,
            "runId": "run_cli",
            "sessionId": "session-cli",
            "answer": "",
            "trace": [],
        }

    def execute_persisted(user_id, run_id, action, cancel_event, publish):
        assert user_id == 7
        assert run_id == "run_cli"
        assert action in {"approval:approval_cli", "resume"}
        assert not cancel_event.is_set()
        publish({"type": "answer", "content": "done"})
        publish({"type": "done", "runId": run_id})

    service = AgentApplicationService(
        execute_agent=execute_agent,
        execute_persisted=execute_persisted,
        approval_store=FakeApprovalStore(),
        run_store=FakeRunStore(),
    )
    first = service.run(
        {"question": "hello"},
        7,
        event_sink=emitted.append,
    )
    assert first.paused
    assert first.approval_id == "approval_cli"
    assert emitted[-1]["type"] == "approval_required"

    named = service._named_event(
        "agent_step",
        {"type": "step_finished", "step": {"status": "success"}},
    )
    assert named["type"] == "agent_step"
    assert named["eventType"] == "step_finished"

    second = service.resolve_approval(
        user_id=7,
        run_id="run_cli",
        approval_id="approval_cli",
        decision="allow_once",
        event_sink=emitted.append,
    )
    assert not second.paused
    assert second.result["answer"] == "done"
    assert second.result["messageId"] == 9

    resumed = service.resume(user_id=7, run_id="run_cli")
    assert resumed.result["answer"] == "done"

    completed = AgentExecution(
        result={
            "paused": False,
            "runId": "run_command",
            "sessionId": "session-command",
            "messageId": 10,
            "answer": "command done",
            "trace": [],
        }
    )

    class FakeLocalAgent:
        def run(self, task, *, tools, event_sink):
            assert task == "hello"
            assert tools
            event_sink(
                {
                    "type": "done",
                    "runId": "run_command",
                }
            )
            return completed

    with (
        patch.object(cli, "_local_agent", return_value=FakeLocalAgent()),
        patch.object(cli, "_remote_client", return_value=None),
    ):
        response = CliRunner().invoke(
            cli.app,
            ["run", "hello", "--events"],
        )
    assert response.exit_code == 0, response.output
    assert '"type": "done"' in response.output
    assert '"runId": "run_command"' in response.output

    cli_source = (ROOT / "backend" / "knowflow" / "cli.py").read_text(
        encoding="utf-8"
    )
    requirements = (ROOT / "backend" / "requirements.txt").read_text(
        encoding="utf-8"
    )
    pyproject = (ROOT / "backend" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "Typer" in cli_source
    assert "PromptSession" in cli_source
    assert "--events" in cli_source
    assert "def resume(" in cli_source
    assert "def list_models(" in cli_source
    assert "KNOWFLOW_CLI_USER_ID" in cli_source
    assert 'knowflow = "knowflow.cli:main"' in pyproject
    extension_source = (
        ROOT / "backend" / "knowflow" / "routers" / "extensions.py"
    ).read_text(encoding="utf-8")
    assert '"/api/agent/tools"' in extension_source
    for dependency in (
        "typer==",
        "rich==",
        "prompt-toolkit==",
        "textual==",
    ):
        assert dependency in requirements

    print("agent cli checks passed")


if __name__ == "__main__":
    main()
