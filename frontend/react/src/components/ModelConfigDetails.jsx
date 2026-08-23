import { useState } from "react";
import { connectionResultStatus } from "./modelConnectionState.js";

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
  connectionResult = null,
  onDeleteModel,
  onModelEdit,
  onModelTest,
  onSetDefaultModel,
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  if (!model) {
    return (
      <div className={"settings-detail-empty"}>
        <strong>{"选择一个模型配置"}</strong>
        <span>{"连接状态和配置详情会显示在这里。"}</span>
      </div>
    );
  }

  const status = model.status || "untested";
  const connectionStatus = connectionResultStatus(connectionResult);
  const protocol = model.modelType === "chat"
    ? apiModeLabel[model.apiMode] || apiModeLabel.chat_completions
    : "不适用";

  return (
    <section className={"model-config-details"} aria-label={"模型详情"}>
      <div className={"model-config-detail-header"}>
        <div className={"model-config-heading"}>
          <div className={"model-config-heading-state"}>
            <span className={`model-config-status ${status}`}>
              {statusText[status] || status}
            </span>
            {model.isDefault ? <span className={"model-config-default"}>{"默认"}</span> : null}
          </div>
          <h2>{model.name || model.modelName || "未命名配置"}</h2>
          <p>{model.modelName || "未设置模型名称"}</p>
        </div>
        <div className={"model-config-capabilities"} aria-label={"模型能力"}>
          <span>{modelTypeLabel[model.modelType] || model.modelType || "模型"}</span>
          {model.modelType === "chat" ? <span>{protocol}</span> : null}
        </div>
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
          value={model.apiKeyMasked ? "已配置" : "未配置"}
        />
      </dl>

      {connectionResult ? (
        <div className={"model-config-connection-result"} data-status={connectionStatus} role={connectionStatus === "error" ? "alert" : "status"}>
          <span className={"model-config-connection-dot"} aria-hidden={"true"} />
          <div>
            <strong>
              {connectionStatus === "checking"
                ? "正在检查连接"
                : connectionStatus === "success"
                  ? "连接可用"
                  : "连接失败"}
              {Number.isFinite(connectionResult.latencyMs) ? ` · ${connectionResult.latencyMs}ms` : ""}
            </strong>
            <span>{connectionResult.message}</span>
          </div>
        </div>
      ) : null}

      <div className={"model-config-detail-actions"}>
        <button
          className={"model-config-test-button"}
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
        {!model.isDefault ? (
          <button
            className={"secondary-button"}
            type={"button"}
            disabled={busy}
            onClick={() => onSetDefaultModel?.(model.id)}
          >
            {"设为默认"}
          </button>
        ) : null}
        <div
          className={menuOpen ? "model-config-more-menu is-open" : "model-config-more-menu"}
          onBlur={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget)) setMenuOpen(false);
          }}
        >
          <button
            className={"model-config-more-trigger"}
            type={"button"}
            aria-expanded={menuOpen}
            aria-haspopup={"menu"}
            aria-label={"更多模型操作"}
            title={"更多操作"}
            onClick={() => setMenuOpen((current) => !current)}
          >
            <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
              <circle cx={"5"} cy={"12"} r={"1.5"} />
              <circle cx={"12"} cy={"12"} r={"1.5"} />
              <circle cx={"19"} cy={"12"} r={"1.5"} />
            </svg>
          </button>
          {menuOpen ? <div className={"model-config-more-popover"} role={"menu"}>
            <button
              className={"danger"}
              type={"button"}
              role={"menuitem"}
              disabled={busy}
              onClick={() => {
                setMenuOpen(false);
                onDeleteModel?.(model.id);
              }}
            >
              {"删除配置"}
            </button>
          </div> : null}
        </div>
      </div>
    </section>
  );
}
