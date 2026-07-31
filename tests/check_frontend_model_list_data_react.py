from pathlib import Path
import re


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
    panel = read("frontend/react/src/components/ModelListPanel.jsx")
    require("frontend/react/src/components/ModelListPanel.jsx", 'chat_completions: "Chat Completions"', "Chat Completions protocol label")
    require("frontend/react/src/components/ModelListPanel.jsx", 'responses: "Responses API"', "Responses protocol label")
    require("frontend/react/src/components/ModelListPanel.jsx", 'apiModeLabel[model.apiMode] || apiModeLabel.chat_completions', "legacy API protocol fallback")
    if not re.search(r'model\.modelType === "chat" \? " · "', panel):
        raise AssertionError("protocol must only render for chat models")
    require("frontend/react/src/components/SettingsPage.jsx", "loadModels", "React settings model loader")
    require("frontend/react/src/components/SettingsPage.jsx", "modelConfigApi.list", "React settings loads model list")
    require("frontend/react/src/components/SettingsPage.jsx", "setModels", "React settings owns model list state")
    require("frontend/react/src/components/SettingsPage.jsx", "await loadModels()", "React settings refreshes after mutations")
    require("frontend/react/src/components/SettingsPage.jsx", "requestModelOptionsRefresh", "React settings still refreshes shared model options")
    require("frontend/react/src/controller/reactNotifications.js", "knowflow:react-model-options-updated", "controller broadcasts shared model options through React channel")

    forbid("frontend/react/src/components/SettingsPage.jsx", "knowflow:legacy-models-updated", "legacy model list data event")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:legacy-models-updated", "legacy model list broadcast")
    forbid("frontend/react/src/components/ChatContextToolbar.jsx", "knowflow:legacy-model-options-updated", "legacy model options listener")
    forbid("frontend/react/src/components/ChatContextToolbar.jsx", "knowflow:legacy-model-selection-updated", "legacy model selection listener")
    forbid("frontend/react/src/components/KnowledgeModals.jsx", "knowflow:legacy-model-options-updated", "legacy modal model options listener")
    forbid("frontend/react/src/components/KnowledgeSummary.jsx", "knowflow:legacy-model-options-updated", "legacy summary model options listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:legacy-model-options-updated", "legacy model options broadcast")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:legacy-model-selection-updated", "legacy model selection broadcast")
    forbid("frontend/react/src/controller/knowflowController.js", "__knowflowReactModelOptionsEnabled", "dead model options ownership flag")


if __name__ == "__main__":
    main()
