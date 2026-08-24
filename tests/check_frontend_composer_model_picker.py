from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def require(relative_path: str, needle: str, label: str) -> None:
    if needle not in read(relative_path):
        raise AssertionError(f"Missing {label}: {needle}")


def main() -> None:
    component = "frontend/react/src/components/ComposerModelPicker.jsx"
    composer = "frontend/react/src/components/ChatComposerForm.jsx"
    sidebar = "frontend/react/src/components/Sidebar.jsx"
    bridge = "frontend/react/src/controller/bridgeBindings.js"
    chat_flow = "frontend/react/src/controller/chatFlow.js"

    require(
        component,
        "knowflow:react-model-options-updated",
        "model catalog event",
    )
    require(
        component,
        "knowflow:react-model-selection-updated",
        "model selection event",
    )
    require(
        component,
        "knowflow:react-chat-model-change",
        "model change dispatch",
    )
    require(component, 'model.modelType === "chat"', "chat-only filter")
    require(component, 'role={"listbox"}', "model listbox semantics")
    require(component, 'event.key === "ArrowDown"', "keyboard next option")
    require(component, 'event.key === "ArrowUp"', "keyboard previous option")
    require(component, 'event.key === "Enter"', "keyboard model selection")
    require(component, 'event.key === "Escape"', "keyboard close")
    require(component, "配置模型", "empty model action")
    require(component, "管理模型", "model settings action")
    require(component, "推理强度", "reasoning effort controls")
    require(component, "knowflow:react-chat-reasoning-change", "reasoning change dispatch")
    require(component, 'role={"radiogroup"}', "reasoning radio semantics")
    require(component, "aria-activedescendant", "active option semantics")
    require(component, 'import Fuse from "fuse.js"', "mature fuzzy search library")
    require(component, "搜索模型、提供商或协议", "model search input")
    require(component, 'aria-keyshortcuts={"Alt+P"}', "model shortcut semantics")
    require(component, "agentlens.recentChatModels.v1", "recent model ordering")
    require(component, "没有匹配", "empty model search state")
    require(component, "上下文预算", "context budget section")
    require(component, 'role={"progressbar"}', "context progress semantics")
    require(component, "composer-context-value", "context trigger summary")
    require(component, "压缩早期对话", "manual context compaction action")
    require(component, "onCompactContext", "context compaction callback")
    require(component, 'reasoning: ".composer-reasoning-section"', "reasoning focus target")
    require(composer, "ComposerModelPicker", "composer model picker mount")
    require(composer, "contextStatus={contextStatus}", "composer context projection")
    require(composer, "contextOperation={contextOperation}", "context compaction state projection")
    require(composer, 'command.action === "context"', "context slash command")
    require(composer, '["reasoning", "status"].includes(command.action)', "session status commands")
    require(composer, 'command.action === "help"', "command browser action")
    require(
        composer,
        "disabled={sending || switchingSession}",
        "sending and session-switch state lock",
    )

    require(sidebar, "chat_model_config_id", "saved session model field")
    require(sidebar, "sessionApi.compactContext", "session context compaction API call")
    require(sidebar, "chatModelConfigId", "session model event payload")
    require(bridge, "resolveChatModelConfigId", "session model validation")
    require(
        bridge,
        "notifyReactModelSelectionUpdated",
        "session model React synchronization",
    )
    require(
        chat_flow,
        "retryRequest?.payload?.chatModelConfigId",
        "retry keeps original request model",
    )
    require(
        chat_flow,
        "retryRequest?.payload?.reasoningEffort",
        "retry keeps original reasoning effort",
    )
    require(chat_flow, "reasoningEffort,", "reasoning effort API payload")
    require(bridge, "selectedReasoningEffort", "reasoning state synchronization")

    styles = read("frontend/styles.css") + read("frontend/refinement.css")
    for selector in (
        ".composer-model-trigger",
        ".composer-model-popover",
        ".composer-model-option",
        ".composer-model-option.selected",
        ".composer-model-search",
        ".composer-model-empty",
        ".composer-reasoning-section",
        ".composer-context-section",
        ".composer-context-track",
    ):
        if selector not in styles:
            raise AssertionError(f"Missing composer model style: {selector}")
    if "@media (max-width: 520px)" not in styles:
        raise AssertionError("Missing compact composer model layout")

    print("composer model picker is visible, durable, and accessible")


if __name__ == "__main__":
    main()
