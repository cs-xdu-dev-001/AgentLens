import { notifyError, notifyToast } from "./errorFeedback.js";
import { useCallback, useEffect, useMemo, useState } from "react";
import { modelConfigApi } from "../api/client.js";
import { providerPresets } from "../data/settings.js";
import { ModelConfigForm } from "./ModelConfigForm.jsx";
import { ModelListPanel } from "./ModelListPanel.jsx";
import { SettingsHeader } from "./SettingsHeader.jsx";
import { SettingsSidePanel } from "./SettingsSidePanel.jsx";

const defaultModelFormValues = {
  name: "DeepSeek V4 Flash",
  provider: "deepseek",
  modelType: "chat",
  apiMode: "chat_completions",
  baseUrl: "https://api.deepseek.com",
  apiKey: "",
  modelName: "deepseek-v4-flash",
  temperature: "0.7",
  topP: "0.9",
  maxTokens: "4096",
};


function normalizeProvider(provider) {
  return providerPresets[provider] ? provider : "custom";
}

function valueForInput(value) {
  return value === null || value === undefined ? "" : String(value);
}

function formValuesFromPreset(provider, presetIndex = 0) {
  const key = normalizeProvider(provider);
  const preset = Number.isInteger(presetIndex) ? providerPresets[key]?.models?.[presetIndex] : null;
  if (!preset) {
    return {
      ...defaultModelFormValues,
      name: "自定义模型",
      provider: key === "custom" ? "" : key,
      baseUrl: providerPresets[key]?.baseUrl || "",
      modelName: "",
      temperature: "0.7",
      topP: "0.9",
      maxTokens: "4096",
    };
  }
  return {
    name: preset.name,
    provider: key,
    modelType: preset.modelType,
    apiMode: preset.apiMode || "chat_completions",
    baseUrl: providerPresets[key].baseUrl,
    apiKey: "",
    modelName: preset.modelName,
    temperature: valueForInput(preset.temperature),
    topP: valueForInput(preset.topP),
    maxTokens: valueForInput(preset.maxTokens),
  };
}

function formValuesFromModel(model) {
  return {
    name: valueForInput(model.name),
    provider: valueForInput(model.provider),
    modelType: valueForInput(model.modelType || "chat"),
    apiMode: valueForInput(model.apiMode || "chat_completions"),
    baseUrl: valueForInput(model.baseUrl),
    apiKey: "",
    modelName: valueForInput(model.modelName),
    temperature: valueForInput(model.temperature),
    topP: valueForInput(model.topP),
    maxTokens: valueForInput(model.maxTokens),
  };
}

