import { providerPresets } from "../data/settings.js";
import { ModelProviderSelector } from "./ModelProviderSelector.jsx";

export function ModelConfigForm({
  editingModelId,
  formValues,
  selectedProvider,
  selectedPresetValue,
  submitting = false,
  onCancel,
  onFieldChange,
  onPresetChange,
  onProviderSelect,
  onSubmit,
}) {
  const providerKey = providerPresets[selectedProvider] ? selectedProvider : "custom";
  const presets = providerPresets[providerKey]?.models || [];

  return (
    <form className={"model-config-form"} id={"model-form"} onSubmit={onSubmit}>
      <div className={"model-config-form-header"}>
        <h2 id={"model-form-title"}>{editingModelId ? "编辑模型配置" : "新建模型配置"}</h2>
        <button
          className={"icon-button"}
          type={"button"}
          aria-label={"关闭配置表单"}
          disabled={submitting}
          onClick={onCancel}
        >
          <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
            <path d={"M6 6l12 12M18 6 6 18"} />
          </svg>
        </button>
      </div>

      <ModelProviderSelector selectedProvider={providerKey} onProviderSelect={onProviderSelect} />

      <div className={"form-grid"}>
        <label>
          {"配置名称"}
          <input name={"name"} value={formValues.name} required onChange={onFieldChange} />
        </label>
        <label>
          {"预设模型"}
          <select id={"model-preset-select"} value={selectedPresetValue} disabled={!presets.length} onChange={onPresetChange}>
            <option value={""}>{"手动输入模型名称"}</option>
            {presets.map((preset, index) => (
              <option key={providerKey + ":" + index} value={providerKey + ":" + index}>
                {preset.label}
              </option>
            ))}
          </select>
        </label>
        {providerKey === "custom" ? (
          <label>
            {"提供商标识"}
            <input name={"provider"} id={"model-provider"} value={formValues.provider} placeholder={"例如 newapi"} required onChange={onFieldChange} />
          </label>
        ) : null}
        <label>
          {"模型类型"}
          <select name={"modelType"} value={formValues.modelType} onChange={onFieldChange}>
            <option value={"chat"}>{"聊天模型"}</option>
            <option value={"embedding"}>{"向量模型"}</option>
            <option value={"rerank"}>{"重排模型"}</option>
          </select>
        </label>
        {formValues.modelType === "chat" ? (
          <label>
            {"接口协议"}
            <select name={"apiMode"} value={formValues.apiMode || "chat_completions"} onChange={onFieldChange}>
              <option value={"chat_completions"}>{"Chat Completions"}</option>
              <option value={"responses"}>{"Responses API"}</option>
            </select>
          </label>
        ) : null}
        <label>
          {"模型名称"}
          <input name={"modelName"} value={formValues.modelName} required onChange={onFieldChange} />
        </label>
        <label className={"wide"}>
          {"接口地址"}
          <input name={"baseUrl"} value={formValues.baseUrl} required onChange={onFieldChange} />
        </label>
        <label className={"wide"}>
          {"API密钥"}
          <input
            name={"apiKey"}
            value={formValues.apiKey}
            type={"password"}
            autoComplete={"new-password"}
            placeholder={editingModelId ? "留空则沿用现有密钥" : "输入API密钥"}
            onChange={onFieldChange}
          />
        </label>
      </div>
      <div className={"button-row"}>
        <button type={"submit"} id={"model-submit-btn"} disabled={submitting}>
          {submitting ? "正在保存..." : editingModelId ? "更新配置" : "保存配置"}
        </button>
        <button className={"secondary-button"} type={"button"} id={"model-cancel-btn"} onClick={onCancel} disabled={submitting}>
          {"取消"}
        </button>
      </div>
    </form>
  );
}
