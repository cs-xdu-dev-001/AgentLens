from pathlib import Path


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
    require(client, "/api/agent/approvals/", "approval endpoint")
    require(client, "body: { decision }", "approval decision body")

    flow = "frontend/react/src/controller/chatFlow.js"
    require(flow, 'eventPayload.type === "approval_required"', "required SSE")
    require(flow, 'eventPayload.type === "approval_resolved"', "resolved SSE")
    require(flow, "markApprovalsCancelled", "terminal approval cleanup")
    require(flow, "renderAgentApprovals", "approval render bridge")
    require(flow, "knowflow:react-approval-local-state", "local decision reconciliation")
    require(flow, "handleLocalApprovalState", "local decision state handler")

    events = "frontend/react/src/controller/messageEvents.js"
    require(events, "updateReactMessageApprovals", "message approval bridge")
    require(events, "knowflow:react-message-approvals", "approval message event")

    messages = "frontend/react/src/components/ChatMessages.jsx"
    require(messages, "AgentApprovalPrompt", "chat approval prompt")
    require(messages, "message.approvals", "message approval state")
    require(messages, "knowflow:react-message-approvals", "message approval listener")

    prompt = "frontend/react/src/components/AgentApprovalPrompt.jsx"
    require(prompt, 'approvalApi.resolve(approval.approvalId, "allow_once")', "allow once")
    require(prompt, 'approvalApi.resolve(approval.approvalId, "deny")', "deny")
    require(prompt, "disabled={busy", "busy action lock")
    require(prompt, "pendingApprovalIds", "cross-surface request lock")
    require(prompt, "knowflow:react-approval-local-state", "cross-surface state sync")
    require(prompt, "scheduleLocalStateCleanup", "bounded shared state cleanup")
    require(prompt, "pendingApprovalIds.delete", "successful request lock release")
    require(prompt, "error?.status === 404", "expired approval")
    require(prompt, "审批已失效", "expired copy")
    forbid(prompt, "dangerouslySetInnerHTML", "unsafe approval summary rendering")

    strip = "frontend/react/src/components/AgentTraceStrip.jsx"
    require(strip, 'step.status === "waiting"', "waiting step priority")
    require(strip, 'step.kind === "approval"', "approval step priority")

    presentation = (
        "frontend/react/src/components/agentTracePresentation.js"
    )
    require(presentation, 'mcp: "MCP"', "MCP node")
    require(presentation, 'approval: "APPROVAL"', "approval node")
    require(presentation, "serverName", "server detail")
    require(presentation, "toolName", "tool detail")
    require(presentation, "risk", "risk detail")
    require(presentation, "decision", "decision detail")

    summary = "frontend/react/src/components/AgentRunSummary.jsx"
    require(summary, 'step.kind === "tool" || step.kind === "mcp"', "MCP tool count")
    require(summary, '"等待确认"', "waiting approval summary")

    drawer = "frontend/react/src/components/ChatEvidenceDrawer.jsx"
    require(drawer, "AgentApprovalPrompt", "drawer approval prompt")
    require(drawer, "knowflow:react-agent-approvals-updated", "drawer approval event")

    styles = "frontend/styles.css"
    require(styles, ".agent-approval-prompt", "approval card style")
    require(styles, ".agent-trace-strip.waiting", "waiting strip style")
    require(styles, "prefers-reduced-motion", "reduced motion")
    print("MCP approval UI contract is complete")


if __name__ == "__main__":
    main()
