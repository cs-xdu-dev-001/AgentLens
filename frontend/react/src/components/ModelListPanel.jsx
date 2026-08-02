const modelTypeLabel = {
  chat: "聊天模型",
  embedding: "向量模型",
  rerank: "重排模型",
};

const statusText = {
  available: "可用",
  unavailable: "不可用",
  untested: "待检查",
};

const providerNames = {
  deepseek: "DeepSeek",
  mimo: "MiMo",
  openai: "OpenAI",
  siliconflow: "SiliconFlow",
  zhipu: "智谱AI",
  bailian: "百炼",
  custom: "自定义",
};

const apiModeLabel = {
  chat_completions: "Chat Completions",
  responses: "Responses API",
};

function providerMark(provider) {
  const name = providerNames[provider] || provider || "API";
  return name.replace(/[^a-zA-Z0-9]/g, "").slice(0, 2).toUpperCase()
    || "AI";
}

export function ModelListPanel({
  models = [],
  selectedModelId = null,
  busyModelId = null,
  onModelSelect,
}) {
  return (
    <aside className={"model-config-list"} aria-label={"已保存的模型配置"}>
      <div className={"model-config-list-header"}>
        <strong>{"已保存"}</strong>
        <span>{models.length}</span>
      </div>
      <div className={"model-config-list-items"} id={"model-list"} role={"listbox"}>
        {models.length ? (
          models.map((model) => {
            const selected = String(selectedModelId || "") === String(model.id);
            const status = model.status || "untested";
            const modelType = modelTypeLabel[model.modelType] || "模型";
            return (
              <button
                className={selected ? "model-config-item selected" : "model-config-item"}
                type={"button"}
                role={"option"}
                aria-selected={selected}
                disabled={busyModelId === model.id}
                key={model.id}
                onClick={() => onModelSelect?.(model.id)}
              >
                <span className={"model-config-provider-mark"} aria-hidden={"true"}>
                  {providerMark(model.provider)}
                </span>
                <span className={"model-config-item-copy"}>
                  <span className={"model-config-item-title"}>
                    <strong>{model.name || model.modelName || "未命名配置"}</strong>
                    {model.isDefault ? <span className={"model-config-default"}>{"默认"}</span> : null}
                  </span>
                  <span className={"model-config-item-meta"}>
                    {model.modelName || "未设置模型"}
                    {model.modelType === "chat" ? " · " + (apiModeLabel[model.apiMode] || apiModeLabel.chat_completions)
                      : " · " + modelType}
                  </span>
                </span>
                <span className={"model-config-item-state"}>
                  <span className={`model-config-status ${status}`}>
                    {statusText[status] || status}
                  </span>
                </span>
              </button>
            );
          })
        ) : (
          <div className={"settings-list-empty"}>
            <strong>{"暂无配置"}</strong>
          </div>
        )}
      </div>
    </aside>
  );
}
