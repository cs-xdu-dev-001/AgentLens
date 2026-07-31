from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def require(relative_path: str, needle: str, label: str) -> None:
    if needle not in read(relative_path):
        raise AssertionError(f"Missing {label}: {needle}")


def main() -> None:
    component = "frontend/react/src/components/AgentRecoveryPanel.jsx"
    require(component, "从失败步骤继续", "durable step recovery action")
    require(component, "重新运行本轮", "full run retry action")
    require(
        component,
        "knowflow:react-agent-run-action",
        "resume event dispatch",
    )
    require(
        component,
        'action: "restart"',
        "durable full run restart action",
    )
    require(
        component,
        "knowflow:react-page-activated",
        "configuration target navigation",
    )
    require(component, "failureLabels", "Chinese recovery copy map")
    require(component, "attemptCount", "attempt count display")

    client = "frontend/react/src/api/client.js"
    require(client, "restart:", "restart API client")
    require(client, "/restart", "restart API endpoint")

    controller = "frontend/react/src/controller/chatFlow.js"
    require(controller, '"restart"', "restart controller action")
    require(
        controller,
        "nextRunId",
        "replacement run reconnect binding",
    )

    drawer = "frontend/react/src/components/ChatEvidenceDrawer.jsx"
    require(drawer, "AgentRecoveryPanel", "drawer recovery panel")
    require(drawer, "messageId={messageId}", "recovery message binding")

    plan = "frontend/react/src/components/AgentTaskPlan.jsx"
    if 'dispatchAction(run, "resume", messageId)' in read(plan):
        raise AssertionError("duplicate plan resume action remains")

    presentation = (
        "frontend/react/src/components/agentTracePresentation.js"
    )
    require(
        presentation,
        'normalizeTraceStatus(step?.status) === "failed"',
        "failure-aware summary label",
    )
    require(presentation, '"失败原因"', "failure summary label")

    styles = read("frontend/styles.css")
    for selector in (
        ".agent-recovery-panel",
        ".agent-recovery-actions",
        ".agent-recovery-code",
    ):
        if selector not in styles:
            raise AssertionError(f"Missing recovery style: {selector}")
    if "@media (max-width: 520px)" not in styles:
        raise AssertionError("Missing compact recovery layout")

    print("Agent recovery controls are actionable and non-duplicated")


if __name__ == "__main__":
    main()
