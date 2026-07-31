import { useCallback, useEffect, useMemo, useState } from "react";
import { modelConfigApi } from "../api/client.js";
import { providerPresets } from "../data/settings.js";
import { ModelConfigDetails } from "./ModelConfigDetails.jsx";
import { ModelConfigForm } from "./ModelConfigForm.jsx";
import { ModelListPanel } from "./ModelListPanel.jsx";
import { SettingsHeader } from "./SettingsHeader.jsx";
import { notifyError, notifyToast } from "./errorFeedback.js";


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

function normalizeApiMode(value) {
  return value === "responses" ? "responses" : "chat_completions";
}

function valueForInput(value) {
  return value === null || value === undefined ? "" : String(value);
}

function sameId(left, right) {
  return String(left ?? "") === String(right ?? "");
}

function formValuesFromPreset(provider, presetIndex = 0) {
  const key = normalizeProvider(provider);
  const preset = Number.isInteger(presetIndex)
    ? providerPresets[key]?.models?.[presetIndex]
    : null;
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
    apiMode: normalizeApiMode(preset.apiMode),
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
    apiMode: normalizeApiMode(model.apiMode),
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
    apiMode: formValues.modelType === "chat"
      ? normalizeApiMode(formValues.apiMode)
      : "chat_completions",
    baseUrl: formValues.baseUrl.trim(),
    modelName: formValues.modelName.trim(),
    temperature: numberOrNull(formValues.temperature),
    topP: numberOrNull(formValues.topP),
    maxTokens: numberOrNull(
      formValues.maxTokens,
      (value) => Number.parseInt(value, 10),
    ),
  };
  if (formValues.apiKey.trim()) {
    payload.apiKey = formValues.apiKey.trim();
  }
  return payload;
}

function requestModelOptionsRefresh() {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-models-refresh-request"),
  );
}

function preferredModel(models, preferredId, currentId) {
  const preferred = models.find((model) => sameId(model.id, preferredId));
  if (preferred) return preferred;
  const current = models.find((model) => sameId(model.id, currentId));
  if (current) return current;
  return (
    models.find((model) => model.isDefault && model.modelType === "chat")
    || models.find((model) => model.isDefault)
    || models[0]
    || null
  );
}

export function SettingsPage({ active = false }) {
  const [busyModelId, setBusyModelId] = useState(null);
  const [editingModelId, setEditingModelId] = useState(null);
  const [formValues, setFormValues] = useState(defaultModelFormValues);
  const [models, setModels] = useState([]);
  const [selectedModelId, setSelectedModelId] = useState(null);
  const [selectedPresetValue, setSelectedPresetValue] = useState("deepseek:0");
  const [selectedProvider, setSelectedProvider] = useState("deepseek");
  const [submitting, setSubmitting] = useState(false);
  const [panelMode, setPanelMode] = useState("details");

  const loadModels = useCallback(async (preferredId = null) => {
    try {
      const response = await modelConfigApi.list();
      const nextModels = Array.isArray(response) ? response : [];
      setModels(nextModels);
      setSelectedModelId((currentId) => (
        preferredModel(nextModels, preferredId, currentId)?.id ?? null
      ));
      return nextModels;
    } catch (error) {
      notifyError(error, "加载模型配置失败");
      return null;
    }
  }, []);

  useEffect(() => {
    loadModels();
  }, [loadModels]);

  const normalizedProvider = useMemo(
    () => normalizeProvider(selectedProvider),
    [selectedProvider],
  );
  const selectedModel = useMemo(
    () => models.find((model) => sameId(model.id, selectedModelId)) || null,
    [models, selectedModelId],
  );

  const resetModelForm = () => {
    setEditingModelId(null);
    setSelectedProvider("deepseek");
    setSelectedPresetValue("deepseek:0");
    setFormValues(formValuesFromPreset("deepseek", 0));
  };

  const closeModelForm = () => {
    resetModelForm();
    setPanelMode("details");
  };

  const handleCreateModel = () => {
    resetModelForm();
    setPanelMode("form");
  };

  const handleModelSelect = (modelId) => {
    setSelectedModelId(modelId);
    setPanelMode("details");
  };

  const handleFieldChange = (event) => {
    const { name, value } = event.target;
    setFormValues((currentValues) => ({
      ...currentValues,
      [name]: name === "apiMode" ? normalizeApiMode(value) : value,
      ...(name === "modelType" && value !== "chat"
        ? { apiMode: "chat_completions" }
        : {}),
    }));
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
      const savedModel = editingModelId
        ? await modelConfigApi.update(editingModelId, payload)
        : await modelConfigApi.create(payload);
      notifyToast(
        editingModelId
          ? "模型配置已更新"
          : "模型配置已保存",
      );
      const preferredId = savedModel?.id || editingModelId || null;
      await loadModels(preferredId);
      requestModelOptionsRefresh();
      resetModelForm();
      setPanelMode("details");
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
      setSelectedModelId(modelId);
      setEditingModelId(modelId);
      setSelectedProvider(normalizeProvider(model.provider));
      setSelectedPresetValue("");
      setFormValues(formValuesFromModel(model));
      setPanelMode("form");
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
      await loadModels(modelId);
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
      await loadModels(modelId);
      requestModelOptionsRefresh();
    } catch (error) {
      notifyError(error, "设置默认模型失败");
    } finally {
      setBusyModelId(null);
    }
  };

  const handleDeleteModel = async (modelId) => {
    const targetModel = models.find((model) => sameId(model.id, modelId));
    const targetName = targetModel?.name || targetModel?.modelName || "该模型";
    if (!window.confirm(`删除“${targetName}”配置？此操作无法撤销。`)) {
      return;
    }
    setBusyModelId(modelId);
    try {
      await modelConfigApi.delete(modelId);
      notifyToast("模型配置已删除");
      if (sameId(editingModelId, modelId)) resetModelForm();
      await loadModels();
      setPanelMode("details");
      requestModelOptionsRefresh();
    } catch (error) {
      notifyError(error, "删除模型失败");
    } finally {
      setBusyModelId(null);
    }
  };

  return (
    <section className={active ? "page active" : "page"} id={"page-settings"}>
      <div className={"workspace-page settings-workspace"}>
        <SettingsHeader
          disabled={submitting}
          onCreate={handleCreateModel}
        />
        <div className={"settings-workspace-shell"}>
          <ModelListPanel
            busyModelId={busyModelId}
            models={models}
            selectedModelId={selectedModelId}
            onModelSelect={handleModelSelect}
          />
          <section className={"settings-workspace-detail"} aria-label={"配置工作区"}>
            {panelMode === "form" ? (
              <ModelConfigForm
                editingModelId={editingModelId}
                formValues={formValues}
                selectedProvider={normalizedProvider}
                selectedPresetValue={selectedPresetValue}
                submitting={submitting}
                onCancel={closeModelForm}
                onFieldChange={handleFieldChange}
                onPresetChange={handlePresetChange}
                onProviderSelect={handleProviderSelect}
                onSubmit={handleModelSubmit}
              />
            ) : (
              <ModelConfigDetails
                busy={sameId(busyModelId, selectedModelId)}
                model={selectedModel}
                onDeleteModel={handleDeleteModel}
                onModelEdit={handleModelEdit}
                onModelTest={handleModelTest}
                onSetDefaultModel={handleSetDefaultModel}
              />
            )}
          </section>
        </div>
      </div>
    </section>
  );
}
