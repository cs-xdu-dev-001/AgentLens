from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, token: str, label: str) -> None:
    assert token in read(path), f"missing {label}: {path} -> {token}"


def forbid(path: str, token: str, label: str) -> None:
    assert token not in read(path), f"unexpected {label}: {path} -> {token}"


def main() -> None:
    client = "frontend/react/src/api/client.js"
    require(client, "export const approvalApi", "approval API")
    require(client, "/api/agent/approvals?status=waiting", "global waiting approval list endpoint")
    require(client, "listPending", "global approval list client")
    require(client, "/api/agent/approvals/", "approval endpoint")
    require(client, "body: { decision }", "approval decision body")

    flow = "frontend/react/src/controller/chatFlow.js"
    projection = "frontend/react/src/controller/agentEvents.js"
    require(projection, 'name === "approval.required"', "required SSE")
    require(projection, 'name === "approval.resolved"', "resolved SSE")
    require(projection, "cancelPendingAgentApprovals", "terminal approval cleanup")
    require(flow, "renderAgentApprovals", "approval render bridge")
    require(flow, "knowflow:react-approval-local-state", "local decision reconciliation")
    require(flow, "handleLocalApprovalState", "local decision state handler")
    require(flow, "handleApprovalResume", "durable approval reconnect")
    require(flow, "projection.paused", "paused stream preservation")

    events = "frontend/react/src/controller/messageEvents.js"
    require(events, "updateReactMessageApprovals", "message approval bridge")
    require(events, "knowflow:react-message-approvals", "approval message event")

    messages = "frontend/react/src/components/ChatMessages.jsx"
    require(messages, "AgentApprovalPrompt", "chat approval prompt")
    require(messages, "message.approvals", "message approval state")
    require(messages, "knowflow:react-message-approvals", "message approval listener")
    require(messages, "activeAgentInteractionOwner", "single transcript interaction owner")
    require(messages, 'data-interaction-active={ownsInteraction ? "true" : "false"}', "visible inactive requests")
    require(messages, "interactionPending={Boolean(interactionOwner)}", "recovery interaction lock")

    prompt = "frontend/react/src/components/AgentApprovalPrompt.jsx"
    composer = "frontend/react/src/components/ChatComposerForm.jsx"
    require(prompt, "approvalApi.resolve(", "approval submission")
    require(prompt, 'handleDecision("allow_once")', "allow once")
    require(prompt, 'handleDecision("allow_session")', "allow for session")
    require(prompt, "allowApprovalForSession", "session approval grant")
    require(prompt, "approval.approvalId,\n        nextDecision", "durable session decision")
    require(composer, "clearApprovalSessionGrants", "session approval reset")
    require(prompt, 'handleDecision("deny")', "deny")
    require(prompt, 'handleDecision("timeout")', "automatic timeout")
    require(prompt, "approval?.expiresAt", "server expiry timestamp")
    require(prompt, "disabled={busy", "busy action lock")
    require(prompt, "pendingApprovalIds", "cross-surface request lock")
    require(prompt, "knowflow:react-approval-local-state", "cross-surface state sync")
    require(prompt, "knowflow:react-agent-approval-resume", "resume dispatch")
    require(prompt, "scheduleLocalStateCleanup", "bounded shared state cleanup")
    require(prompt, "pendingApprovalIds.delete", "successful request lock release")
    require(prompt, "interactive = true", "single interactive approval owner")
    require(prompt, "knowflow:react-agent-interaction-focus", "approval focus request")
    require(prompt, "requestedApprovalId", "targeted approval focus")
    require(prompt, "String(approval?.approvalId)", "scoped approval focus target")
    require(prompt, "queuedCount", "pending interaction count")
    require(prompt, "error?.status === 404", "expired approval")
    require(prompt, "审批已失效", "expired copy")
    forbid(prompt, "dangerouslySetInnerHTML", "unsafe approval summary rendering")

    run_presentation = "frontend/react/src/components/agentRunPresentation.js"
    require(run_presentation, "pendingAgentInteractionOwners", "cross-message interaction queue")
    require(run_presentation, "activeAgentInteractionOwner", "active interaction projection")
    require(run_presentation, 'step.status === "waiting"', "waiting step priority")
    require(run_presentation, 'step.kind === "approval"', "approval step priority")

    presentation = (
        "frontend/react/src/components/agentTracePresentation.js"
    )
    require(presentation, 'mcp: "MCP"', "MCP node")
    require(presentation, 'approval: "APPROVAL"', "approval node")
    require(presentation, "serverName", "server detail")
    require(presentation, "toolName", "tool detail")
    require(presentation, "risk", "risk detail")
    require(presentation, "decision", "decision detail")

    require(
        run_presentation,
        '["tool", "mcp", "sandbox", "workspace"].includes(item.kind)',
        "MCP and workspace tool count",
    )
    require(run_presentation, '"等待确认"', "waiting approval summary")

    drawer = "frontend/react/src/components/ChatEvidenceDrawer.jsx"
    require(drawer, "AgentApprovalPrompt", "drawer approval prompt")
    require(drawer, "interactive={false}", "read-only drawer approval mirror")
    require(drawer, "knowflow:react-agent-approvals-updated", "drawer approval event")

    styles = "frontend/styles.css"
    require(styles, ".agent-approval-prompt", "approval card style")
    require(styles, ".agent-trace-strip.waiting", "waiting strip style")
    require(styles, "prefers-reduced-motion", "reduced motion")

    question_prompt = "frontend/react/src/components/AgentQuestionPrompt.jsx"
    require(question_prompt, "interactive = true", "single interactive question owner")
    require(question_prompt, "前往当前请求", "inactive question handoff")

    sidebar = "frontend/react/src/components/Sidebar.jsx"
    require(sidebar, "function PendingApprovals", "global approval inbox")
    require(sidebar, "approvalApi.listPending", "global approval inbox request")
    require(sidebar, "knowflow:react-session-continue", "approval session jump")
    require(sidebar, "pending-approvals-badge", "pending approval count badge")

    require(flow, "scheduleAgentInteractionFocus", "post-hydration approval focus")
    require(flow, "approvalMessageId", "approval message focus metadata")

    script = r'''import {
  activeAgentInteractionOwner,
  pendingAgentInteractionOwners,
} from "./frontend/react/src/components/agentRunPresentation.js";

const messages = [
  {
    id: "older",
    approvals: [{approvalId: "a1", status: "waiting", sequence: 2}],
    questions: [],
  },
  {
    id: "newer",
    approvals: [],
    questions: [{questionId: "q1", status: "waiting", sequence: 1}],
  },
];
const owners = pendingAgentInteractionOwners(messages);
if (owners.length !== 2) throw new Error("pending interactions were lost");
const active = activeAgentInteractionOwner(messages);
if (active.messageId !== "older" || active.interaction.value.approvalId !== "a1") {
  throw new Error("cross-message arrival order changed");
}
if (active.queuedCount !== 1) throw new Error("queued interaction count is wrong");
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    print("MCP approval UI contract is complete")


if __name__ == "__main__":
    main()
