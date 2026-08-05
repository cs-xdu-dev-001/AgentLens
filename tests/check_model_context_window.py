from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.model_context_window import prepare_model_context


def main() -> None:
    messages = [{"role": "system", "content": "Keep policy."}]
    for index in range(40):
        messages.extend(
            [
                {"role": "user", "content": f"old-{index} " * 100},
                {"role": "assistant", "content": f"answer-{index} " * 100},
            ]
        )
    messages.extend(
        [
            {"role": "user", "content": "latest request"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-latest",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-latest",
                "name": "lookup",
                "content": "current result",
            },
        ]
    )

    window = prepare_model_context(messages, max_tokens=2_000)
    assert window.trimmed is True
    assert window.original_tokens > window.sent_tokens
    assert window.messages[0]["role"] == "system"
    assert any(
        message.get("content") == "latest request"
        for message in window.messages
    )
    assert window.messages[-1]["role"] == "tool"
    assert window.messages[-1]["tool_call_id"] == "call-latest"

    small = prepare_model_context(
        [{"role": "user", "content": "hello"}],
        max_tokens=2_000,
    )
    assert small.trimmed is False
    assert small.messages == [{"role": "user", "content": "hello"}]

    print("model context uses bounded LangChain trimming without mutating history")


if __name__ == "__main__":
    main()
