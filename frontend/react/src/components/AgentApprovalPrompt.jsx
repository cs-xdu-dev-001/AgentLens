import { useEffect, useRef, useState } from "react";
import { approvalApi } from "../api/client.js";
import {
  allowApprovalForSession,
  composerPermissionRuleBehavior,
  permissionModeAllowsApproval,
  readComposerPermissionMode,
  readComposerPermissionRules,
  sessionAllowsApproval,
  subscribeComposerPermissionMode,
  subscribeComposerPermissionRules,
} from "./composerPermissions.js";

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
  allow_session: "本会话已允许",
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
  autoFocus = false,
  compact = false,
  interactive = true,
  queuedCount = 0,
}) {
  const [busy, setBusy] = useState(false);
  const [localDecision, setLocalDecision] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [permissionMode, setPermissionMode] = useState(readComposerPermissionMode);
  const [permissionRules, setPermissionRules] = useState(readComposerPermissionRules);
  const rootRef = useRef(null);
  const autoAttemptRef = useRef("");

  useEffect(() => subscribeComposerPermissionMode(setPermissionMode), []);
  useEffect(() => subscribeComposerPermissionRules(setPermissionRules), []);

  useEffect(() => {
    const approvalId = approval?.approvalId;
    if (!approvalId) return undefined;
    if (approval.decision || approval.status !== "waiting") {
      const shared = localApprovalStates.get(approvalId);
      clearLocalState(approvalId);
      setBusy(false);
      setLocalDecision(
        shared?.decision === "allow_session"
          ? "allow_session"
          : approval.decision || "",
      );
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

  const decision = approval?.decision || localDecision;
  const pending = approval?.status === "waiting" && !decision;
  const risk = riskLabels[approval?.risk] || "需确认操作";
  const ruleBehavior = composerPermissionRuleBehavior(approval, permissionRules);

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
      const result = await approvalApi.resolve(
        approval.approvalId,
        nextDecision,
      );
      if (nextDecision === "allow_session") {
        allowApprovalForSession(approval);
      }
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

  useEffect(() => {
    if (!pending || busy || ruleBehavior === "ask") return;
    const automaticDecision = ruleBehavior === "deny"
      ? "deny"
      : ruleBehavior === "allow"
        ? "allow_once"
        : permissionModeAllowsApproval(permissionMode, approval)
          || sessionAllowsApproval(approval)
          ? "allow_once"
          : "";
    if (!automaticDecision) return;
    const attemptKey = `${approval.approvalId}:${permissionMode}:${ruleBehavior}:${automaticDecision}`;
    if (autoAttemptRef.current === attemptKey) return;
    autoAttemptRef.current = attemptKey;
    handleDecision(automaticDecision);
  }, [approval, busy, pending, permissionMode, ruleBehavior]);

  useEffect(() => {
    if (!pending || busy || !approval?.expiresAt) return undefined;
    const expiresAt = Date.parse(approval.expiresAt);
    if (!Number.isFinite(expiresAt)) return undefined;
    const timer = window.setTimeout(
      () => handleDecision("timeout"),
      Math.max(0, expiresAt - Date.now()) + 250,
    );
    return () => window.clearTimeout(timer);
  }, [approval?.approvalId, approval?.expiresAt, pending, busy]);

  useEffect(() => {
    if (!pending || !interactive) return undefined;
    const focusPrompt = () => {
      rootRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      rootRef.current
        ?.querySelector("button:not(:disabled)")
        ?.focus({ preventScroll: true });
    };
    const handleFocusRequest = (event) => {
      const requestedApprovalId = String(event.detail?.approvalId || "").trim();
      if (
        requestedApprovalId
        && requestedApprovalId !== String(approval?.approvalId)
      ) return;
      focusPrompt();
    };
    window.addEventListener("knowflow:react-agent-interaction-focus", handleFocusRequest);
    if (autoFocus) {
      const frame = window.requestAnimationFrame(focusPrompt);
      return () => {
        window.cancelAnimationFrame(frame);
        window.removeEventListener("knowflow:react-agent-interaction-focus", handleFocusRequest);
      };
    }
    return () => window.removeEventListener(
      "knowflow:react-agent-interaction-focus",
      handleFocusRequest,
    );
  }, [approval?.approvalId, autoFocus, interactive, pending]);

  if (!approval?.approvalId) return null;

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
      data-approval-id={approval.approvalId}
      aria-label={`${approval.toolName || "工具"}操作确认`}
      aria-busy={busy}
      ref={rootRef}
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
            {ruleBehavior === "ask" ? " · Ask规则" : ""}
            {queuedCount ? ` · 另有${queuedCount}项待处理` : ""}
          </span>
        </div>
      </div>

      {!compact ? (
        <pre className={"agent-approval-summary"}>
          {summaryText(approval.inputSummary)}
        </pre>
      ) : null}

      {pending && interactive ? (
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
            onClick={() => handleDecision("allow_session")}
          >
            {"本会话允许"}
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

      {pending && !interactive ? (
        <button
          className="agent-approval-jump"
          type="button"
          onClick={() => window.dispatchEvent(
            new CustomEvent("knowflow:react-agent-interaction-focus"),
          )}
        >
          前往对话处理请求
        </button>
      ) : null}

      {errorMessage ? (
        <div className={"agent-approval-error"} role={"alert"}>
          {errorMessage}
        </div>
      ) : null}
    </section>
  );
}
