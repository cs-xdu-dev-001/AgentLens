from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def require(relative_path: str, needle: str, label: str) -> None:
    if needle not in read(relative_path):
        raise AssertionError(f"Missing {label}: {needle}")


def main() -> None:
    policy = "frontend/react/src/components/composerPermissions.js"
    picker = "frontend/react/src/components/ComposerPermissionPicker.jsx"
    composer = "frontend/react/src/components/ChatComposerForm.jsx"
    commands = "frontend/react/src/components/composerCommands.js"
    approval = "frontend/react/src/components/AgentApprovalPrompt.jsx"
    styles = "frontend/styles.css"
    tui = "cli-tui/src/app.jsx"

    for token in ('id: "plan"', 'id: "ask"', 'id: "auto_edit"', 'id: "full_access"'):
        require(policy, token, "four-level permission policy")
    require(policy, 'autoEdit: "auto_edit"', "legacy auto-edit migration")
    require(policy, 'bypass: "full_access"', "legacy full-access migration")
    require(policy, "window.sessionStorage", "browser-session scope")
    require(policy, "permissionModeAllowsApproval", "approval policy projection")
    require(policy, "COMPOSER_PERMISSION_BEHAVIORS", "tool permission rule categories")
    require(policy, "composerPermissionRuleBehavior", "tool permission rule projection")
    require(policy, '["deny", "ask", "allow"]', "safe rule precedence")
    require(policy, "MAX_RULES_PER_BEHAVIOR", "bounded browser-session rules")
    require(policy, 'approval?.risk === "write"', "safe auto-edit boundary")
    require(policy, "!approval?.destructive", "destructive action guard")

    require(picker, 'role={"listbox"}', "permission listbox semantics")
    require(picker, 'role={"option"}', "permission option semantics")
    require(picker, '["ArrowDown", "ArrowUp"].includes(event.key)', "keyboard option navigation")
    require(picker, '["Home", "End"].includes(event.key)', "keyboard boundary navigation")
    require(picker, 'window.requestAnimationFrame(() => listboxRef.current?.focus())', "slash-command focus handoff")
    require(picker, 'role={"tab"}', "rule tab semantics")
    require(picker, "handleRuleTabKeyDown", "keyboard rule category navigation")
    require(picker, '["Enter", " "].includes(event.key)', "keyboard permission selection")
    require(picker, 'event.key === "Escape"', "keyboard close")
    require(picker, "本次浏览器会话", "session scope copy")
    require(picker, "工具规则", "tool rule editor entry")
    require(picker, "COMPOSER_PERMISSION_BEHAVIORS.map", "rule category tabs")
    require(picker, "updateComposerPermissionRules", "rule editor persistence")

    require(composer, "ComposerPermissionPicker", "composer permission control")
    require(composer, "cycleComposerPermissionMode", "Shift+Tab mode cycle")
    require(composer, "clearApprovalSessionGrants", "session grant reset owner")
    require(commands, 'value: "/permissions"', "permission slash command")
    require(commands, 'value: "/plan"', "plan slash command")
    require("frontend/react/src/controller/chatFlow.js", 'executionMode: permissionMode === "plan" ? "plan_only" : "auto"', "plan request projection")
    require("backend/knowflow/routers/extensions.py", 'payload.skillId is None and execution_mode != "plan_only"', "plan mode skill activation boundary")
    require(approval, "subscribeComposerPermissionMode", "live policy updates")
    require(approval, 'handleDecision("allow_once")', "automatic approval submission")
    require(approval, 'handleDecision("allow_session")', "session approval action")
    require(approval, "sessionAllowsApproval", "session approval projection")
    require(approval, "approval.approvalId,\n        nextDecision", "durable session decision")
    require(approval, "autoAttemptRef", "bounded automatic approval attempt")
    require(approval, 'ruleBehavior === "ask"', "ask rule override")
    require(approval, 'ruleBehavior === "deny"', "deny rule enforcement")

    require(styles, ".composer-permission-picker", "permission trigger layout")
    require(styles, ".composer-permission-popover", "permission popover")
    require(styles, ".composer-permission-option.danger", "full-access warning")
    require(styles, ".composer-permission-rule-tabs", "permission rule category control")
    require(styles, ".composer-permission-rule-add", "permission rule input")

    require(tui, "本次会话", "TUI session scope")
    require(tui, "权限模式已切换为", "TUI selection feedback")
    require(tui, "Allow / Ask / Deny", "TUI tool rule categories")
    require(tui, "permissionRuleBehavior", "TUI rule enforcement")
    require(tui, "Home/End首尾", "TUI permission boundary navigation")
    require(tui, "R工具规则", "TUI direct rule navigation")
    require(tui, "client.send({type: 'approve', decision})", "durable TUI session decision")

    script = r'''import {
  allowApprovalForSession,
  composerPermissionRuleBehavior,
  clearApprovalSessionGrants,
  emptyComposerPermissionRules,
  normalizeComposerPermissionMode,
  normalizeComposerPermissionRules,
  permissionModeAllowsApproval,
  sessionAllowsApproval,
  updateComposerPermissionRules,
} from "./frontend/react/src/components/composerPermissions.js";

if (normalizeComposerPermissionMode("invalid") !== "ask") process.exit(1);
if (permissionModeAllowsApproval("plan", {risk: "write"})) process.exit(13);
if (permissionModeAllowsApproval("ask", {risk: "write"})) process.exit(2);
if (!permissionModeAllowsApproval("auto_edit", {risk: "write", destructive: false})) process.exit(3);
if (permissionModeAllowsApproval("auto_edit", {risk: "write", destructive: true})) process.exit(4);
if (permissionModeAllowsApproval("auto_edit", {risk: "delete", destructive: false})) process.exit(5);
if (!permissionModeAllowsApproval("full_access", {risk: "delete", destructive: true})) process.exit(6);
if (normalizeComposerPermissionMode("autoEdit") !== "auto_edit") process.exit(7);
if (normalizeComposerPermissionMode("bypass") !== "full_access") process.exit(8);
const approval = {serverName: "workspace", toolName: "write_file", risk: "write", destructive: false};
if (sessionAllowsApproval(approval)) process.exit(9);
allowApprovalForSession(approval);
if (!sessionAllowsApproval(approval)) process.exit(10);
if (sessionAllowsApproval({...approval, destructive: true})) process.exit(11);
clearApprovalSessionGrants();
if (sessionAllowsApproval(approval)) process.exit(12);

let rules = emptyComposerPermissionRules();
rules = updateComposerPermissionRules(rules, "allow", "web_*");
if (composerPermissionRuleBehavior("WEB_SEARCH", rules) !== "allow") process.exit(14);
rules = updateComposerPermissionRules(rules, "ask", "web_search");
if (composerPermissionRuleBehavior("web_search", rules) !== "ask") process.exit(15);
rules = updateComposerPermissionRules(rules, "deny", "*");
if (composerPermissionRuleBehavior("web_search", rules) !== "deny") process.exit(16);
const conflict = normalizeComposerPermissionRules({allow: ["write_file"], deny: ["write_file"]});
if (conflict.deny[0] !== "write_file" || conflict.allow.length) process.exit(17);
const unchanged = updateComposerPermissionRules(rules, "allow", "bad rule name");
if (JSON.stringify(unchanged) !== JSON.stringify(rules)) process.exit(18);
'''
    subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
    )

    print("web and TUI permissions share real session-scoped modes and tool rules")


if __name__ == "__main__":
    main()
