import { useState } from "react";
import { memoryApi } from "../api/client.js";
import { publishMemoryActivity } from "../controller/memoryActivity.js";
import { notifyError, notifyToast } from "./errorFeedback.js";
import {
  normalizeTraceStatus,
  safeText,
  traceCopyText,
  traceMemoryItems,
  traceStepFields,
  traceStepReason,
  traceStepTarget,
} from "./agentTracePresentation.js";


const memoryActionLabels = {
  recall: "参考",
  add: "新增",
  update: "更新",
  delete: "删除",
};

const targetLabels = {
  memory: "管理长期记忆",
  skills: "查看Skill",
  tools: "查看工具",
};

export function AgentTraceStepDetail({
  id,
  step,
  messageId = "",
  run = null,
}) {
  const [copying, setCopying] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const fields = traceStepFields(step);
  const memoryItems = traceMemoryItems(step);
  const target = traceStepTarget(step);
  const failed = normalizeTraceStatus(step?.status) === "failed";
  const operationId = safeText(step?.details?.operationId);
  const canRetryMemory = failed && step?.name === "memory_write" && operationId;
  const canOpenRecovery = failed && step?.name !== "memory_write" && run?.id;

  const copyDetails = async () => {
    if (copying) return;
    setCopying(true);
    try {
      await navigator.clipboard.writeText(traceCopyText(step));
      notifyToast("已复制步骤详情");
    } catch (error) {
      notifyError(error, "复制失败，请重试。");
    } finally {
      setCopying(false);
    }
  };

  const openTarget = () => {
    if (!target) return;
    window.dispatchEvent(
      new CustomEvent(
        "knowflow:react-page-activated",
        { detail: { page: target } },
      ),
    );
  };

  const retryStep = async () => {
    if (!canRetryMemory || retrying) return;
    setRetrying(true);
    try {
      const nextActivity = await memoryApi.retryOperation(
        operationId,
      );
      publishMemoryActivity(messageId, nextActivity);
      notifyToast("已重新整理长期记忆");
    } catch (error) {
      notifyError(error, "重试失败，请稍后再试。");
    } finally {
      setRetrying(false);
    }
  };

  const openRecovery = () => {
    if (!canOpenRecovery) return;
    window.dispatchEvent(
      new CustomEvent("knowflow:react-agent-recovery-focus", {
        detail: {
          messageId,
          runId: run.id,
        },
      }),
    );
  };

  return (
    <section
      className={"agent-trace-step-detail"}
      id={id}
      aria-label={"步骤详情"}
    >
      <div className={"agent-trace-reason"}>
        <span>{"为什么执行"}</span>
        <p>{traceStepReason(step)}</p>
      </div>
      {fields.length ? (
        <dl className={"agent-trace-fields"}>
          {fields.map((field) => (
            <div key={`${field.label}-${field.value}`}>
              <dt>{field.label}</dt>
              <dd>{field.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {step?.kind === "memory" ? (
        <div className={"agent-trace-memory-items"}>
          <span>{"记忆内容"}</span>
          {memoryItems.length ? (
            <ul>
              {memoryItems.map((item, index) => (
                <li key={`${item.action}-${index}`}>
                  <span>
                    {memoryActionLabels[item.action] || "记录"}
                  </span>
                  <p>{item.content}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p>{"没有产生长期记忆变更。"}</p>
          )}
        </div>
      ) : null}
      <div className={"agent-trace-detail-actions"}>
        <button
          type={"button"}
          disabled={copying}
          onClick={copyDetails}
        >
          {copying ? "复制中…" : "复制详情"}
        </button>
        {target ? (
          <button type={"button"} onClick={openTarget}>
            {targetLabels[target]}
          </button>
        ) : null}
        {canRetryMemory ? (
          <button
            className={"primary"}
            type={"button"}
            disabled={retrying}
            onClick={retryStep}
          >
            {retrying ? "重试中…" : "重试记忆整理"}
          </button>
        ) : null}
        {canOpenRecovery ? (
          <button className={"primary"} type={"button"} onClick={openRecovery}>
            {"查看恢复操作"}
          </button>
        ) : null}
      </div>
    </section>
  );
}
