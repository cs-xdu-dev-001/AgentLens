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
    require(composer, "ComposerModelPicker", "composer model picker mount")
    require(
        composer,
        "disabled={sending || switchingSession}",
        "sending and session-switch state lock",
    )

    require(sidebar, "chat_model_config_id", "saved session model field")
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
        ".composer-reasoning-section",
    ):
        if selector not in styles:
            raise AssertionError(f"Missing composer model style: {selector}")
    if "@media (max-width: 520px)" not in styles:
        raise AssertionError("Missing compact composer model layout")

    print("composer model picker is visible, durable, and accessible")


if __name__ == "__main__":
    main()
