from pathlib import Path

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


def main() -> None:
    controller = "frontend/react/src/controller/knowflowController.js"
    chat_flow = "frontend/react/src/controller/chatFlow.js"
    bridge = "frontend/react/src/controller/bridgeBindings.js"

    require(chat_flow, "export function createChatFlow", "chat flow factory")
    for token, label in [
        ("async function continueSession", "continue session flow"),
        ("function startNewChat", "new chat flow"),
        ("function stopChatGeneration", "stop generation flow"),
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
        "const skillId = retryRequest?.payload?.skillId ?? options.skillId ?? null;",
        "retry-safe Skill id resolution",
    )
    require(chat_flow, "if (skillId) payload.skillId = skillId;", "truthy Skill id payload")
    require_in_order(
        chat_flow_text,
        (
            "const skillId = retryRequest?.payload?.skillId ?? options.skillId ?? null;",
            "const payload = {",
            "if (skillId) payload.skillId = skillId;",
            "const requestSnapshot = { question, payload: { ...payload } };",
            "messageRetryRequests.set(answer.messageId, requestSnapshot);",
        ),
        "Skill id request snapshot and retry storage",
    )
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
