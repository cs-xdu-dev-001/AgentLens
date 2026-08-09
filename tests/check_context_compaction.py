from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.context_compaction import (  # noqa: E402
    ContextCompactionError,
    SUMMARY_MARKER,
    compact_context,
    context_status,
)
from knowflow.tui.backend import TuiBackend  # noqa: E402


class FakeGateway:
    def __init__(self) -> None:
        self.requests: list[list[dict]] = []

    def complete(self, messages, _config):
        self.requests.append(messages)
        return {
            "role": "assistant",
            "content": (
                "## 用户目标与验收标准\n完成CLI上下文压缩。\n"
                "## 工作区边界\n只修改测试工作区。\n"
                "## 已修改文件及关键实现决策\n保留完整记录。\n"
                "## 未完成步骤\n运行测试。\n"
                "## 失败与证据\n无。\n"
                "## 权限决定\n写操作仍确认。\n"
                "## Skills与工具\n保留已激活Skill。"
            ),
        }


class ExplodingGateway:
    def complete(self, _messages, _config):
        raise RuntimeError("https://secret.example/v1?token=do-not-show")


class FailingLocalAgent:
    def context_status(self, _messages):
        return {
            "shouldAutoCompact": True,
            "usedTokens": 80,
            "maxTokens": 100,
        }

    def compact_context(self, _messages, **_kwargs):
        raise RuntimeError("summary upstream unavailable")


class SavingLocalAgent:
    def __init__(self) -> None:
        self.saved = None

    def compact_context(self, _messages, **_kwargs):
        return {
            "messages": [
                {"role": "system", "content": "policy"},
                {"role": "system", "content": f"{SUMMARY_MARKER}\nsummary"},
                {"role": "user", "content": "latest"},
            ],
            "metadata": {"reason": "manual", "originalTokens": 100, "compactedTokens": 20},
            "status": {"usedTokens": 20, "maxTokens": 100, "usagePercent": 20},
            "compacted": True,
            "reason": "compacted",
        }

    def save_context_state(self, run_id, *, messages, metadata):
        self.saved = (run_id, messages, metadata)


def main() -> None:
    messages = [{"role": "system", "content": "workspace policy"}]
    for index in range(18):
        messages.extend(
            [
                {
                    "role": "user",
                    "content": f"goal-{index} " * 180,
                },
                {
                    "role": "assistant",
                    "content": f"result-{index} " * 180,
                },
            ]
        )
    status = context_status(messages, max_tokens=4_000)
    assert status["shouldAutoCompact"] is True
    assert status["roleTokens"]["user"] > 0
    assert status["roleTokens"]["assistant"] > 0

    gateway = FakeGateway()
    result = compact_context(
        messages,
        gateway=gateway,
        config={"model_name": "fake"},
        max_tokens=8_000,
        custom_instructions="特别保留工作区边界",
    )
    assert result.compacted is True
    assert result.metadata["originalTokens"] > result.metadata["compactedTokens"]
    assert result.messages[0] == messages[0]
    assert SUMMARY_MARKER in result.messages[1]["content"]
    assert result.messages[2]["role"] == "user"
    assert gateway.requests
    assert "特别保留工作区边界" in gateway.requests[0][0]["content"]
    assert messages[1]["content"].startswith("goal-0")

    try:
        compact_context(
            messages,
            gateway=ExplodingGateway(),
            config={"model_name": "fake"},
            max_tokens=8_000,
        )
    except ContextCompactionError as exc:
        assert str(exc) == "模型摘要请求失败；原上下文已保留。"
        assert "do-not-show" not in str(exc)
    else:
        raise AssertionError("compaction failure must preserve the old context")

    repeated_messages = list(result.messages)
    for index in range(12):
        repeated_messages.extend(
            [
                {"role": "user", "content": f"later-{index} " * 180},
                {"role": "assistant", "content": f"done-{index} " * 180},
            ]
        )
    repeated_gateway = FakeGateway()
    repeated = compact_context(
        repeated_messages,
        gateway=repeated_gateway,
        config={"model_name": "fake"},
        max_tokens=8_000,
    )
    assert repeated.compacted is True
    assert SUMMARY_MARKER in repeated_gateway.requests[0][1]["content"]

    failing = TuiBackend(
        local_agent=FailingLocalAgent(),
        remote_client=None,
        tools=True,
        model_id=None,
        skill_id=None,
    )
    failing.conversation = list(messages)
    original = list(failing.conversation)
    events: list[dict] = []
    failing._auto_compact(events.append)
    assert failing.conversation == original
    assert events[0]["type"] == "context_compaction_started"
    assert events[-1]["type"] == "context_compaction_failed"

    saving_agent = SavingLocalAgent()
    saving = TuiBackend(
        local_agent=saving_agent,
        remote_client=None,
        tools=True,
        model_id=None,
        skill_id=None,
    )
    saving.current_run_id = "run_test123"
    saving.conversation = list(messages)
    saving.transcript = list(messages)
    compacted = saving.compact_context("保留目标")
    assert compacted["compacted"] is True
    assert saving.transcript == messages
    assert saving_agent.saved is not None
    assert saving_agent.saved[0] == "run_test123"

    print("context compaction preserves transcript, persists boundaries, and fails closed")


if __name__ == "__main__":
    main()
