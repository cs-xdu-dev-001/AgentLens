from pathlib import Path
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
        messages,
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
    check_memory_trace_reconciliation()

    print("memory activity is visible, inspectable, and retryable")


if __name__ == "__main__":
    main()
