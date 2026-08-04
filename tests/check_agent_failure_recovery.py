from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_failure import (  # noqa: E402
    classify_agent_failure,
    recovery_from_snapshot,
)
from knowflow.database import Database  # noqa: E402
from knowflow.services.agent_run_store import AgentRunStore  # noqa: E402


def main() -> None:
    timeout = classify_agent_failure(code="web_search_timeout")
    assert timeout == {
        "code": "web_search_timeout",
        "summary": "The web search request timed out.",
        "retryable": True,
        "target": None,
    }

    mcp_auth = classify_agent_failure(code="resource_unauthorized")
    assert mcp_auth["code"] == "mcp_authentication_required"
    assert mcp_auth["retryable"] is False
    assert mcp_auth["target"] == "tools"

    model_auth = classify_agent_failure(code="invalid_api_key")
    assert model_auth["code"] == "model_authentication_failed"
    assert model_auth["target"] == "settings"

    rate_limit = classify_agent_failure(code="rate_limit_exceeded")
    assert rate_limit["code"] == "rate_limited"
    assert rate_limit["retryable"] is True

    unknown = classify_agent_failure(code="private_vendor_problem")
    assert unknown == {
        "code": "private_vendor_problem",
        "summary": "The Agent run failed.",
        "retryable": True,
        "target": None,
    }

    assert recovery_from_snapshot("completed", [], []) is None
    interrupted = recovery_from_snapshot("interrupted", [], [])
    assert interrupted is not None
    assert interrupted["code"] == "service_restart_interrupted"
    assert interrupted["retryable"] is True

    db_path = ROOT / "data" / "test-dbs" / "agent-failure-recovery.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    store = AgentRunStore(
        database=Database(f"sqlite:///{db_path.as_posix()}")
    )
    run = store.create_run(
        user_id=1,
        session_id="session-recovery",
        user_message_id=1,
        goal_summary="恢复测试",
        trigger_mode="auto",
        request_payload={
            "question": "恢复测试",
            "sessionId": "session-recovery",
        },
        run_id="run_failure_recovery",
    )
    step = store.replace_plan(
        1,
        run["id"],
        [
            {"title": "请求模型", "kind": "reasoning"},
            {"title": "整理回答", "kind": "answer"},
        ],
    )[0]
    store.transition_run(1, run["id"], "running")
    store.transition_step(1, run["id"], step["id"], "running")
    store.transition_step(
        1,
        run["id"],
        step["id"],
        "failed",
        output_summary="The upstream service timed out.",
        error_code="upstream_timeout",
    )
    store.transition_run(1, run["id"], "failed")
    snapshot = store.get_snapshot(1, run["id"])
    assert snapshot is not None
    assert snapshot["failure"] == {
        "code": "upstream_timeout",
        "summary": "The upstream service timed out.",
        "retryable": True,
        "target": None,
    }

    restarted = store.restart_run(
        1,
        run["id"],
        run_id="run_failure_restarted",
    )
    assert restarted["id"] == "run_failure_restarted"
    assert restarted["status"] == "planning"
    assert restarted["sessionId"] == snapshot["sessionId"]
    assert restarted["userMessageId"] == snapshot["userMessageId"]
    assert restarted["goalSummary"] == snapshot["goalSummary"]
    assert store.load_request(1, restarted["id"]) == {
        **store.load_request(1, run["id"]),
        "_agentEngine": "langgraph",
    }

    extensions = (
        ROOT / "backend" / "knowflow" / "routers" / "extensions.py"
    ).read_text(encoding="utf-8")
    assert 'error_code="agent_step_failed"' not in extensions
    assert "classify_agent_failure" in extensions

    print("agent failure classification and recovery policy work")


if __name__ == "__main__":
    main()
