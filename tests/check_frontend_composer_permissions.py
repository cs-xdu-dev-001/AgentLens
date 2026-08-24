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
    require(policy, 'approval?.risk === "write"', "safe auto-edit boundary")
    require(policy, "!approval?.destructive", "destructive action guard")

    require(picker, 'role={"listbox"}', "permission listbox semantics")
    require(picker, 'role={"option"}', "permission option semantics")
    require(picker, '["ArrowDown", "ArrowUp"].includes(event.key)', "keyboard option navigation")
    require(picker, 'event.key === "Enter"', "keyboard permission selection")
    require(picker, 'event.key === "Escape"', "keyboard close")
    require(picker, "仅影响本次浏览器会话", "session scope copy")

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
    require(approval, "transportDecision", "server-side decision boundary")
    require(approval, "autoAttemptRef", "bounded automatic approval attempt")

    require(styles, ".composer-permission-picker", "permission trigger layout")
    require(styles, ".composer-permission-popover", "permission popover")
    require(styles, ".composer-permission-option.danger", "full-access warning")

    require(tui, "仅影响本次会话，Shift+Tab可快速切换", "TUI session scope")
    require(tui, "权限模式已切换为", "TUI selection feedback")

    script = r'''import {
  allowApprovalForSession,
  clearApprovalSessionGrants,
  normalizeComposerPermissionMode,
  permissionModeAllowsApproval,
  sessionAllowsApproval,
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
'''
    subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
    )

    print("web and TUI permission modes share real session-scoped behavior")


if __name__ == "__main__":
    main()
