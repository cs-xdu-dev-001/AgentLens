const RUNNING_STATUSES = new Set(["planning", "running"]);
const WAITING_STATUSES = new Set(["waiting", "waiting_approval", "waiting_input", "paused"]);
const COMPLETED_STATUSES = new Set(["completed", "success", "succeeded"]);
const FAILED_STATUSES = new Set(["failed", "error"]);

const FEEDBACK = {
  idle: {
    state: "idle",
    title: "AgentLens",
    notification: "",
    color: "#10a37f",
  },
  running: {
    state: "running",
    title: "运行中 · AgentLens",
    notification: "",
    color: "#d97757",
  },
  waiting: {
    state: "waiting",
    title: "等待操作 · AgentLens",
    notification: "Agent需要你的操作",
    color: "#2563eb",
  },
  completed: {
    state: "completed",
    title: "已完成 · AgentLens",
    notification: "任务已完成",
    color: "#10a37f",
  },
  failed: {
    state: "failed",
    title: "执行失败 · AgentLens",
    notification: "任务执行失败",
    color: "#dc2626",
  },
};

export function agentWindowFeedback(run) {
  const status = String(run?.runSummary?.status || run?.status || "").trim().toLowerCase();
  let state = "idle";
  if (WAITING_STATUSES.has(status)) state = "waiting";
  else if (RUNNING_STATUSES.has(status)) state = "running";
  else if (COMPLETED_STATUSES.has(status)) state = "completed";
  else if (FAILED_STATUSES.has(status)) state = "failed";
  return {
    ...FEEDBACK[state],
    runId: String(run?.id || run?.runId || run?.runSummary?.runId || ""),
  };
}

export function shouldNotifyAgentWindow(previous, next, {
  visibilityState = "visible",
  hasFocus = true,
} = {}) {
  if (!["waiting", "completed", "failed"].includes(next?.state)) return false;
  if (previous?.state === next.state && previous?.runId === next.runId) return false;
  return visibilityState === "hidden" || !hasFocus;
}

export function agentWindowFaviconDataUrl(state) {
  const feedback = FEEDBACK[state] || FEEDBACK.idle;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect x="4" y="4" width="40" height="40" rx="12" fill="#fff" stroke="#d6d6d3" stroke-width="1.2"/><path d="M17 14v20M31 14 20.5 24.2 32 34" fill="none" stroke="#111" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/><circle cx="38" cy="10" r="6" fill="${feedback.color}" stroke="#fff" stroke-width="2"/></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}
