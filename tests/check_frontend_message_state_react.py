from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle not in text:
        raise AssertionError(f"missing {label} in {path}: {needle}")


def forbid(path: str, needle: str, label: str) -> None:
    text = read(path)
    if needle in text:
        raise AssertionError(f"unexpected {label} in {path}: {needle}")


def main() -> None:
    controller = "frontend/react/src/controller/knowflowController.js"
    chat_flow = "frontend/react/src/controller/chatFlow.js"
    messages = "frontend/react/src/components/ChatMessages.jsx"
    message_events = "frontend/react/src/controller/messageEvents.js"

    require(controller, "messageRetryRequests", "controller retry metadata map")
    require(controller, "messageRetryRequests.clear()", "retry metadata is cleared with rendered messages")
    require(chat_flow, "messageId", "chat flow uses React message ids")
    require(chat_flow, "answer.streaming", "chat flow tracks streaming on message handle")
    require(chat_flow, "answer.thinking", "chat flow tracks thinking on message handle")
    require(messages, "detail.messageId", "React message events expose message id")
    require(messages, "data-react-message-id", "React message id retained for actions")
    require(messages, "message.retryable", "retry action only renders for retryable answers")
    require(messages, "!message.streaming", "message actions wait for streaming to finish")
    require(messages, 'aria-label={"复制答案"}', "localized copy action label")
    require(messages, 'aria-label={"重新生成"}', "localized retry action label")
    require(messages, 'aria-label={"编辑并重新发送"}', "localized user edit action label")
    require(messages, 'edit: "knowflow:react-message-edit"', "user edit action event")
    require(messages, 'rewind: "knowflow:react-message-rewind"', "user rewind action event")
    require(messages, "message.sourceMessageId", "rewind action requires a persisted message id")
    require(
        "frontend/react/src/controller/bridgeBindings.js",
        'window.addEventListener("knowflow:react-message-edit"',
        "user message edit bridge",
    )
    require(
        "frontend/react/src/controller/bridgeBindings.js",
        'requestComposerReset({ focus: true, question })',
        "user message edit restores composer",
    )
    require(
        "frontend/react/src/controller/bridgeBindings.js",
        'window.addEventListener("knowflow:react-message-rewind"',
        "user message rewind bridge",
    )
    require(chat_flow, "beforeMessageId: branchPoint", "rewind branch point reaches the API")
    require(chat_flow, "restoredQuestion", "rewind restores the selected question")
    require(messages, 'from "../controller/markdown.js"', "React message component renders markdown internally")
    require(message_events, "retryable", "message bridge carries retry availability")
    require("frontend/styles.css", ".message-actions button svg", "bounded message action icons")
    require(
        "frontend/styles.css",
        "@media (hover: none), (max-width: 760px)",
        "message actions remain available on touch screens",
    )
    forbid(messages, "payload.html", "message append should not trust external HTML")
    forbid(messages, "detail.html", "message update should not trust external HTML")
    forbid(messages, "messageRetryRequests", "message retry map should not live in React component")
    forbid(
        messages,
        'rawContent: "", thinking: Boolean(detail.enabled)',
        "disabling the thinking state must not clear a completed answer",
    )
    forbid(
        chat_flow,
        'eventPayload.type === "answer") {\n            answer.streaming = false;',
        "streaming state ending on the first answer chunk",
    )

    for needle, label in [
        ("function $(selector)", "legacy query helper"),
        ("function $all(selector)", "legacy queryAll helper"),
        (".classList.", "legacy classList state mutations"),
        (".classList.add", "legacy classList add"),
        (".classList.remove", "legacy classList remove"),
        (".classList.contains", "legacy classList contains"),
        (".__retryRequest", "legacy retry request on DOM node"),
        ("#chat-messages .message-row.assistant .message.assistant", "legacy last assistant DOM lookup"),
        ("bubble?.dataset", "legacy bubble dataset read"),
        ("bubble?.textContent", "legacy bubble text read"),
    ]:
        forbid(controller, needle, label)

    print("assistant message streaming and retry state use React message ids")


if __name__ == "__main__":
    main()
