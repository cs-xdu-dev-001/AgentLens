from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_event_protocol import (  # noqa: E402
    AGENT_EVENT_SCHEMA_VERSION,
    AgentEventNormalizer,
    normalize_agent_event,
)


def main() -> None:
    started = normalize_agent_event(
        {
            "type": "tool_started",
            "runId": "run_protocol",
            "toolCallId": "call_1",
            "toolName": "web_fetch",
            "status": "running",
        }
    )
    assert started["schemaVersion"] == AGENT_EVENT_SCHEMA_VERSION
    assert started["eventName"] == "tool.started"
    assert started["category"] == "tool"
    assert started["status"] == "running"
    assert started["normalizedStatus"] == "running"
    assert started["eventId"].startswith("evt_")
    assert started["occurredAt"].endswith("+00:00")

    completed = normalize_agent_event(
        {
            "type": "tool_result",
            "status": "success",
            "latencyMs": 42,
        },
        run_id="run_protocol",
    )
    assert completed["eventName"] == "tool.completed"
    assert completed["status"] == "success"
    assert completed["normalizedStatus"] == "completed"
    assert completed["durationMs"] == 42

    failed = normalize_agent_event(
        {
            "type": "tool_result",
            "status": "failed",
            "errorCode": "web_fetch_timeout",
            "errorMessage": "请求超时",
        }
    )
    assert failed["eventName"] == "tool.failed"
    assert failed["error"] == {
        "code": "web_fetch_timeout",
        "message": "请求超时",
        "retryable": True,
    }
    assert failed["recoveryActions"] == ["retry", "fix"]

    message = normalize_agent_event(
        {"type": "answer", "message": "这是普通消息", "content": "正文"}
    )
    assert message["eventName"] == "message.delta"
    assert message["normalizedStatus"] == "running"
    assert "error" not in message

    structured_failure = normalize_agent_event(
        {
            "eventName": "step.failed",
            "error": {
                "code": "validation_failed",
                "message": "校验失败",
                "retryable": False,
            },
        }
    )
    assert structured_failure["normalizedStatus"] == "failed"
    assert structured_failure["error"]["retryable"] is False

    stream = AgentEventNormalizer("run_stream")
    first = stream({
        "type": "run_started",
        "runId": "run_untrusted",
        "sequence": 99,
    })
    second = stream({"type": "agent_step", "status": "success"})
    assert first["eventName"] == "run.started"
    assert second["eventName"] == "step.completed"
    assert [first["sequence"], second["sequence"]] == [1, 2]
    assert first["runId"] == "run_stream"
    assert second["runId"] == "run_stream"
    assert normalize_agent_event(second) == second

    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "agent_event_protocol_v1.json")
        .read_text(encoding="utf-8")
    )
    assert fixture["schemaVersion"] == AGENT_EVENT_SCHEMA_VERSION
    assert [
        normalize_agent_event(event)["eventName"]
        for event in fixture["events"]
    ] == fixture["eventNames"]

    web_check = """
      import fs from 'node:fs';
      import {
        agentEventError,
        agentEventIs,
        agentEventName,
        agentReconnectDelay,
        createAgentProjection,
        isRetryableAgentStreamStatus,
        projectAgentEvent,
      } from './frontend/react/src/controller/agentEvents.js';
      import {agentEventName as tuiAgentEventName} from './cli-tui/src/protocol.js';
      import {mergeToolCall} from './frontend/react/src/controller/chatFlow.js';
      const tool = {type: 'tool_result', status: 'failed'};
      if (agentEventName(tool) !== 'tool.failed') process.exit(1);
      if (agentEventName({type: 'answer', final: true}) !== 'message.completed') process.exit(5);
      if (!agentEventIs({eventName: 'approval.required'}, 'approval.required')) process.exit(2);
      const error = agentEventError({error: {code: 'x', message: '失败', retryable: false}});
      if (error.code !== 'x' || error.message !== '失败' || error.retryable !== false) process.exit(3);
      const calls = mergeToolCall(
        [{toolCallId: 'call_1', status: 'running'}],
        {toolCallId: 'call_1', normalizedStatus: 'completed', output: 'ok'},
      );
      if (calls.length !== 1 || calls[0].status !== 'completed' || calls[0].output !== 'ok') process.exit(4);
      const fixture = JSON.parse(fs.readFileSync(
        './tests/fixtures/agent_event_protocol_v1.json',
        'utf8',
      ));
      const webNames = fixture.events.map(agentEventName);
      const tuiNames = fixture.events.map(tuiAgentEventName);
      if (JSON.stringify(webNames) !== JSON.stringify(fixture.eventNames)) process.exit(6);
      if (JSON.stringify(tuiNames) !== JSON.stringify(fixture.eventNames)) process.exit(7);
      let projection = createAgentProjection();
      for (const event of fixture.events) {
        projection = projectAgentEvent(projection, event).projection;
      }
      const expected = fixture.projection;
      if (projection.answer !== expected.answer) process.exit(8);
      if (projection.terminal !== expected.terminal) process.exit(9);
      if (projection.lastSequence !== expected.lastSequence) process.exit(10);
      if (projection.toolCalls[0]?.status !== expected.toolStatus) process.exit(11);
      if (projection.approvals[0]?.status !== expected.approvalStatus) process.exit(12);
      if (projection.trace.length !== expected.traceCount) process.exit(13);
      if (projection.references.length !== expected.referenceCount) process.exit(14);
      if (projection.sessionId !== expected.sessionId) process.exit(15);
      if (agentReconnectDelay(0) !== 250 || agentReconnectDelay(8) !== 4000) process.exit(16);
      if (!isRetryableAgentStreamStatus(503) || !isRetryableAgentStreamStatus(429)) process.exit(17);
      if (isRetryableAgentStreamStatus(401) || isRetryableAgentStreamStatus(404)) process.exit(18);
      let approvalProjection = projectAgentEvent(
        createAgentProjection(),
        {eventName: 'approval.required', approvalId: 'approval_pause'},
      ).projection;
      approvalProjection = projectAgentEvent(
        approvalProjection,
        {
          eventName: 'approval.resolved',
          approvalId: 'approval_pause',
          status: 'success',
          run: {id: 'run_pause', status: 'running'},
        },
      ).projection;
      if (approvalProjection.paused) process.exit(19);
    """
    subprocess.run(
        ["node", "--input-type=module", "-e", web_check],
        cwd=ROOT,
        check=True,
    )

    print("Unified Agent event protocol checks passed")


if __name__ == "__main__":
    main()
