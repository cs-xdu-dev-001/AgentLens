from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def require(relative_path: str, needle: str, label: str) -> None:
    if needle not in read(relative_path):
        raise AssertionError(f"Missing {label}: {needle}")


def forbid(relative_path: str, needle: str, label: str) -> None:
    if needle in read(relative_path):
        raise AssertionError(f"Legacy {label} still present: {needle}")


def main() -> None:
    require("frontend/react/src/components/ChatComposerForm.jsx", "sending", "React composer sending state")
    require("frontend/react/src/components/ChatComposerForm.jsx", "knowflow:react-sending-updated", "React composer sending event")
    require("frontend/react/src/controller/knowflowController.js", "knowflow:react-sending-updated", "controller dispatches React sending event")
    require("frontend/react/src/components/ChatComposerForm.jsx", "knowflow:react-chat-queue-updated", "React composer queue event")
    require("frontend/react/src/components/ChatComposerForm.jsx", "继续输入，Enter加入待发送", "running composer remains usable")
    require("frontend/react/src/controller/chatFlow.js", "appendQueuedChatRequest", "chat queue reducer")
    require("frontend/react/src/controller/chatFlow.js", "scheduleQueuedChat", "chat queue automatic drain")
    require("frontend/react/src/controller/chatFlow.js", "chatQueuePaused", "chat queue pause state")
    require("frontend/react/src/controller/chatFlow.js", "CHAT_QUEUE_PRIORITIES", "Claude-style queue priorities")
    require("frontend/react/src/controller/chatFlow.js", "reprioritizeQueuedChatRequest", "queue reprioritization")
    require("frontend/react/src/controller/chatFlow.js", "settleQueueAfterRun", "queue resumes after interaction settles")
    require("frontend/react/src/controller/chatFlow.js", "任务尚未发送", "queue send rollback")
    require("frontend/react/src/controller/controllerState.js", "chatQueueBlockReason", "queue blocking reason")
    require("frontend/react/src/components/ChatComposerForm.jsx", "composer-queue-priority", "queue priority selector")
    require("frontend/react/src/components/ChatComposerForm.jsx", "等待权限确认", "approval queue block copy")
    require("frontend/react/src/controller/bridgeBindings.js", "knowflow:react-chat-queue-action", "chat queue action bridge")

    forbid("frontend/react/src/components/ChatComposerForm.jsx", "knowflow:legacy-sending-updated", "legacy sending event listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:legacy-sending-updated", "legacy sending event dispatch")
    forbid("frontend/react/src/controller/knowflowController.js", "notifyReactSendingUpdated", "legacy sending notifier")
    forbid("frontend/react/src/controller/knowflowController.js", "__knowflowReactSendingStateEnabled", "legacy sending ownership flag")
    forbid("frontend/react/src/controller/knowflowController.js", "renderSendButton", "legacy send button renderer")
    forbid("frontend/react/src/controller/knowflowController.js", "chat-submit-btn", "legacy send button DOM access")

    script = r'''import {
  appendQueuedChatRequest,
  orderQueuedChatRequests,
  reprioritizeQueuedChatRequest,
  takeQueuedChatRequest,
} from "./frontend/react/src/controller/chatFlow.js";

const queue = [
  {id: "later", question: "稍后", priority: "later", sequence: 1},
  {id: "next-2", question: "接下来2", priority: "next", sequence: 3},
  {id: "now", question: "立即", priority: "now", sequence: 5},
  {id: "next-1", question: "接下来1", priority: "next", sequence: 2},
];
const ordered = orderQueuedChatRequests(queue);
if (ordered.map(item => item.id).join(",") !== "now,next-1,next-2,later") {
  throw new Error("queue priority order is unstable");
}
const duplicate = appendQueuedChatRequest(queue, queue[0]);
if (duplicate.length !== queue.length) throw new Error("queue duplicate accepted");
const reprioritized = reprioritizeQueuedChatRequest(queue, "later", "now");
if (reprioritized[0].id !== "later") throw new Error("reprioritize failed");
const taken = takeQueuedChatRequest(queue);
if (taken.request.id !== "now" || taken.remaining.length !== 3) {
  throw new Error("priority dequeue failed");
}
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)


if __name__ == "__main__":
    main()
