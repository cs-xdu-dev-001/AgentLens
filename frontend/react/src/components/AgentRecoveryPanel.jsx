import { useEffect, useId, useMemo, useRef, useState } from "react";
import {
  buildAgentRunPresentation,
  compactPublicText,
} from "./agentRunPresentation.js";

const failureLabels = {
  agent_run_cancelled: {
    title: "任务已停止",
    summary: "本轮没有继续执行，可以重新运行。",
  },
  agent_run_failed: {
    title: "任务执行失败",
    summary: "可以从失败位置继续，或重新运行本轮。",
  },
  mcp_authentication_required: {
    title: "MCP授权已失效",
    summary: "重新授权后，再从失败步骤继续。",
  },
  mcp_tool_configuration_invalid: {
    title: "MCP工具配置不可用",
    summary: "检查已启用工具和服务器连接后继续。",
  },
  model_authentication_failed: {
    title: "模型认证失败",
    summary: "检查模型配置中的接口地址和密钥后继续。",
  },
  rate_limited: {
    title: "请求过于频繁",
    summary: "上游服务正在限流，稍后可继续执行。",
  },
  service_restart_interrupted: {
    title: "任务被服务重启中断",
    summary: "运行记录已保存，可以从中断位置继续。",
  },
  upstream_timeout: {
    title: "上游响应超时",
    summary: "已完成步骤不会重做，可以从失败位置继续。",
  },
  web_search_timeout: {
    title: "联网搜索超时",
    summary: "可以重试当前任务，已完成步骤不会重做。",
  },
};

const targetLabels = {
  memory: "管理长期记忆",
  settings: "检查模型配置",
  tools: "重新授权",
};

function latestFailedStep(run) {
  const steps = Array.isArray(run?.steps) ? run.steps : [];
  return [...steps].reverse().find((step) => step.status === "failed") || null;
}

function fallbackFailure(run) {
  const trace = Array.isArray(run?.trace) ? run.trace : [];
  const failedTrace = [...trace].reverse().find(
    (step) => step.status === "failed",
  );
  const code = failedTrace?.errorCode
    || (run?.status === "interrupted"
      ? "service_restart_interrupted"
      : run?.status === "cancelled"
        ? "agent_run_cancelled"
        : "agent_run_failed");
  return {
    code,
    retryable: true,
    summary: "",
    target: null,
  };
}

function dispatchRunAction(run, messageId, action, failure, failedStep) {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-agent-run-action", {
      detail: {
        action,
        failedStepTitle: failedStep?.title || "",
        failureCode: failure?.code || "agent_run_failed",
        messageId,
        runId: run.id,
      },
    }),
  );
}

const actionLabels = {
  continue: "从失败步骤继续",
  retry: "重新运行本轮",
  fix: "让Agent分析错误",
};

const pendingActionLabels = {
  continue: "正在从失败位置继续…",
  retry: "正在重新运行…",
  fix: "正在提交分析任务…",
};

const actionMap = { continue: "resume", retry: "restart", fix: "fix" };
const restartAction = { action: "restart" };

function openTarget(target) {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-page-activated", {
      detail: { page: target },
    }),
  );
}

