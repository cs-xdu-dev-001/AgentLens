import { useEffect, useState } from "react";
import { approvalApi } from "../api/client.js";

const pendingApprovalIds = new Set();
const localApprovalStates = new Map();
const localApprovalCleanupTimers = new Map();

function clearLocalState(approvalId) {
  const timer = localApprovalCleanupTimers.get(approvalId);
  if (timer) window.clearTimeout(timer);
  localApprovalCleanupTimers.delete(approvalId);
  localApprovalStates.delete(approvalId);
  pendingApprovalIds.delete(approvalId);
}

function scheduleLocalStateCleanup(approvalId) {
  const previous = localApprovalCleanupTimers.get(approvalId);
  if (previous) window.clearTimeout(previous);
  const timer = window.setTimeout(() => {
    localApprovalCleanupTimers.delete(approvalId);
    localApprovalStates.delete(approvalId);
    pendingApprovalIds.delete(approvalId);
  }, 10 * 60 * 1000);
  localApprovalCleanupTimers.set(approvalId, timer);
}

function publishLocalState(approvalId, value) {
  localApprovalStates.set(approvalId, value);
  window.dispatchEvent(
    new CustomEvent("knowflow:react-approval-local-state", {
      detail: { approvalId, ...value },
    }),
  );
}

const riskLabels = {
  delete: "删除操作",
  destructive: "高风险操作",
  unknown: "风险未知",
  write: "写入操作",
};

const decisionLabels = {
  allow_once: "已允许本次",
  cancelled: "运行已取消",
  deny: "已拒绝",
  timeout: "审批已超时",
};

function summaryText(value) {
  if (typeof value === "string") return value.trim() || "无公开参数";
  if (value == null) return "无公开参数";
  try {
    const text = JSON.stringify(value, null, 2);
    return text.length > 1200 ? `${text.slice(0, 1200)}…` : text;
  } catch {
    return String(value);
  }
}

export function AgentApprovalPrompt({
  approval,
  compact = false,
}) {
  const [busy, setBusy] = useState(false);
  const [localDecision, setLocalDecision] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    const approvalId = approval?.approvalId;
    if (!approvalId) return undefined;
    if (approval.decision || approval.status !== "waiting") {
      clearLocalState(approvalId);
      setBusy(false);
      setLocalDecision(approval.decision || "");
      setErrorMessage("");
    } else {
      const shared = localApprovalStates.get(approvalId);
      setBusy(shared?.state === "submitting");
      setLocalDecision(shared?.decision || "");
      setErrorMessage(shared?.error || "");
    }

    const handleLocalState = (event) => {
      if (event.detail?.approvalId !== approvalId) return;
      setBusy(event.detail.state === "submitting");
      setLocalDecision(event.detail.decision || "");
      setErrorMessage(event.detail.error || "");
    };
    window.addEventListener(
      "knowflow:react-approval-local-state",
      handleLocalState,
    );
    return () =>
      window.removeEventListener(
        "knowflow:react-approval-local-state",
        handleLocalState,
      );
  }, [approval?.approvalId, approval?.decision, approval?.status]);

  if (!approval?.approvalId) return null;

  const decision = approval.decision || localDecision;
  const pending = approval.status === "waiting" && !decision;
  const risk = riskLabels[approval.risk] || "需确认操作";

  const handleDecision = async (nextDecision) => {
    if (
      !pending ||
      busy ||
      pendingApprovalIds.has(approval.approvalId)
    ) return;
    pendingApprovalIds.add(approval.approvalId);
    publishLocalState(approval.approvalId, {
      state: "submitting",
      decision: "",
      error: "",
    });
    try {
      const request =
        nextDecision === "allow_once"
          ? approvalApi.resolve(approval.approvalId, "allow_once")
          : approvalApi.resolve(approval.approvalId, "deny");
      const result = await request;
      pendingApprovalIds.delete(approval.approvalId);
      publishLocalState(approval.approvalId, {
        state: "resolved",
        decision: nextDecision,
        error: "",
      });
      scheduleLocalStateCleanup(approval.approvalId);
      if (result?.runId) {
        window.dispatchEvent(
          new CustomEvent("knowflow:react-agent-approval-resume", {
            detail: {
              runId: result.runId,
              resumeStarted: Boolean(result.resumeStarted),
              resumeRequired: Boolean(result.resumeRequired),
            },
          }),
        );
      }
    } catch (error) {
      pendingApprovalIds.delete(approval.approvalId);
      if (error?.status === 404) {
        publishLocalState(approval.approvalId, {
          state: "expired",
          decision: "expired",
          error: "审批已失效",
        });
        scheduleLocalStateCleanup(approval.approvalId);
      } else {
        publishLocalState(approval.approvalId, {
          state: "idle",
          decision: "",
          error: "提交失败，请重试。",
        });
        scheduleLocalStateCleanup(approval.approvalId);
      }
    }
  };

  const resolvedLabel =
    localDecision === "expired"
      ? "审批已失效"
      : decisionLabels[decision] ||
        (approval.status === "cancelled" ? "运行已取消" : "");

  return (
    <section
      className={[
        "agent-approval-prompt",
        compact ? "compact" : "",
        pending ? "waiting" : "resolved",
      ].filter(Boolean).join(" ")}
      aria-label={`${approval.toolName || "工具"}操作确认`}
    >
      <div className={"agent-approval-heading"}>
        <span className={"agent-approval-icon"} aria-hidden={"true"}>
          {"!"}
        </span>
        <div>
          <strong>{pending ? "等待你的确认" : resolvedLabel}</strong>
          <span>
            {approval.serverName || "MCP"}
            {" · "}
            {approval.toolName || "未知工具"}
            {" · "}
            {risk}
          </span>
        </div>
      </div>

      {!compact ? (
        <pre className={"agent-approval-summary"}>
          {summaryText(approval.inputSummary)}
        </pre>
      ) : null}

      {pending ? (
        <div className={"agent-approval-actions"}>
          <button
            className={"primary"}
            type={"button"}
            disabled={busy || !pending}
            onClick={() => handleDecision("allow_once")}
          >
            {busy ? "正在提交..." : "允许本次"}
          </button>
          <button
            type={"button"}
            disabled={busy || !pending}
            onClick={() => handleDecision("deny")}
          >
            {"拒绝"}
          </button>
        </div>
      ) : null}

      {errorMessage ? (
        <div className={"agent-approval-error"} role={"status"}>
          {errorMessage}
        </div>
      ) : null}
    </section>
  );
}
