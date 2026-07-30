from pathlib import Path
import re


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


def forbid_in_function(path: str, function_name: str, needle: str, label: str) -> None:
    text = read(path)
    marker = f"const {function_name} ="
    start = text.find(marker)
    if start == -1:
        raise AssertionError(f"missing function {function_name} in {path}")
    next_handler = text.find("\n  const ", start + len(marker))
    body = text[start:] if next_handler == -1 else text[start:next_handler]
    if needle in body:
        raise AssertionError(f"unexpected {label} in {path}::{function_name}: {needle}")


def main() -> None:
    require("frontend/react/src/api/client.js", "modelConfigApi", "model config API helper")
    require("frontend/react/src/data/settings.js", "export const providerPresets", "provider preset data module")
    require("frontend/react/src/components/SettingsPage.jsx", "modelConfigApi", "settings page owns model API calls")
    require("frontend/react/src/components/SettingsPage.jsx", "formValues", "settings page owns model form state")
    require("frontend/react/src/components/SettingsPage.jsx", "handleModelSubmit", "React model submit handler")
    require("frontend/react/src/components/SettingsPage.jsx", "handleModelEdit", "React model edit handler")
    require("frontend/react/src/components/SettingsPage.jsx", "handleModelTest", "React model test handler")
    require("frontend/react/src/components/SettingsPage.jsx", "handleSetDefaultModel", "React default model handler")
    require("frontend/react/src/components/SettingsPage.jsx", "handleDeleteModel", "React model delete handler")
    require("frontend/react/src/components/SettingsPage.jsx", "loadModels", "React model list loader")
    require("frontend/react/src/components/SettingsPage.jsx", "modelConfigApi.list", "React model list API call")
    require("frontend/react/src/components/SettingsPage.jsx", "knowflow:react-models-refresh-request", "React asks legacy data hub to refresh models")
    require("frontend/react/src/components/ModelConfigForm.jsx", "value={formValues.name}", "controlled model name input")
    require("frontend/react/src/components/ModelConfigForm.jsx", "onChange={onFieldChange}", "controlled model form input change")
    require("frontend/react/src/components/ModelConfigForm.jsx", "onSubmit={onSubmit}", "React submit callback")
    require("frontend/react/src/components/ModelConfigForm.jsx", "selectedPresetValue", "controlled preset select")
    require("frontend/react/src/components/ModelConfigForm.jsx", "{editingModelId ? (", "cancel action only appears while editing")
    require("frontend/react/src/components/ModelProviderSelector.jsx", "selectedProvider", "controlled provider selector")
    require("frontend/react/src/components/ModelProviderSelector.jsx", "aria-pressed={selectedProvider === provider.key}", "provider selection accessibility state")
    require("frontend/styles.css", "Compact provider selector pass", "compact provider selector styles")
    require("frontend/styles.css", "grid-template-columns: repeat(2, minmax(0, 1fr))", "two-column mobile provider selector")
    require("frontend/styles.css", ':root[data-theme="mono-dark"] #page-settings #provider-grid .provider-card.selected', "dark provider selected state")
    require("frontend/styles.css", "color: var(--text) !important;", "dark provider selected text contrast")
    require("frontend/react/src/components/ModelListPanel.jsx", "onModelEdit", "model edit callback prop")
    require("frontend/react/src/components/ModelListPanel.jsx", "onModelTest", "model test callback prop")
    require("frontend/react/src/components/ModelListPanel.jsx", "待检查", "productized unchecked model status")
    require("frontend/react/src/components/ModelListPanel.jsx", "检查", "productized model connection action")
    require("frontend/react/src/components/SettingsPage.jsx", "模型连接检查完成", "productized model connection success copy")
    require("frontend/react/src/components/SettingsPage.jsx", "检查模型失败", "productized model connection failure copy")
    require("frontend/react/src/components/ModelListPanel.jsx", "onSetDefaultModel", "default model callback prop")
    require("frontend/react/src/components/ModelListPanel.jsx", "onDeleteModel", "delete model callback prop")
    settings_page = read("frontend/react/src/components/SettingsPage.jsx")
    form = read("frontend/react/src/components/ModelConfigForm.jsx")
    require("frontend/react/src/components/SettingsPage.jsx", 'apiMode: "chat_completions"', "default API protocol")
    require("frontend/react/src/components/SettingsPage.jsx", 'apiMode: preset.apiMode || "chat_completions"', "preset API fallback")
    require("frontend/react/src/components/SettingsPage.jsx", 'apiMode: valueForInput(model.apiMode || "chat_completions")', "model API fallback")
    require("frontend/react/src/components/SettingsPage.jsx", 'apiMode: formValues.modelType === "chat" && formValues.apiMode === "responses" ? "responses" : "chat_completions"', "payload API protocol")
    require("frontend/react/src/components/SettingsPage.jsx", 'name === "modelType" && value !== "chat" ? { apiMode: "chat_completions" }', "non-chat protocol reset")
    if not re.search(r'formValues\.modelType === "chat" \? \(\s*<label>[\s\S]*?name=\{"apiMode"\}', form):
        raise AssertionError("API protocol select must be conditional on chat model type")
    for needle in ['value={"chat_completions"}>{"Chat Completions"}', 'value={"responses"}>{"Responses API"}']:
        require("frontend/react/src/components/ModelConfigForm.jsx", needle, "API protocol option")
    require("frontend/react/src/controller/bridgeBindings.js", "knowflow:react-models-refresh-request", "bridge module refreshes model data on React request")

    forbid("frontend/react/src/components/ModelConfigForm.jsx", "knowflow:react-model-submit", "legacy model form submit event")
    forbid("frontend/react/src/components/ModelConfigForm.jsx", "detail: { form:", "passing form DOM to legacy controller")
    forbid("frontend/react/src/components/ModelConfigForm.jsx", "knowflow:react-model-provider-input", "legacy provider input event")
    forbid("frontend/react/src/components/ModelConfigForm.jsx", "knowflow:react-model-preset-change", "legacy preset change event")
    forbid("frontend/react/src/components/ModelProviderSelector.jsx", "knowflow:react-provider-change", "legacy provider card event")
    forbid("frontend/react/src/components/ModelProviderSelector.jsx", "provider.description", "provider descriptions inside option buttons")
    forbid("frontend/react/src/components/ModelListPanel.jsx", "knowflow:react-model-edit", "legacy model edit event")
    forbid("frontend/react/src/components/ModelListPanel.jsx", "knowflow:react-model-test", "legacy model test event")
    forbid("frontend/react/src/components/ModelListPanel.jsx", "未测试", "test-like unchecked model status")
    forbid("frontend/react/src/components/ModelListPanel.jsx", ">测试<", "test-like model action label")
    forbid("frontend/react/src/components/SettingsPage.jsx", "模型连接测试完成", "test-like model success copy")
    forbid("frontend/react/src/components/SettingsPage.jsx", "测试模型失败", "test-like model failure copy")
    forbid("frontend/react/src/components/ModelListPanel.jsx", "knowflow:react-model-default", "legacy default model event")
    forbid("frontend/react/src/components/ModelListPanel.jsx", "knowflow:react-model-delete", "legacy delete model event")
    forbid("frontend/react/src/components/SettingsPage.jsx", "knowflow:legacy-models-updated", "legacy model list data event")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:legacy-models-updated", "legacy model list broadcast")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:react-model-submit", "legacy model submit listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:react-model-edit", "legacy model edit listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:react-model-test", "legacy model test listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:react-model-default", "legacy default model listener")
    forbid("frontend/react/src/controller/knowflowController.js", "knowflow:react-model-delete", "legacy delete model listener")
    forbid("frontend/react/src/controller/knowflowController.js", "state.editingModelId", "legacy model edit state")
    forbid("frontend/react/src/controller/knowflowController.js", "const PROVIDER_PRESETS", "duplicate legacy provider presets")
    forbid("frontend/react/src/controller/knowflowController.js", "submitModelConfigForm", "legacy model form submit function")
    forbid("frontend/react/src/controller/knowflowController.js", "providerKey", "legacy provider resolver")
    forbid("frontend/react/src/controller/knowflowController.js", "selectProviderCard", "legacy provider card sync")
    forbid("frontend/react/src/controller/knowflowController.js", "buildPresetOptions", "legacy preset option builder")
    forbid("frontend/react/src/controller/knowflowController.js", "applyProviderPreset", "legacy provider preset applier")
    forbid("frontend/react/src/controller/knowflowController.js", "applyModelPreset", "legacy model preset applier")
    forbid("frontend/react/src/controller/knowflowController.js", "function editModel", "legacy model edit function")
    forbid("frontend/react/src/controller/knowflowController.js", "function testModel", "legacy model test function")
    forbid("frontend/react/src/controller/knowflowController.js", "function setDefaultModel", "legacy default model function")
    forbid("frontend/react/src/controller/knowflowController.js", "function deleteModel", "legacy delete model function")
    forbid("frontend/react/src/controller/knowflowController.js", "onclick=\"editModel", "legacy inline edit model handler")
    forbid("frontend/react/src/controller/knowflowController.js", "window.editModel", "legacy global model edit export")
    forbid("frontend/react/src/controller/knowflowController.js", "window.testModel", "legacy global model test export")
    forbid("frontend/react/src/controller/knowflowController.js", "window.setDefaultModel", "legacy global default model export")
    forbid("frontend/react/src/controller/knowflowController.js", "window.deleteModel", "legacy global delete model export")
    forbid("frontend/react/src/controller/knowflowController.js", "__knowflowReactProviderCardsEnabled", "dead provider-card ownership flag")
    forbid("frontend/react/src/controller/knowflowController.js", "__knowflowReactSettingsControlsEnabled", "dead settings-controls ownership flag")
    forbid("frontend/react/src/controller/knowflowController.js", "__knowflowReactModelListEnabled", "dead model-list ownership flag")
    forbid_in_function(
        "frontend/react/src/components/SettingsPage.jsx",
        "handleProviderSelect",
        "setEditingModelId(null)",
        "provider selection clearing model edit state",
    )
    forbid_in_function(
        "frontend/react/src/components/SettingsPage.jsx",
        "handlePresetChange",
        "setEditingModelId(null)",
        "preset selection clearing model edit state",
    )

    print("model settings are owned by React instead of legacy DOM bridges")


if __name__ == "__main__":
    main()
