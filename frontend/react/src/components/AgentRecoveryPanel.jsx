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

function dispatchRunAction(run, messageId) {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-agent-run-action", {
      detail: {
        action: "resume",
        messageId,
        runId: run.id,
      },
    }),
  );
}

function dispatchFullRetry(run, messageId) {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-agent-run-action", {
      detail: {
        action: "restart",
        messageId,
        runId: run.id,
      },
    }),
  );
}

function openTarget(target) {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-page-activated", {
      detail: { page: target },
    }),
  );
}

export function AgentRecoveryPanel({ messageId = "", run = null }) {
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

  return (
    <section
      className={`agent-recovery-panel ${failure.retryable ? "retryable" : "needs-config"}`}
      aria-label={"运行恢复"}
      role={"status"}
    >
      <div className={"agent-recovery-heading"}>
        <span className={"agent-recovery-signal"} aria-hidden={"true"}></span>
        <div>
          <strong>{copy.title}</strong>
          <p>{copy.summary}</p>
        </div>
      </div>
      <div className={"agent-recovery-meta"}>
        <code className={"agent-recovery-code"}>{failure.code}</code>
        {failedStep ? (
          <span>
            {failedStep.title}
            {attemptCount ? ` · 已尝试${attemptCount}次` : ""}
          </span>
        ) : null}
      </div>
      <div className={"agent-recovery-actions"}>
        {target ? (
          <button
            className={!failure.retryable ? "primary" : ""}
            type={"button"}
            onClick={() => openTarget(target)}
          >
            {targetLabels[target] || "检查配置"}
          </button>
        ) : null}
        {canResume ? (
          <button
            className={!target ? "primary" : ""}
            type={"button"}
            onClick={() => dispatchRunAction(run, messageId)}
          >
            {"从失败步骤继续"}
          </button>
        ) : null}
        {messageId ? (
          <button
            type={"button"}
            onClick={() => dispatchFullRetry(run, messageId)}
          >
            {"重新运行本轮"}
          </button>
        ) : null}
      </div>
    </section>
  );
}
