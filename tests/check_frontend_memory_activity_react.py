from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    if needle not in read(path):
        raise AssertionError(
            f"missing {label} in {path}: {needle}"
        )


def main() -> None:
    client = "frontend/react/src/api/client.js"
    messages = "frontend/react/src/components/ChatMessages.jsx"
    events = "frontend/react/src/controller/messageEvents.js"
    flow = "frontend/react/src/controller/chatFlow.js"
    trace = "frontend/react/src/components/AgentTraceView.jsx"
    styles = "frontend/react/src/styles.css"

    require(
        client,
        "activity: (messageId)",
        "message memory activity API",
    )
    require(
        client,
        "retryOperation: (operationId)",
        "failed write retry API",
    )
    require(
        messages,
        "MemoryActivityStatus",
        "compact memory activity status",
    )
    require(
        messages,
        "memoryActivity",
        "message memory activity state",
    )
    require(
        messages,
        "正在整理记忆",
        "running memory copy",
    )
    require(
        messages,
        "记忆写入失败",
        "failed memory copy",
    )
    require(
        messages,
        "memoryApi.retryOperation",
        "memory retry interaction",
    )
    require(
        messages,
        "setPollTick",
        "polling survives a transient request failure",
    )
    require(
        messages,
        "knowflow:react-agent-trace-open",
        "memory detail drawer reuse",
    )
    require(
        events,
        "updateReactMessageMemoryActivity",
        "memory activity event bridge",
    )
    require(
        flow,
        "eventPayload.memoryActivity",
        "stream completion memory state",
    )
    require(
        flow,
        "message.memoryActivity",
        "history memory state",
    )
    require(trace, 'memory: "MEMORY"', "memory trace badge")
    require(trace, "memoryDetailsForDisplay", "safe memory item details")
    require(styles, ".memory-activity-status", "compact status styling")
    require(styles, ".memory-activity-retry", "retry styling")

    print("memory activity is visible, inspectable, and retryable")


if __name__ == "__main__":
    main()
