export const COMPOSER_PERMISSION_MODES = Object.freeze([
  {
    id: "plan",
    label: "计划",
    description: "只分析并制定计划，不执行修改",
  },
  {
    id: "ask",
    label: "询问",
    description: "写入和命令执行前确认",
  },
  {
    id: "auto_edit",
    label: "自动编辑",
    description: "普通文件修改自动通过，命令仍确认",
  },
  {
    id: "full_access",
    label: "完全访问",
    description: "本会话自动执行，仍受工作区与沙箱限制",
  },
]);

export const DEFAULT_COMPOSER_PERMISSION_MODE = "ask";

const STORAGE_KEY = "knowflow:composer-permission-mode";
const CHANGE_EVENT = "knowflow:react-permission-mode-change";
const LEGACY_MODE_ALIASES = Object.freeze({
  autoEdit: "auto_edit",
  bypass: "full_access",
});
const sessionApprovalGrants = new Set();

export function approvalSessionGrantKey(approval) {
  if (!approval?.toolName) return "";
  return [
    String(approval.serverName || "MCP").slice(0, 255),
    String(approval.toolName).slice(0, 160),
    String(approval.risk || "unknown").slice(0, 30),
    approval.destructive ? "destructive" : "standard",
  ].join("|");
}

export function allowApprovalForSession(approval) {
  const key = approvalSessionGrantKey(approval);
  if (key) sessionApprovalGrants.add(key);
  return key;
}

export function sessionAllowsApproval(approval) {
  const key = approvalSessionGrantKey(approval);
  return Boolean(key && sessionApprovalGrants.has(key));
}

export function clearApprovalSessionGrants() {
  sessionApprovalGrants.clear();
}

export function normalizeComposerPermissionMode(value) {
  const canonical = LEGACY_MODE_ALIASES[value] || value;
  return COMPOSER_PERMISSION_MODES.some((mode) => mode.id === canonical)
    ? canonical
    : DEFAULT_COMPOSER_PERMISSION_MODE;
}

export function readComposerPermissionMode() {
  if (typeof window === "undefined") return DEFAULT_COMPOSER_PERMISSION_MODE;
  try {
    return normalizeComposerPermissionMode(window.sessionStorage.getItem(STORAGE_KEY));
  } catch {
    return DEFAULT_COMPOSER_PERMISSION_MODE;
  }
}

export function setComposerPermissionMode(value) {
  const mode = normalizeComposerPermissionMode(value);
  if (typeof window === "undefined") return mode;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // The mode still applies to the current mounted page when storage is unavailable.
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: { mode } }));
  return mode;
}

export function cycleComposerPermissionMode() {
  const current = readComposerPermissionMode();
  const index = COMPOSER_PERMISSION_MODES.findIndex((mode) => mode.id === current);
  return setComposerPermissionMode(
    COMPOSER_PERMISSION_MODES[(index + 1) % COMPOSER_PERMISSION_MODES.length].id,
  );
}

export function subscribeComposerPermissionMode(listener) {
  if (typeof window === "undefined") return () => {};
  const handleChange = (event) => listener(
    normalizeComposerPermissionMode(event.detail?.mode),
  );
  window.addEventListener(CHANGE_EVENT, handleChange);
  return () => window.removeEventListener(CHANGE_EVENT, handleChange);
}

export function permissionModeAllowsApproval(mode, approval) {
  const normalized = normalizeComposerPermissionMode(mode);
  if (normalized === "full_access") return true;
  return normalized === "auto_edit"
    && approval?.risk === "write"
    && !approval?.destructive;
}