function numberOrNull(value, parser = Number) {
  if (value === "" || value === null || value === undefined) return null;
  const parsed = parser(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function payloadFromFormValues(formValues) {
  const payload = {
    name: formValues.name.trim(),
    provider: formValues.provider.trim(),
    modelType: formValues.modelType,
    apiMode: formValues.modelType === "chat" && formValues.apiMode === "responses" ? "responses" : "chat_completions",
    baseUrl: formValues.baseUrl.trim(),
    modelName: formValues.modelName.trim(),
    temperature: numberOrNull(formValues.temperature),
    topP: numberOrNull(formValues.topP),
    maxTokens: numberOrNull(formValues.maxTokens, (value) => Number.parseInt(value, 10)),
  };
  if (formValues.apiKey.trim()) payload.apiKey = formValues.apiKey.trim();
  return payload;
}

function requestModelOptionsRefresh() {
  window.dispatchEvent(new CustomEvent("knowflow:react-models-refresh-request"));
}

export function SettingsPage({ active = false }) {
  const [busyModelId, setBusyModelId] = useState(null);
  const [editingModelId, setEditingModelId] = useState(null);
  const [formValues, setFormValues] = useState(defaultModelFormValues);
  const [models, setModels] = useState([]);
  const [selectedPresetValue, setSelectedPresetValue] = useState("deepseek:0");
  const [selectedProvider, setSelectedProvider] = useState("deepseek");
  const [submitting, setSubmitting] = useState(false);

  const loadModels = useCallback(async () => {
    try {
      const nextModels = await modelConfigApi.list();
      setModels(Array.isArray(nextModels) ? nextModels : []);
    } catch (error) {
      notifyError(error, "加载模型配置失败");
    }
  }, []);

  useEffect(() => {
    loadModels();
  }, [loadModels]);

  const normalizedProvider = useMemo(() => normalizeProvider(selectedProvider), [selectedProvider]);

  const resetModelForm = () => {
    setEditingModelId(null);
    setSelectedProvider("deepseek");
    setSelectedPresetValue("deepseek:0");
    setFormValues(formValuesFromPreset("deepseek", 0));
  };

  const handleFieldChange = (event) => {
    const { name, value } = event.target;
    setFormValues((currentValues) => ({ ...currentValues, [name]: value, ...(name === "modelType" && value !== "chat" ? { apiMode: "chat_completions" } : {}) }));
    if (name === "provider") {
      setSelectedProvider(normalizeProvider(value.trim()));
      setSelectedPresetValue("");
    }
  };

  const handleProviderSelect = (provider) => {
    const key = normalizeProvider(provider);
    setSelectedProvider(key);
    const firstPreset = providerPresets[key]?.models?.[0];
    setSelectedPresetValue(firstPreset ? `${key}:0` : "");
    setFormValues(formValuesFromPreset(key, firstPreset ? 0 : null));
  };

  const handlePresetChange = (event) => {
    const value = event.target.value || "";
    setSelectedPresetValue(value);
    if (!value) return;
    const [provider, indexText] = value.split(":");
    const index = Number.parseInt(indexText, 10);
    setSelectedProvider(normalizeProvider(provider));
    setFormValues(formValuesFromPreset(provider, index));
  };

  const handleModelSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const payload = payloadFromFormValues(formValues);
      if (editingModelId) {
        await modelConfigApi.update(editingModelId, payload);
        notifyToast("模型配置已更新");
      } else {
        await modelConfigApi.create(payload);
        notifyToast("模型配置已保存");
      }
      resetModelForm();
      await loadModels();
      requestModelOptionsRefresh();
    } catch (error) {
      notifyError(error, "保存失败");
    } finally {
      setSubmitting(false);
    }
  };

  const handleModelEdit = async (modelId) => {
    setBusyModelId(modelId);
    try {
      const model = await modelConfigApi.get(modelId);
      setEditingModelId(modelId);
      setSelectedProvider(normalizeProvider(model.provider));
      setSelectedPresetValue("");
      setFormValues(formValuesFromModel(model));
      window.dispatchEvent(new CustomEvent("knowflow:react-page-change", { detail: { page: "settings" } }));
    } catch (error) {
      notifyError(error, "加载模型配置失败");
    } finally {
      setBusyModelId(null);
    }
  };

  const handleModelTest = async (modelId) => {
    setBusyModelId(modelId);
    try {
      const result = await modelConfigApi.test(modelId);
      notifyToast(result?.message || "模型连接检查完成");
      await loadModels();
      requestModelOptionsRefresh();
    } catch (error) {
      notifyError(error, "检查模型失败");
    } finally {
      setBusyModelId(null);
    }
  };

  const handleSetDefaultModel = async (modelId) => {
    setBusyModelId(modelId);
    try {
      await modelConfigApi.setDefault(modelId);
      notifyToast("默认模型已更新");
      await loadModels();
      requestModelOptionsRefresh();
    } catch (error) {
      notifyError(error, "设置默认模型失败");
    } finally {
      setBusyModelId(null);
    }
  };

  const handleDeleteModel = async (modelId) => {
    setBusyModelId(modelId);
    try {
      await modelConfigApi.delete(modelId);
      notifyToast("模型配置已删除");
      if (String(editingModelId || "") === String(modelId)) resetModelForm();
      await loadModels();
      requestModelOptionsRefresh();
    } catch (error) {
      notifyError(error, "删除模型失败");
    } finally {
      setBusyModelId(null);
    }
  };

  return (
    <section className={active ? "page active" : "page"} id={"page-settings"}>
      <div className={"workspace-page"}>
        <SettingsHeader />
        <div className={"settings-grid"}>
          <section className={"settings-main"}>
            <ModelConfigForm
              editingModelId={editingModelId}
              formValues={formValues}
              selectedProvider={normalizedProvider}
              selectedPresetValue={selectedPresetValue}
              submitting={submitting}
              onCancel={resetModelForm}
              onFieldChange={handleFieldChange}
              onPresetChange={handlePresetChange}
              onProviderSelect={handleProviderSelect}
              onSubmit={handleModelSubmit}
            />
            <ModelListPanel
              busyModelId={busyModelId}
              models={models}
              onDeleteModel={handleDeleteModel}
              onModelEdit={handleModelEdit}
              onModelTest={handleModelTest}
              onSetDefaultModel={handleSetDefaultModel}
            />
          </section>
          <SettingsSidePanel />
        </div>
      </div>
    </section>
  );
}
