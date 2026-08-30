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
    require("frontend/react/src/components/ChatComposerForm.jsx", "question", "React composer question state")
    require("frontend/react/src/components/ChatComposerForm.jsx", "setQuestion", "React composer question setter")
    require("frontend/react/src/components/ChatComposerForm.jsx", "textareaRef", "React composer textarea ref")
    require("frontend/react/src/components/ChatComposerForm.jsx", "resizeTextarea", "React composer textarea autoresize")
    require("frontend/react/src/components/ChatComposerForm.jsx", "knowflow:react-composer-reset", "React composer reset command")
    require("frontend/react/src/components/ChatComposerForm.jsx", "value={question}", "controlled textarea value")
    require("frontend/react/src/components/ChatComposerForm.jsx", "detail: { question: question.trim() }", "submit sends question payload")
    require("frontend/react/src/controller/knowflowController.js", "requestComposerReset", "controller asks React to reset composer")
    require("frontend/react/src/controller/chatFlow.js", "options.question", "chat flow reads question from React event")
    require("frontend/react/src/components/ChatComposerForm.jsx", "promptStash", "React composer prompt stash state")
    require("frontend/react/src/components/ChatComposerForm.jsx", "Ctrl+S", "prompt stash shortcut copy")
    require("frontend/react/src/components/ChatComposerForm.jsx", "草稿已暂存，发送当前输入后自动恢复", "prompt stash status")
    require("frontend/react/src/components/ChatComposerForm.jsx", "pendingStashRestoreRef", "accepted-submit stash restoration guard")
    require("frontend/react/src/controller/bridgeBindings.js", "knowflow:react-attachments-replace", "stashed attachment restoration bridge")
    require("frontend/react/src/controller/bridgeBindings.js", "renderAttachmentTray,", "attachment tray bridge dependency")
    require("frontend/react/src/controller/knowflowController.js", "renderAttachmentTray,", "attachment tray bridge injection")
    require("frontend/react/src/styles.css", ".composer-stash-notice", "prompt stash presentation")

    for needle, label in [
        ("function resizeComposer", "legacy composer textarea resize helper"),
        ("#chat-form textarea", "legacy textarea DOM lookup"),
        ("$(\"#chat-form\").reset()", "legacy form reset lookup"),
        ("form.reset()", "legacy form reset call"),
        ("knowflow:react-chat-input", "legacy chat input bridge event"),
        ("input.style.height", "legacy textarea style mutation"),
    ]:
        forbid("frontend/react/src/controller/knowflowController.js", needle, label)

    print("composer input value and textarea sizing are owned by React")


if __name__ == "__main__":
    main()
