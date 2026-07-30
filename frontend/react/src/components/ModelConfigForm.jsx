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
    <form className={"panel stack-form"} id={"model-form"} onSubmit={onSubmit}>
      <div className={"panel-title"}>
        <h2 id={"model-form-title"}>{editingModelId ? "编辑模型配置" : "新建模型配置"}</h2>
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
        <label>
          {"提供商标识"}
          <input name={"provider"} id={"model-provider"} value={formValues.provider} placeholder={"openai, newapi, oneapi, siliconflow"} required onChange={onFieldChange} />
        </label>
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
          {"API 密钥"}
          <input name={"apiKey"} value={formValues.apiKey} type={"password"} placeholder={"sk-xxx"} onChange={onFieldChange} />
        </label>
        <label>
          {"温度"}
          <input name={"temperature"} type={"number"} step={"0.1"} value={formValues.temperature} onChange={onFieldChange} />
        </label>
        <label>
          {"Top P"}
          <input name={"topP"} type={"number"} step={"0.1"} value={formValues.topP} onChange={onFieldChange} />
        </label>
        <label>
          {"最大 token 数"}
          <input name={"maxTokens"} type={"number"} value={formValues.maxTokens} onChange={onFieldChange} />
        </label>
      </div>
      <div className={"button-row"}>
        <button type={"submit"} id={"model-submit-btn"} disabled={submitting}>
          {submitting ? "正在保存..." : editingModelId ? "更新配置" : "保存配置"}
        </button>
        {editingModelId ? (
          <button className={"secondary-button"} type={"button"} id={"model-cancel-btn"} onClick={onCancel} disabled={submitting}>
            {"取消编辑"}
          </button>
        ) : null}
      </div>
    </form>
  );
}
