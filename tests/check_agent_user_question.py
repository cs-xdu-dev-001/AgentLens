from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, token: str, label: str) -> None:
    assert token in read(path), f"missing {label}: {path} -> {token}"


def main() -> None:
    tooling = "backend/knowflow/services/agent_tooling.py"
    engine = "backend/knowflow/services/langgraph_agent_engine.py"
    runs = "backend/knowflow/routers/agent_runs.py"
    flow = "frontend/react/src/controller/chatFlow.js"
    projection = "frontend/react/src/controller/agentEvents.js"
    messages = "frontend/react/src/components/ChatMessages.jsx"
    prompt = "frontend/react/src/components/AgentQuestionPrompt.jsx"
    tui = "cli-tui/src/app.jsx"

    require(tooling, 'ASK_USER_QUESTION_TOOL = "ask_user_question"', "question tool")
    require(engine, '"type": "user_question"', "LangGraph interrupt")
    require(engine, "Command(resume=resume_payload)", "checkpoint resume")
    require(runs, '/api/agent/runs/{run_id}/answer', "answer endpoint")
    require(runs, '"answer": {"waiting_input"}', "answer transition guard")
    require(projection, 'name === "question.required"', "question projection")
    require(projection, "event.run?.pendingQuestion", "snapshot question restore")
    require(flow, "handleQuestionResume", "same-run reconnect")
    require(flow, "knowflow:react-agent-question-resume", "resume event")
    require(messages, "AgentQuestionPrompt", "question card mount")
    require(messages, "pendingAgentInteractions", "single interaction owner")
    require(messages, "data-interaction-kind", "active interaction marker")
    require(prompt, "agentRunApi.answer", "answer API call")
    require(prompt, "autoFocus", "active question focus ownership")
    require(prompt, "queuedCount", "pending interaction count")
    require(prompt, "knowflow:react-agent-interaction-focus", "shared focus request")
    require(prompt, 'role="alert"', "inline answer failure")
    require(tui, "function QuestionPrompt", "TUI question prompt")
    require(tui, "type: 'answer_question'", "TUI answer protocol")
    presentation = "frontend/react/src/components/agentRunPresentation.js"
    require(presentation, "pendingAgentInteractions", "interaction ordering")
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            """
import {pendingAgentInteractions} from './frontend/react/src/components/agentRunPresentation.js';
const rows = pendingAgentInteractions({
  approvals: [
    {approvalId: 'late', status: 'waiting', sequence: 4},
    {approvalId: 'done', status: 'resolved', decision: 'deny', sequence: 1},
  ],
  questions: [
    {questionId: 'first', status: 'waiting', sequence: 2},
    {questionId: 'answered', status: 'answered', sequence: 3},
  ],
});
if (rows.length !== 2) process.exit(1);
if (rows[0].kind !== 'question' || rows[0].value.questionId !== 'first') process.exit(2);
if (rows[1].kind !== 'approval' || rows[1].value.approvalId !== 'late') process.exit(3);
""",
        ],
        cwd=ROOT,
        check=True,
    )
    print("structured Agent user question flow is complete")


if __name__ == "__main__":
    main()
