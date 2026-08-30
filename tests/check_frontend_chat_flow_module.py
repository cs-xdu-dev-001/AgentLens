from pathlib import Path
import subprocess
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle not in text:
        raise AssertionError(f"missing {label} in {path}: {needle}")


def require_in_order(text: str, needles: tuple[str, ...], label: str) -> None:
    position = 0
    for needle in needles:
        found = text.find(needle, position)
        if found < 0:
            raise AssertionError(f"missing or out-of-order {label}: {needle}")
        position = found + len(needle)


def forbid(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle in text:
        raise AssertionError(f"unexpected {label} in {path}: {needle}")


def check_retry_snapshot_clone() -> None:
    script = textwrap.dedent(
        """
        import assert from "node:assert/strict";
        import { cloneChatPayload } from "./frontend/react/src/controller/chatFlow.js";
        import {
          agentRunActionKey,
          createAgentRunActionGuard,
        } from "./frontend/react/src/controller/chatFlow.js";

        const blob = new Blob(["immutable"]);
        const attachment = {
          filename: "before.txt",
          optional: undefined,
          blob,
          metadata: {
            trace: { status: "ready" },
            tags: ["original"],
          },
        };
        const attachments = [attachment];
        const payload = {
          question: "snapshot",
          skillId: 17,
          enabledTools: ["search"],
          attachments,
        };

        const snapshot = cloneChatPayload(payload);
        attachments.push({ filename: "later.txt" });
        attachment.filename = "after.txt";
        attachment.metadata.trace.status = "changed";
        attachment.metadata.tags.push("changed");
        payload.enabledTools.push("later-tool");

        assert.notStrictEqual(snapshot.attachments, attachments);
        assert.notStrictEqual(snapshot.attachments[0], attachment);
        assert.notStrictEqual(snapshot.attachments[0].metadata, attachment.metadata);
        assert.notStrictEqual(
          snapshot.attachments[0].metadata.trace,
          attachment.metadata.trace,
        );
        assert.deepEqual(snapshot.enabledTools, ["search"]);
        assert.equal(snapshot.attachments.length, 1);
        assert.equal(snapshot.attachments[0].filename, "before.txt");
        assert.equal(snapshot.attachments[0].metadata.trace.status, "ready");
        assert.deepEqual(snapshot.attachments[0].metadata.tags, ["original"]);
        assert.equal("optional" in snapshot.attachments[0], true);
        assert.equal(snapshot.attachments[0].optional, undefined);
        assert.strictEqual(snapshot.attachments[0].blob, blob);
        assert.equal(snapshot.skillId, 17);

        const { shouldOpenRestoredRun } = await import(
          "./frontend/react/src/controller/chatFlow.js"
        );
        assert.equal(shouldOpenRestoredRun({ id: "active", status: "running" }), true);
        assert.equal(shouldOpenRestoredRun({ id: "failed", status: "failed" }), true);
        assert.equal(shouldOpenRestoredRun({ id: "done", status: "completed" }), false);
        assert.equal(shouldOpenRestoredRun(null), false);

        const guard = createAgentRunActionGuard();
        const detail = { action: "cancel", messageId: "message-1", runId: "run-1" };
        const key = guard.acquire(detail);
        assert.equal(key, agentRunActionKey(detail));
        assert.equal(guard.acquire(detail), null);
        guard.release(key);
        assert.equal(guard.acquire(detail), key);
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
            "chat retry payload clone behavior failed:\n"
            f"{result.stdout}{result.stderr}"
        )


def main() -> None:
    controller = "frontend/react/src/controller/knowflowController.js"
    chat_flow = "frontend/react/src/controller/chatFlow.js"
    bridge = "frontend/react/src/controller/bridgeBindings.js"

    require(chat_flow, "export function createChatFlow", "chat flow factory")
    for token, label in [
        ("async function continueSession", "continue session flow"),
        ("let sessionSwitchController = null;", "abortable session switch"),
        ("publishSessionSwitch(\"loading\"", "session loading state"),
        ("publishSessionSwitch(\"error\"", "session error state"),
        ("publishSessionSwitch(\"success\"", "session success state"),
        ("approvals: Array.isArray(message.approvals)", "restored approval state"),
        ("let workbenchTarget = null;", "restored run selection"),
        ("knowflow:react-agent-trace-open", "restored workbench projection"),
        ("shouldOpenRestoredRun(workbenchTarget.run)", "actionable run auto-open"),
        ("function startNewChat", "new chat flow"),
        ("function stopChatGeneration", "stop generation flow"),
        ("void handleAgentRunAction", "run-aware cancellation without aborting its event stream"),
        ("const liveStream = Boolean", "live stream ownership during cancellation"),
        ("if (!liveStream)", "restored run cancellation reconnect"),
        ("if (ownsSendingState && ownsView() && (!controller || ownsController)) setSending(false);", "sending state belongs to the current view and controller"),
        ("正在安全结束当前操作", "truthful cancellation acknowledgement"),
        ("async function retryAnswer", "retry answer flow"),
        ("async function submitChat", "streaming submit flow"),
        ("appendMessage(\"assistant\", \"\", { thinking: true, streaming: true })", "assistant streaming append"),
        ("state.selectedChatKnowledgeBaseId ? Number(state.selectedChatKnowledgeBaseId) : null", "React-owned knowledge id snapshot"),
        ("state.selectedChatModelConfigId ? Number(state.selectedChatModelConfigId) : null", "React-owned model id snapshot"),
    ]:
        require(chat_flow, token, label)

    chat_flow_text = read(chat_flow)
    require(
        chat_flow,
        "const skillId = retryRequest?.payload?.skillId ?? queuedRequest?.skillId ?? options.skillId ?? null;",
        "retry-safe Skill id resolution",
    )
    require(chat_flow, "export function cloneChatPayload", "retry payload clone")
    require(chat_flow, "if (skillId) payload.skillId = skillId;", "truthy Skill id payload")
    require_in_order(
        chat_flow_text,
        (
            "const skillId = retryRequest?.payload?.skillId ?? queuedRequest?.skillId ?? options.skillId ?? null;",
            "const payload = {",
            "if (skillId) payload.skillId = skillId;",
            "const requestSnapshot = { question, payload: cloneChatPayload(payload) };",
            "messageRetryRequests.set(answer.messageId, requestSnapshot);",
        ),
        "Skill id request snapshot and retry storage",
    )
    forbid(chat_flow, "payload: { ...payload }", "shallow retry payload snapshot")
    forbid(chat_flow, 'publishAgentRunActionState(detail, "succeeded", "恢复请求已接受。");', "generic action acknowledgement")
    check_retry_snapshot_clone()
    require(
        bridge,
        "submitChat({ question: event.detail?.question, skillId: event.detail?.skillId })",
        "bridge forwards Skill id",
    )
    if read(bridge).count(
        "submitChat({ question: event.detail?.question, skillId: event.detail?.skillId })"
    ) < 2:
        raise AssertionError("both submit bridges must forward Skill id")
    forbid(bridge, "selectedSkill", "legacy bridge Skill state")

    require(controller, "createChatFlow", "controller imports chat flow factory")
    require(controller, "chatFlow.continueSession", "controller exposes continue flow to bridges")
    require(controller, "dispatchReactMessagesReset", "controller can clear React messages")
    require(controller, "function clearChatMessages", "controller defines message clearing helper")

    for token, label in [
        ("async function continueSession", "inline continue session flow"),
        ("function startNewChat", "inline new chat flow"),
        ("function stopChatGeneration", "inline stop generation flow"),
        ("async function retryAnswer", "inline retry answer flow"),
        ("async function submitChat", "inline streaming submit flow"),
        ("resetReactChatMessages", "undefined legacy reset helper"),
    ]:
        forbid(controller, token, label)

    print("chat streaming flow is split out of knowflowController")


if __name__ == "__main__":
    main()
