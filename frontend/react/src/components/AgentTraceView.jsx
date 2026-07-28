import { useMemo, useState } from "react";


const kindLabels = {
  model: "MODEL",
  tool: "TOOL",
  mcp: "MCP",
  skill: "SKILL",
  agent: "AGENT",
  system: "SYS",
  approval: "APPROVAL",
};

const nameLabels = {
  agent_run: "Agent",
  model_completion: "模型",
  web_search: "联网搜索",
};

const statusLabels = {
  waiting: "等待中",
  running: "运行中",
  success: "已完成",
  completed: "已完成",
  failed: "失败",
  error: "失败",
  cancelled: "已取消",
};

const skillSourceLabels = {
  builtin: "内置",
  personal: "个人",
  github: "个人",
  upload: "个人",
};

function skillDisplayName(step) {
  const value = step?.details?.displayName;
  return typeof value === "string" && value.trim()
    ? value.trim()
    : "Skill";
}

function safeDependencyNames(value) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => typeof item === "string")
    .map((item) => item.trim())
    .filter(Boolean);
}

function skillDetailsForDisplay(step) {
  const details = (
    step?.details
    && typeof step.details === "object"
    && !Array.isArray(step.details)
  )
    ? step.details
    : {};
  const version = (
    typeof details.version === "string"
    && details.version.trim()
  )
    ? details.version.trim()
    : "无";
  const sourceKind = typeof details.sourceKind === "string"
    ? skillSourceLabels[details.sourceKind]
    : null;
  return {
    displayName: skillDisplayName(step),
    version,
    sourceKind: sourceKind || "个人",
    requiredTools: safeDependencyNames(details.requiredTools),
    requiredMcp: safeDependencyNames(details.requiredMcp),
  };
}

function traceStatusClass(status) {
  if (status === "completed") return "success";
  if (status === "error") return "failed";
  return status;
}

function displayName(step) {
  return (
    nameLabels[step?.name]
    || String(step?.name || step?.kind || "步骤").replaceAll("_", " ")
  );
}

export function traceStepTitle(step) {
  if (!step) return "";
  if (step.title === "连接中断") return step.title;
  if (step.kind === "skill") {
    if (step.status === "running") {
      return `正在激活 ${skillDisplayName(step)}`;
    }
    if (step.status === "success" || step.status === "completed") {
      return `已激活 ${skillDisplayName(step)}`;
    }
    return "Skill 激活失败";
  }
  if (step.kind === "approval") {
    if (step.status === "waiting") return "等待工具确认";
    if (step.status === "success") return "已允许工具执行";
    if (step.status === "cancelled") return "工具确认已取消";
    return step.outputSummary?.decision === "timeout"
      ? "工具确认已超时"
      : "已拒绝工具执行";
  }
  if (step.name === "agent_run") {
    if (step.status === "running") return "Agent正在处理";
    if (step.status === "success") return "Agent处理完成";
    return "Agent处理失败";
  }
  if (step.name === "model_completion") {
    if (step.status === "running") return "模型正在分析";
    if (step.status === "success") return "模型步骤完成";
    return "模型调用失败";
  }
  if (step.name === "web_search") {
    if (step.status === "running") return "正在联网搜索";
    if (step.status === "success") return "联网搜索完成";
    return "联网搜索失败";
  }
  return `${displayName(step)}${statusLabels[step.status] || ""}`;
}

function stepDepth(step, byId) {
  let depth = 0;
  let parent = step.parentId
    ? byId.get(step.parentId)
    : null;
  const visited = new Set();
  while (
    parent
    && !visited.has(parent.stepId)
    && depth < 6
  ) {
    visited.add(parent.stepId);
    depth += 1;
    parent = parent.parentId
      ? byId.get(parent.parentId)
      : null;
  }
  return depth;
}

