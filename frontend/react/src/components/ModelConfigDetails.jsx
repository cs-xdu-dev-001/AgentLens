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

function DetailItem({ label, value }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value || "未配置"}</dd>
    </div>
  );
}

export function ModelConfigDetails({
  model,
  busy = false,
  onDeleteModel,
  onModelEdit,
  onModelTest,
  onSetDefaultModel,
}) {
  if (!model) {
    return (
      <div className={"settings-detail-empty"}>
        <strong>{"选择一个模型配置"}</strong>
        <span>{"连接状态和配置详情会显示在这里。"}</span>
      </div>
    );
  }

  const status = model.status || "untested";
  const protocol = model.modelType === "chat"
    ? apiModeLabel[model.apiMode] || apiModeLabel.chat_completions
    : "不适用";

  return (
    <section className={"model-config-details"} aria-label={"模型详情"}>
      <div className={"model-config-detail-header"}>
        <div>
          <span className={`model-config-status ${status}`}>
            {statusText[status] || status}
          </span>
          <h2>{model.name || model.modelName || "未命名配置"}</h2>
          <p>{model.modelName || "未设置模型名称"}</p>
        </div>
        {model.isDefault ? (
          <span className={"model-config-default"}>
            {`${modelTypeLabel[model.modelType] || "模型"}默认`}
          </span>
        ) : null}
      </div>

      <dl className={"model-config-detail-grid"}>
        <DetailItem
          label={"提供商"}
          value={providerNames[model.provider] || model.provider || "自定义"}
        />
        <DetailItem
          label={"模型类型"}
          value={modelTypeLabel[model.modelType] || model.modelType}
        />
        <DetailItem label={"接口协议"} value={protocol} />
        <DetailItem label={"接口地址"} value={model.baseUrl} />
        <DetailItem
          label={"API密钥"}
          value={model.apiKeyMasked || "未配置"}
        />
      </dl>

      <div className={"model-config-detail-actions"}>
        <button
          className={"secondary-button"}
          type={"button"}
          disabled={busy}
          onClick={() => onModelTest?.(model.id)}
        >
          {busy ? "检查中..." : "检查连接"}
        </button>
        <button
          className={"secondary-button"}
          type={"button"}
          disabled={busy}
          onClick={() => onModelEdit?.(model.id)}
        >
          {"编辑"}
        </button>
        <button
          className={"secondary-button"}
          type={"button"}
          disabled={busy || model.isDefault}
          onClick={() => onSetDefaultModel?.(model.id)}
        >
          {model.isDefault ? "已是默认" : "设为默认"}
        </button>
        <button
          className={"secondary-button danger"}
          type={"button"}
          disabled={busy}
          onClick={() => onDeleteModel?.(model.id)}
        >
          {"删除"}
        </button>
      </div>
    </section>
  );
}
