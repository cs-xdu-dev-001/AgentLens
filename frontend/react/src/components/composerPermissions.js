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

export const COMPOSER_PERMISSION_BEHAVIORS = Object.freeze([
  {
    id: "allow",
    label: "Allow",
    description: "匹配工具自动放行，包括破坏性操作",
  },
  {
    id: "ask",
    label: "Ask",
    description: "匹配工具始终询问",
  },
  {
    id: "deny",
    label: "Deny",
    description: "匹配工具直接拒绝",
  },
]);

const STORAGE_KEY = "knowflow:composer-permission-mode";
const CHANGE_EVENT = "knowflow:react-permission-mode-change";
const RULE_STORAGE_KEY = "knowflow:composer-permission-rules";
const RULE_CHANGE_EVENT = "knowflow:react-permission-rules-change";
const MAX_RULES_PER_BEHAVIOR = 100;
const MAX_RULE_LENGTH = 120;
const RULE_PATTERN = /^[a-z0-9_.:*/-]+$/;
const LEGACY_MODE_ALIASES = Object.freeze({
  autoEdit: "auto_edit",
  bypass: "full_access",
});
const sessionApprovalGrants = new Set();

export function emptyComposerPermissionRules() {
  return { allow: [], ask: [], deny: [] };
}

export function normalizeComposerPermissionRule(value) {
  const rule = String(value || "").trim().toLowerCase();
  const wildcardIndex = rule.indexOf("*");
  const validWildcard = wildcardIndex < 0
    || rule === "*"
    || wildcardIndex === rule.length - 1 && rule.lastIndexOf("*") === wildcardIndex;
  return rule.length > 0
    && rule.length <= MAX_RULE_LENGTH
    && RULE_PATTERN.test(rule)
    && validWildcard
    ? rule
    : "";
}

export function normalizeComposerPermissionRules(value) {
  const source = value && typeof value === "object" ? value : {};
  const result = emptyComposerPermissionRules();
  const claimed = new Set();
  for (const behavior of ["deny", "ask", "allow"]) {
    const values = Array.isArray(source[behavior]) ? source[behavior] : [];
    for (const candidate of values) {
      const rule = normalizeComposerPermissionRule(candidate);
      if (!rule || claimed.has(rule)) continue;
      result[behavior].push(rule);
      claimed.add(rule);
      if (result[behavior].length >= MAX_RULES_PER_BEHAVIOR) break;
    }
  }
  return result;
}

export function updateComposerPermissionRules(
  rules,
  behavior,
  toolName,
  remove = false,
) {
  const rule = normalizeComposerPermissionRule(toolName);
  if (!rule || !COMPOSER_PERMISSION_BEHAVIORS.some((item) => item.id === behavior)) {
    return normalizeComposerPermissionRules(rules);
  }
  const nextRules = normalizeComposerPermissionRules(rules);
  for (const key of ["allow", "ask", "deny"]) {
    nextRules[key] = nextRules[key].filter((item) => item !== rule);
  }
  if (!remove) nextRules[behavior].push(rule);
  return normalizeComposerPermissionRules(nextRules);
}

function permissionRuleMatches(rule, toolName) {
  if (rule === "*") return true;
  if (rule.endsWith("*") && toolName.startsWith(rule.slice(0, -1))) return true;
  return rule === toolName;
}

export function composerPermissionRuleBehavior(
  approvalOrToolName,
  rules = readComposerPermissionRules(),
) {
  const rawToolName = typeof approvalOrToolName === "string"
    ? approvalOrToolName
    : approvalOrToolName?.toolName;
  const toolName = normalizeComposerPermissionRule(rawToolName);
  if (!toolName) return "";
  const normalizedRules = normalizeComposerPermissionRules(rules);
  for (const behavior of ["deny", "ask", "allow"]) {
    if (normalizedRules[behavior].some((rule) => permissionRuleMatches(rule, toolName))) {
      return behavior;
    }
  }
  return "";
}

export function permissionRuleCount(rules) {
  const normalized = normalizeComposerPermissionRules(rules);
  return normalized.allow.length + normalized.ask.length + normalized.deny.length;
}

export function readComposerPermissionRules() {
  if (typeof window === "undefined") return emptyComposerPermissionRules();
  try {
    return normalizeComposerPermissionRules(
      JSON.parse(window.sessionStorage.getItem(RULE_STORAGE_KEY) || "{}"),
    );
  } catch {
    return emptyComposerPermissionRules();
  }
}

export function setComposerPermissionRules(value) {
  const rules = normalizeComposerPermissionRules(value);
  if (typeof window === "undefined") return rules;
  try {
    window.sessionStorage.setItem(RULE_STORAGE_KEY, JSON.stringify(rules));
  } catch {
    // Rules still apply to mounted components when storage is unavailable.
  }
  window.dispatchEvent(new CustomEvent(RULE_CHANGE_EVENT, { detail: { rules } }));
  return rules;
}

export function subscribeComposerPermissionRules(listener) {
  if (typeof window === "undefined") return () => {};
  const handleChange = (event) => listener(
    normalizeComposerPermissionRules(event.detail?.rules),
  );
  window.addEventListener(RULE_CHANGE_EVENT, handleChange);
  return () => window.removeEventListener(RULE_CHANGE_EVENT, handleChange);
}

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
