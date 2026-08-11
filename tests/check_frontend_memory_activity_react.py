from pathlib import Path
import re
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    if needle not in read(path):
        raise AssertionError(
            f"missing {label} in {path}: {needle}"
        )


def extract_function(source: str, name: str) -> str:
    match = re.search(
        rf"function\s+{re.escape(name)}\s*\(",
        source,
    )
    assert match, f"missing JavaScript function: {name}"
    parameter_start = source.find("(", match.start())
    parameter_depth = 0
    parameter_end = -1
    for index in range(parameter_start, len(source)):
        if source[index] == "(":
            parameter_depth += 1
        elif source[index] == ")":
            parameter_depth -= 1
            if parameter_depth == 0:
                parameter_end = index
                break
    assert parameter_end >= 0, f"unclosed parameters: {name}"
    opening = source.find("{", parameter_end)
    assert opening >= 0, f"missing function body: {name}"
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[match.start():index + 1]
    raise AssertionError(f"unclosed JavaScript function: {name}")


def check_memory_sync_copy() -> None:
    source = read(
        "frontend/react/src/components/ChatMessages.jsx"
    )
    declarations = "\n".join(
        extract_function(source, name)
        for name in (
            "memoryOperations",
            "memoryWriteOperation",
            "memoryStatusText",
        )
    )
    script = textwrap.dedent(
        f"""
        import assert from "node:assert/strict";
        {declarations}
        const pending = {{
          summary: {{}},
          operations: [{{ kind: "write", status: "running" }}],
        }};
        assert.equal(
          memoryStatusText(pending, {{ syncFailures: 3 }}),
          "后台仍在整理，状态同步较慢…",
        );
        assert.equal(
          memoryStatusText(pending, {{ pollingExpired: true }}),
          "后台仍在整理，可刷新查看状态",
        );
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise AssertionError(
            "memory polling delays must be visible:\n"
            f"{result.stdout}{result.stderr}"
        )


def check_memory_trace_reconciliation() -> None:
    script = textwrap.dedent(
        """
        import assert from "node:assert/strict";
        import {
          mergeMemoryActivityTrace,
        } from "./frontend/react/src/controller/memoryActivity.js";
        import {
          traceStepWaitState,
        } from "./frontend/react/src/controller/agentRunState.js";

        const waitingTrace = [
          {
            stepId: "trace-write",
            kind: "memory",
            name: "memory_write",
            status: "waiting",
            title: "Waiting for long-term memory write",
            details: { operationId: "operation-write" },
          },
        ];
        const completedActivity = {
          messageId: 42,
          summary: { recalled: 1, added: 1, updated: 0, deleted: 0 },
          operations: [
            {
              id: "operation-write",
              kind: "write",
              status: "succeeded",
              attemptCount: 1,
              items: [
                { action: "add", content: "用户默认使用Java。" },
              ],
            },
          ],
        };

        const merged = mergeMemoryActivityTrace(
          waitingTrace,
          completedActivity,
        );
        assert.equal(merged.length, 1);
        assert.equal(merged[0].stepId, "trace-write");
        assert.equal(merged[0].status, "success");
        assert.equal(merged[0].title, "长期记忆整理完成");
        assert.equal(merged[0].details.items.length, 1);

        const ordinaryTrace = mergeMemoryActivityTrace(
          [],
          completedActivity,
        );
        assert.deepEqual(ordinaryTrace, []);

        assert.deepEqual(
          traceStepWaitState({ kind: "approval", status: "waiting" }),
          { approval: true, background: false },
        );
        assert.deepEqual(
          traceStepWaitState({ kind: "memory", status: "waiting" }),
          { approval: false, background: true },
        );
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise AssertionError(
            "completed memory activity must reconcile a waiting trace:\n"
            f"{result.stdout}{result.stderr}"
        )


def main() -> None:
    client = "frontend/react/src/api/client.js"
    messages = "frontend/react/src/components/ChatMessages.jsx"
    events = "frontend/react/src/controller/messageEvents.js"
    flow = "frontend/react/src/controller/chatFlow.js"
    trace = (
        "frontend/react/src/components/agentTracePresentation.js"
    )
    activity = "frontend/react/src/controller/memoryActivity.js"
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
        "MEMORY_ACTIVITY_MAX_POLLS = 240",
        "long-running memory polling window",
    )
    require(
        messages,
        "[initialWriteId, messageId]",
        "poll budget reset only for a new memory operation",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "后台整理中，不影响继续对话",
        "non-blocking memory wait copy",
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
        activity,
        "knowflow:react-memory-activity-updated",
        "settled activity broadcast",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "knowflow:react-memory-activity-updated",
        "open drawer reconciliation",
    )
    require(
        events,
        "updateReactMessageMemoryActivity",
        "memory activity event bridge",
    )
    require(
        "frontend/react/src/controller/agentEvents.js",
        "event?.memoryActivity",
        "stream completion memory state",
    )
    require(
        flow,
        "message.memoryActivity",
        "history memory state",
    )
    require(trace, 'memory: "MEMORY"', "memory trace badge")
    require(trace, "traceMemoryItems", "safe memory item details")
    require(styles, ".memory-activity-status", "compact status styling")
    require(styles, ".memory-activity-retry", "retry styling")
    check_memory_trace_reconciliation()
    check_memory_sync_copy()

    print("memory activity is visible, inspectable, and retryable")


if __name__ == "__main__":
    main()
