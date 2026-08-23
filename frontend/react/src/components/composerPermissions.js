export const COMPOSER_PERMISSION_MODES = Object.freeze([
  {
    id: "ask",
    label: "询问",
    description: "写入和命令执行前确认",
  },
  {
    id: "autoEdit",
    label: "自动编辑",
    description: "普通文件修改自动通过，命令仍确认",
  },
  {
    id: "bypass",
    label: "完全访问",
    description: "所有工具自动通过，仅用于可信工作区",
  },
]);

export const DEFAULT_COMPOSER_PERMISSION_MODE = "ask";

const STORAGE_KEY = "knowflow:composer-permission-mode";
const CHANGE_EVENT = "knowflow:react-permission-mode-change";

export function normalizeComposerPermissionMode(value) {
  return COMPOSER_PERMISSION_MODES.some((mode) => mode.id === value)
    ? value
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
  if (normalized === "bypass") return true;
  return normalized === "autoEdit"
    && approval?.risk === "write"
    && !approval?.destructive;
}