function summaryText(value, fallback) {
  if (value == null || value === "") return fallback;
  if (typeof value === "string") return value.trim() || fallback;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function traceDetailsForDisplay(step) {
  if (step?.kind === "skill") {
    return {
      skillDetails: skillDetailsForDisplay(step),
      inputSummary: null,
      outputSummary: null,
      errorCode: null,
    };
  }
  return {
    skillDetails: null,
    inputSummary: summaryText(step?.inputSummary, "无"),
    outputSummary: summaryText(
      step?.outputSummary,
      step?.status === "running" ? "执行中" : "无",
    ),
    errorCode: step?.errorCode || null,
  };
}

function mcpServerName(step) {
  const serverName = step?.details?.serverName || step?.serverName;
  if (serverName) return String(serverName);
  const parts = String(step?.name || "").split("__");
  return parts.length >= 3 && parts[0] === "mcp"
    ? parts[1]
    : "MCP";
}

export function AgentTraceView({ trace = [] }) {
  const [selectedId, setSelectedId] = useState("");
  const rows = useMemo(() => {
    const safeTrace = Array.isArray(trace) ? trace : [];
    const byId = new Map(
      safeTrace.map((step) => [step.stepId, step]),
    );
    return safeTrace.map((step) => ({
      ...step,
      depth: stepDepth(step, byId),
    }));
  }, [trace]);
  const selected = (
    rows.find((step) => step.stepId === selectedId)
    || [...rows].reverse().find(
      (step) =>
        step.status === "waiting" &&
        step.kind === "approval",
    )
    || [...rows].reverse().find((step) => step.status === "running")
    || rows[rows.length - 1]
  );
  const currentStepId = (
    [...rows].reverse().find(
      (step) =>
        step.status === "waiting" &&
        step.kind === "approval",
    )
    || [...rows].reverse().find(
      (step) => step.status === "running",
    )
  )?.stepId;
  const selectedDetails = selected
    ? traceDetailsForDisplay(selected)
    : null;

  if (!rows.length) {
    return (
      <p className={"empty-state"}>
        {"本次回答没有Agent运行记录。"}
      </p>
    );
  }

  return (
    <div className={"agent-trace-view"}>
      <div
        className={"agent-trace-tree"}
        role={"list"}
        aria-label={"Agent运行步骤"}
      >
        {rows.map((step) => (
          <div
            className={"agent-trace-row"}
            style={{ "--trace-depth": step.depth }}
            role={"listitem"}
            key={step.stepId}
          >
            <button
              className={[
                "agent-trace-node",
                traceStatusClass(step.status),
                selected?.stepId === step.stepId
                  ? "selected"
                  : "",
              ].filter(Boolean).join(" ")}
              type={"button"}
              aria-current={
                step.stepId === currentStepId
                  ? "step"
                  : undefined
              }
              onClick={() => setSelectedId(step.stepId)}
            >
              <span
                className={"agent-trace-node-dot"}
                aria-hidden={"true"}
              ></span>
              <span className={`agent-trace-kind ${step.kind}`}>
                {kindLabels[step.kind] || step.kind}
              </span>
              <span className={"agent-trace-node-copy"}>
                <strong>{traceStepTitle(step)}</strong>
                <small>
                  {displayName(step)}
                  {" · "}
                  {statusLabels[step.status] || step.status}
                </small>
              </span>
              <span className={"agent-trace-node-time"}>
                {step.durationMs != null
                  ? `${step.durationMs}ms`
                  : "…"}
              </span>
            </button>
          </div>
        ))}
      </div>
      {selected ? (
        <section
          className={"agent-trace-detail"}
          aria-label={"步骤详情"}
        >
          {selectedDetails.skillDetails ? (
            <div className={"agent-trace-context"}>
              <span>{"Skill"}</span>
              <code>{selectedDetails.skillDetails.displayName}</code>
              <span>{"版本"}</span>
              <code>{selectedDetails.skillDetails.version}</code>
              <span>{"来源"}</span>
              <code>{selectedDetails.skillDetails.sourceKind}</code>
              <span>{"所需工具"}</span>
              <code>
                {selectedDetails.skillDetails.requiredTools.join(", ") || "无"}
              </code>
              <span>{"所需MCP"}</span>
              <code>
                {selectedDetails.skillDetails.requiredMcp.join(", ") || "无"}
              </code>
            </div>
          ) : null}
          {selected.kind === "mcp" || selected.kind === "approval" ? (
            <div className={"agent-trace-context"}>
              <span>{"服务器"}</span>
              <code>{mcpServerName(selected)}</code>
              <span>{"工具"}</span>
              <code>
                {selected.details?.toolName || displayName(selected)}
              </code>
              {selected.details?.risk ? (
                <>
                  <span>{"风险"}</span>
                  <code>{selected.details.risk}</code>
                </>
              ) : null}
              {selected.outputSummary?.decision ? (
                <>
                  <span>{"决定"}</span>
                  <code>{selected.outputSummary.decision}</code>
                </>
              ) : null}
            </div>
          ) : null}
          {selectedDetails.inputSummary !== null ? (
            <div>
              <span>{"公开输入"}</span>
              <code>{selectedDetails.inputSummary}</code>
            </div>
          ) : null}
          {selectedDetails.outputSummary !== null ? (
            <div>
              <span>{"结果摘要"}</span>
              <code>{selectedDetails.outputSummary}</code>
            </div>
          ) : null}
          {selectedDetails.errorCode ? (
            <div>
              <span>{"错误"}</span>
              <code>{selectedDetails.errorCode}</code>
            </div>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