export function AgentRecoveryPanel({
  compact = false,
  interactive = true,
  messageId = "",
  presentation = null,
  run = null,
  trace = [],
}) {
  const headingId = useId();
  const panelRef = useRef(null);
  const [actionState, setActionState] = useState({
    action: "",
    message: "",
    status: "idle",
  });

  useEffect(() => {
    setActionState({ action: "", message: "", status: "idle" });
  }, [run?.id, run?.status]);

  useEffect(() => {
    function handleActionState(event) {
      const detail = event.detail || {};
      if (
        String(detail.runId || "") !== String(run?.id || "")
        || String(detail.messageId || "") !== String(messageId || "")
      ) return;
      setActionState({
        action: detail.action || "",
        message: detail.message || "",
        status: detail.status || "idle",
      });
    }
    window.addEventListener(
      "knowflow:react-agent-run-action-state",
      handleActionState,
    );
    return () => window.removeEventListener(
      "knowflow:react-agent-run-action-state",
      handleActionState,
    );
  }, [messageId, run?.id]);

  useEffect(() => {
    function handleRecoveryFocus(event) {
      const detail = event.detail || {};
      if (
        compact
        || String(detail.runId || "") !== String(run?.id || "")
        || String(detail.messageId || "") !== String(messageId || "")
      ) return;
      window.requestAnimationFrame(() => {
        const target = panelRef.current?.querySelector("button:not(:disabled)");
        (target || panelRef.current)?.focus();
      });
    }
    window.addEventListener(
      "knowflow:react-agent-recovery-focus",
      handleRecoveryFocus,
    );
    return () => window.removeEventListener(
      "knowflow:react-agent-recovery-focus",
      handleRecoveryFocus,
    );
  }, [compact, messageId, run?.id]);

  const runPresentation = useMemo(() => (
    presentation || buildAgentRunPresentation({ run, trace, now: Date.now() })
  ), [presentation, run, trace]);

  if (!run?.id || !["failed", "interrupted", "cancelled"].includes(run.status)) {
    return null;
  }

  const failure = run.failure || fallbackFailure(run);
  const copy = failureLabels[failure.code] || failureLabels.agent_run_failed;
  const failedStep = latestFailedStep(run);
  const attemptCount = Number(failedStep?.attemptCount || 0);
  const canResume = ["failed", "interrupted"].includes(run.status)
    && Array.isArray(run.steps)
    && run.steps.length > 0;
  const target = failure.target;
  const advertisedActions = Array.isArray(run.recoveryActions)
    ? run.recoveryActions.filter((action) => actionMap[action])
    : [];
  const recoveryActions = failure.retryable === false
    ? []
    : advertisedActions.length
      ? advertisedActions
      : [canResume ? "continue" : null, messageId ? "retry" : null].filter(Boolean);
  const failureReason = compactPublicText(
    failure.message || failure.summary,
    compact ? 180 : 260,
  );
  const actionPending = actionState.status === "pending";
  const recoveryMetrics = [
    runPresentation?.total
      ? { label: "已完成", value: `${runPresentation.completed}/${runPresentation.total}` }
      : null,
    runPresentation?.elapsedMs > 0
      ? { label: "用时", value: runPresentation.elapsed }
      : null,
    runPresentation?.toolCalls > 0
      ? { label: "工具调用", value: `${runPresentation.toolCalls}次` }
      : null,
  ].filter(Boolean);

  function requestRecovery(action) {
    if (!interactive) return;
    setActionState({ action, message: "", status: "pending" });
    dispatchRunAction(
      run,
      messageId,
      action === "retry" ? restartAction.action : actionMap[action],
      failure,
      failedStep,
    );
  }

  function copyDiagnostic() {
    window.dispatchEvent(new CustomEvent("knowflow:react-diagnostic-copy-request"));
  }

  return (
    <section
      className={`agent-recovery-panel ${failure.retryable !== false ? "retryable" : "needs-config"}${compact ? " compact" : ""}`}
      aria-labelledby={headingId}
      aria-busy={actionPending}
      ref={panelRef}
      role={"region"}
      tabIndex={-1}
    >
      <div className={"agent-recovery-heading"}>
        <span className={"agent-recovery-signal"} aria-hidden={"true"}></span>
        <div className={"agent-recovery-copy"}>
          <div className={"agent-recovery-title-row"}>
            <strong id={headingId}>{copy.title}</strong>
            <span className={"agent-recovery-state"}>
              {failure.retryable !== false ? "可恢复" : "需要处理"}
            </span>
          </div>
          <p>{copy.summary}</p>
        </div>
      </div>
      {failureReason ? (
        <p className={"agent-recovery-reason"}>{failureReason}</p>
      ) : null}
      {recoveryMetrics.length ? (
        <dl className={"agent-recovery-metrics"}>
          {recoveryMetrics.map((metric) => (
            <div key={metric.label}>
              <dt>{metric.label}</dt>
              <dd>{metric.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {!compact ? (
        <div className={"agent-recovery-meta"}>
          <code className={"agent-recovery-code"}>{failure.code}</code>
          {failedStep ? (
            <span>
              {failedStep.title}
              {attemptCount ? ` · 已尝试${attemptCount}次` : ""}
            </span>
          ) : null}
        </div>
      ) : null}
      {interactive ? (
      <div className={"agent-recovery-actions"} role={"group"} aria-label={"恢复操作"}>
        <button
          type={"button"}
          onClick={copyDiagnostic}
        >
          复制诊断
        </button>
        {target ? (
          <button
            className={!failure.retryable ? "primary" : ""}
            disabled={actionPending}
            type={"button"}
            onClick={() => openTarget(target)}
          >
            {targetLabels[target] || "检查配置"}
          </button>
        ) : null}
        {recoveryActions.map((action, index) => (
          <button
            className={!target && index === 0 ? "primary" : ""}
            disabled={actionPending || actionState.status === "succeeded"}
            key={action}
            type={"button"}
            onClick={() => requestRecovery(action)}
          >
            {actionPending && actionState.action === action
              ? pendingActionLabels[action]
              : actionLabels[action]}
          </button>
        ))}
      </div>
      ) : (
        <button
          className="agent-recovery-jump"
          type="button"
          onClick={() => window.dispatchEvent(
            new CustomEvent("knowflow:react-agent-interaction-focus"),
          )}
        >
          先处理当前请求
        </button>
      )}
      {actionState.status !== "idle" ? (
        <p
          className={`agent-recovery-feedback ${actionState.status}`}
          role={actionState.status === "failed" ? "alert" : "status"}
          aria-live={"polite"}
        >
          {actionState.status === "pending"
            ? pendingActionLabels[actionState.action]
            : actionState.message}
        </p>
      ) : null}
    </section>
  );
}
