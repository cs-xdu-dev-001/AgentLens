const modelTypeLabel = { chat: "聊天模型", embedding: "向量模型", rerank: "重排模型" };
const statusText = { available: "可用", unavailable: "不可用", untested: "待检查" };
const providerNames = { deepseek: "DeepSeek", mimo: "MiMo", openai: "OpenAI", siliconflow: "SiliconFlow", zhipu: "智谱 AI", bailian: "百炼", custom: "自定义" };
const apiModeLabel = { chat_completions: "Chat Completions", responses: "Responses API" };

export function ModelListPanel({ models = [], busyModelId = null, onModelEdit, onModelTest, onSetDefaultModel, onDeleteModel }) {
  return (
    <section className={"panel model-list-panel"}>
      <div className={"panel-title"}>
        <h2>{"模型列表"}</h2>
      </div>
      <div className={"model-list"} id={"model-list"}>
        {models.length ? (
          models.map((model) => {
            const status = model.status || "untested";
            const provider = providerNames[model.provider] || model.provider || "自定义";
            return (
              <article className={"model-row"} key={model.id}>
                <div>
                  <h3>{model.name}</h3>
                  <p>{provider + " / " + (model.modelName || "未知")}</p>
                  <small>{modelTypeLabel[model.modelType] || model.modelType || "模型"}{model.modelType === "chat" ? " · " + (apiModeLabel[model.apiMode] || apiModeLabel.chat_completions) : ""}</small>
                </div>
                <div className={"model-row-meta"}>
                  <span className={status === "available" ? "badge ok" : status === "unavailable" ? "badge warn" : "badge"}>{statusText[status] || status}</span>
                  <span>{"密钥 "}{model.apiKeyMasked || "未配置"}</span>
                  {model.isDefault ? <span className={"badge ok"}>{"默认"}</span> : null}
                </div>
                <div className={"model-row-actions"}>
                  <button type={"button"} disabled={busyModelId === model.id} onClick={() => onModelEdit(model.id)}>{"编辑"}</button>
                  <button type={"button"} disabled={busyModelId === model.id} onClick={() => onModelTest(model.id)}>{"检查"}</button>
                  <button type={"button"} disabled={busyModelId === model.id || model.isDefault} onClick={() => onSetDefaultModel(model.id)}>{"设为默认"}</button>
                  <button className={"danger"} type={"button"} disabled={busyModelId === model.id} onClick={() => onDeleteModel(model.id)}>{"删除"}</button>
                </div>
              </article>
            );
          })
        ) : (
          <p className={"empty-state"}>{"暂无配置"}</p>
        )}
      </div>
    </section>
  );
}
