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
    artifact_event_from_tool_execution,
    normalize_agent_event,
    public_artifact_projection,
    public_run_summary_projection,
    verification_from_agent_event,
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

    rate_limited = normalize_agent_event({
        "type": "error",
        "message": (
            "HTTP 429: rate_limit_reached_error: org-8242d004acb748ada9255f6d42f4dc23 "
            "ak-fbzbf9goi43111d8rrx request reached organization max RPM"
        ),
    })
    assert rate_limited["error"] == {
        "code": "rate_limited",
        "message": "上游模型请求过于频繁，自动重试后仍未恢复。",
        "retryable": True,
    }
    assert "org-" not in json.dumps(rate_limited)
    assert "ak-" not in json.dumps(rate_limited)

    parameter_error = normalize_agent_event({
        "type": "error",
        "errorCode": "ResponsesProtocolError",
        "message": "HTTP 400: invalid temperature: only 1 is allowed for this model",
    })
    assert parameter_error["error"]["code"] == "incompatible_parameters"
    assert parameter_error["error"]["target"] == "settings"
    assert parameter_error["recoveryActions"] == ["fix"]

    snapshot = normalize_agent_event({
        "type": "run_snapshot",
        "run": {
            "id": "run_summary",
            "goalSummary": "检查 api_key=SECRET_VALUE",
            "status": "running",
            "startedAt": "2026-08-13T10:00:00+00:00",
            "steps": [
                {"id": "one", "status": "completed"},
                {"id": "two", "status": "running"},
            ],
        },
    })
    assert snapshot["runSummary"] == {
        "runId": "run_summary",
        "status": "running",
        "headline": "检查 [REDACTED]",
        "startedAt": "2026-08-13T10:00:00+00:00",
        "lastActivityAt": snapshot["occurredAt"],
        "totalSteps": 2,
        "completedSteps": 1,
        "progressPercent": 50,
    }
    cancelling = normalize_agent_event({
        "type": "cancel_requested",
        "status": "cancelling",
        "run": {
            "id": "run_cancelling",
            "status": "cancelling",
            "goalSummary": "安全停止任务",
            "steps": [{"id": "one", "status": "running"}],
        },
    })
    assert cancelling["eventName"] == "run.cancelling"
    assert cancelling["normalizedStatus"] == "cancelling"
    assert cancelling["runSummary"]["status"] == "cancelling"
    normalizer = AgentEventNormalizer("run_cancelling")
    normalizer({
        "type": "run_snapshot",
        "run": {
            "id": "run_cancelling",
            "status": "running",
            "steps": [{"id": "one", "status": "running"}],
        },
    })
    cancelling_update = normalizer({
        "type": "cancel_requested",
        "status": "cancelling",
    })
    assert cancelling_update["runSummary"]["status"] == "cancelling"
    strict_summary = public_run_summary_projection({
        "runSummary": {
            "runId": "run_public",
            "status": "completed",
            "headline": "交付结果 token=SECRET_VALUE",
            "completedSteps": 9,
            "totalSteps": 3,
            "toolCalls": 4,
            "totalTokens": 1200,
            "secret": "SHOULD_NOT_SURVIVE",
        },
    })
    assert strict_summary == {
        "runId": "run_public",
        "status": "completed",
        "headline": "交付结果 [REDACTED]",
        "completedSteps": 3,
        "totalSteps": 3,
        "progressPercent": 100,
        "toolCalls": 4,
        "totalTokens": 1200,
    }

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

    verification = normalize_agent_event(
        {
            "type": "tool_result",
            "toolCallId": "call_check",
            "toolName": "run_sandbox_command",
            "status": "success",
            "latencyMs": 1200,
            "arguments": {"command": "npm test -- --token SECRET"},
            "output": {"exit_code": 0, "stdout": "38 passed"},
        }
    )
    assert verification["verification"] == {
        "id": "verification:call_check",
        "kind": "test",
        "tool": "npm_test",
        "status": "passed",
        "exitCode": 0,
        "durationMs": 1200,
    }
    assert "SECRET" not in json.dumps(verification["verification"])
    failed_verification = verification_from_agent_event(
        {
            "toolCallId": "call_build",
            "toolName": "run_sandbox_command",
            "status": "failed",
            "arguments": {"command": "npm run build"},
            "output": {"exit_code": 2},
        }
    )
    assert failed_verification == {
        "id": "verification:call_build",
        "kind": "build",
        "tool": "npm_build",
        "status": "failed",
        "exitCode": 2,
    }
    unusual_exit_code = verification_from_agent_event(
        {
            "toolCallId": "call_unusual",
            "toolName": "run_sandbox_command",
            "status": "success",
            "arguments": {"command": "git diff --check"},
            "output": {"exit_code": []},
        }
    )
    assert unusual_exit_code == {
        "id": "verification:call_unusual",
        "kind": "check",
        "tool": "git_diff_check",
        "status": "passed",
    }

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

    artifact = artifact_event_from_tool_execution(
        tool_name="write_workspace_file",
        status="success",
        output={
            "path": "reports/report.md",
            "writtenBytes": 512,
            "addedLines": 12,
            "removedLines": 2,
            "operationId": "edit_report",
        },
        tool_call_id="call_write",
    )
    assert artifact == {
        "type": "artifact_created",
        "artifactId": "file:reports/report.md",
        "artifactType": "file",
        "title": "reports/report.md",
        "path": "reports/report.md",
        "operation": "write",
        "sourceTool": "write_workspace_file",
        "toolCallId": "call_write",
        "writtenBytes": 512,
        "addedLines": 12,
        "removedLines": 2,
        "operationId": "edit_report",
        "diffAvailable": True,
        "reverted": False,
    }
    assert artifact_event_from_tool_execution(
        tool_name="read_workspace_file",
        status="success",
        output={"path": "reports/report.md"},
    ) is None
    assert artifact_event_from_tool_execution(
        tool_name="write_workspace_file",
        status="success",
        output={"path": "../outside.txt"},
    ) is None
    assert artifact_event_from_tool_execution(
        tool_name="write_workspace_file",
        status="success",
        output={"path": "/etc/passwd"},
    ) is None
    malformed_artifact = artifact_event_from_tool_execution(
        tool_name="write_workspace_file",
        status="success",
        output={"path": "reports/safe.md", "writtenBytes": []},
    )
    assert malformed_artifact is not None
    assert malformed_artifact["writtenBytes"] == 0
    strict_artifact = public_artifact_projection({
        **artifact,
        "secret": "SHOULD_NOT_SURVIVE",
        "content": "private body",
        "title": "report.md api_key=SECRET_VALUE",
    })
    assert strict_artifact is not None
    assert strict_artifact["path"] == "reports/report.md"
    assert "secret" not in strict_artifact
    assert "content" not in strict_artifact
    assert "SECRET_VALUE" not in json.dumps(strict_artifact)
    reference = normalize_agent_event({
        "type": "reference",
        "documentId": 7,
        "chunkId": "chunk-9",
        "filename": "安全报告.pdf",
        "score": 0.87,
        "content": "第一行\n第二行 token=SECRET_VALUE",
        "secret": "SHOULD_NOT_SURVIVE",
    })
    assert reference["artifactId"] == "reference:安全报告.pdf:chunk-9"
    assert reference["displayLabel"] == "安全报告.pdf"
    assert reference["sourceType"] == "knowledge"
    assert reference["documentId"] == "7"
    assert reference["excerpt"] == "第一行 第二行 [REDACTED]"
    assert "content" not in reference
    assert "secret" not in reference

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
    assert structured_failure["recoveryActions"] == ["fix"]

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
    assert second["runSummary"]["completedSteps"] == 1
    assert second["runSummary"]["totalSteps"] == 1
    assert second["runSummary"]["progressPercent"] == 100
    tool_started = stream({
        "type": "tool_started",
        "toolCallId": "call_stream",
        "toolName": "web_search",
        "status": "running",
    })
    assert tool_started["runSummary"]["toolCalls"] == 1
    usage_updated = stream({
        "type": "usage_updated",
        "usage": {"input_tokens": 20, "output_tokens": 30},
    })
    assert usage_updated["runSummary"]["totalTokens"] == 50
    message_updated = stream({"type": "answer", "content": "正在继续分析"})
    assert message_updated["eventName"] == "message.delta"
    assert message_updated["runSummary"]["lastActivityAt"] == message_updated["occurredAt"]
    artifact_updated = stream({
        "type": "reference",
        "url": "https://example.com/news?token=SECRET_VALUE",
    })
    assert artifact_updated["runSummary"]["referenceCount"] == 1
    done = stream({"type": "done"})
    assert done["runSummary"]["status"] == "completed"
    assert done["runSummary"]["finishedAt"]
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
      import {
        agentEventName as tuiAgentEventName,
        createRunProjection,
        projectRunEvent,
        userFacingErrorMessage,
      } from './cli-tui/src/protocol.js';
      import {mergeToolCall} from './frontend/react/src/controller/chatFlow.js';
      import {buildAgentRunPresentation} from './frontend/react/src/components/agentRunPresentation.js';
      const tool = {type: 'tool_result', status: 'failed'};
      if (agentEventName(tool) !== 'tool.failed') process.exit(1);
      if (agentEventName({type: 'answer', final: true}) !== 'message.completed') process.exit(5);
      if (!agentEventIs({eventName: 'approval.required'}, 'approval.required')) process.exit(2);
      const error = agentEventError({error: {code: 'x', message: '失败', retryable: false}});
      if (error.code !== 'x' || error.message !== '失败' || error.retryable !== false) process.exit(3);
      const rateLimitError = agentEventError({
        message: 'HTTP 429 rate_limit_reached_error org-8242d004acb748ada9255f6d42f4dc23 ak-fbzbf9goi43111d8rrx max RPM: 3',
      });
      if (rateLimitError.code !== 'rate_limited') process.exit(67);
      if (!rateLimitError.message.includes('请求过于频繁')) process.exit(68);
      if (/org-|ak-/.test(JSON.stringify(rateLimitError))) process.exit(69);
      const parameterMessage = userFacingErrorMessage(
        'ResponsesProtocolError',
        '执行失败。',
        'incompatible_parameters',
      );
      if (!parameterMessage.includes('清理temperature')) process.exit(70);
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
      let tuiProjection = createRunProjection();
      for (const event of fixture.events) tuiProjection = projectRunEvent(tuiProjection, event);
      const expected = fixture.projection;
      if (projection.answer !== expected.answer) process.exit(8);
      if (projection.terminal !== expected.terminal) process.exit(9);
      if (projection.lastSequence !== expected.lastSequence) process.exit(10);
      if (projection.toolCalls[0]?.status !== expected.toolStatus) process.exit(11);
      if (projection.approvals[0]?.status !== expected.approvalStatus) process.exit(12);
      if (projection.trace.length !== expected.traceCount) process.exit(13);
      if (projection.references.length !== expected.referenceCount) process.exit(14);
      if (projection.sessionId !== expected.sessionId) process.exit(15);
      if (projection.usage.totalTokens !== expected.totalTokens) process.exit(20);
      if (projection.artifacts.length !== expected.artifactCount) process.exit(21);
      if (tuiProjection.usage.totalTokens !== expected.totalTokens) process.exit(22);
      if (tuiProjection.artifacts.length !== expected.artifactCount - expected.referenceCount) process.exit(23);
      if (tuiProjection.references.length !== expected.referenceCount) process.exit(34);
      if (tuiProjection.references[0]?.url !== 'https://example.com/') process.exit(35);
      if (projection.references[0]?.displayLabel !== 'example.com') process.exit(47);
      if (tuiProjection.references[0]?.displayLabel !== 'example.com') process.exit(48);
      if (projection.references[0]?.sourceType !== 'web' || tuiProjection.references[0]?.sourceType !== 'web') process.exit(49);
      if (projection.context.usagePercent !== expected.contextUsagePercent) process.exit(30);
      if (projection.context.contextTrimmed !== expected.contextTrimmed) process.exit(31);
      if (tuiProjection.context.usagePercent !== expected.contextUsagePercent) process.exit(32);
      if (tuiProjection.context.contextTrimmed !== expected.contextTrimmed) process.exit(33);
      const summaryEvent = {
        eventName: 'run.updated',
        runId: 'run_summary',
        runSummary: {
          runId: 'run_summary',
          status: 'running',
          headline: '统一摘要',
          completedSteps: 1,
          totalSteps: 4,
          progressPercent: 25,
          toolCalls: 2,
          totalTokens: 900,
        },
      };
      projection = projectAgentEvent(projection, summaryEvent).projection;
      tuiProjection = projectRunEvent(tuiProjection, summaryEvent);
      if (projection.runSummary?.headline !== '统一摘要') process.exit(50);
      if (projection.run?.runSummary?.progressPercent !== 25) process.exit(51);
      if (tuiProjection.runSummary?.totalTokens !== 900) process.exit(52);
      const cancellingEvent = {
        type: 'cancel_requested',
        runId: 'run_cancelling',
        status: 'cancelling',
        phase: '正在安全停止当前操作',
        run: {
          id: 'run_cancelling',
          status: 'cancelling',
          currentStepId: 'step_cancelling',
          steps: [{id: 'step_cancelling', title: '整理文件', status: 'running'}],
        },
        runSummary: {
          runId: 'run_cancelling',
          status: 'cancelling',
          completedSteps: 0,
          totalSteps: 1,
        },
      };
      if (agentEventName(cancellingEvent) !== 'run.cancelling') process.exit(70);
      if (tuiAgentEventName(cancellingEvent) !== 'run.cancelling') process.exit(71);
      const webCancelling = projectAgentEvent(createAgentProjection(), cancellingEvent).projection;
      const tuiCancelling = projectRunEvent(createRunProjection(), cancellingEvent);
      if (webCancelling.run?.status !== 'cancelling') process.exit(72);
      if (webCancelling.runSummary?.status !== 'cancelling') process.exit(73);
      if (tuiCancelling.runSummary?.status !== 'cancelling') process.exit(74);
      const cancellingPresentation = buildAgentRunPresentation({
        run: webCancelling.run,
        trace: [],
      });
      if (!cancellingPresentation?.active) process.exit(75);
      if (cancellingPresentation.status?.className !== 'stopping') process.exit(76);
      if (cancellingPresentation.processSummary !== '正在安全停止当前操作') process.exit(77);
      let progressProjection = createAgentProjection({
        run: {
          id: 'run_progress',
          status: 'running',
          currentStepId: 'step_progress',
          steps: [{id: 'step_progress', title: '执行检查', status: 'running'}],
        },
      });
      progressProjection = projectAgentEvent(progressProjection, {
        eventName: 'tool.progress',
        runId: 'run_progress',
        toolCallId: 'call_progress',
        toolName: 'run_sandbox_command',
        elapsedSeconds: 1.2,
        totalLines: 4,
        totalBytes: 256,
      }).projection;
      if (progressProjection.run?.activeTool?.toolCallId !== 'call_progress') process.exit(70);
      if (progressProjection.run?.steps?.[0]?.elapsedSeconds !== 1.2) process.exit(71);
      if (progressProjection.run?.steps?.[0]?.totalLines !== 4) process.exit(72);
      const progressPresentation = buildAgentRunPresentation({
        run: progressProjection.run,
        trace: progressProjection.trace,
      });
      if (!progressPresentation?.processSummary.includes('1.2s')) process.exit(75);
      if (!progressPresentation?.rows?.[0]?.meta.includes('4行')) process.exit(76);
      progressProjection = projectAgentEvent(progressProjection, {
        eventName: 'tool.completed',
        runId: 'run_progress',
        toolCallId: 'call_progress',
        toolName: 'run_sandbox_command',
        elapsedSeconds: 1.4,
        totalLines: 5,
        totalBytes: 300,
      }).projection;
      if (progressProjection.run?.activeTool !== null) process.exit(73);
      if (progressProjection.run?.steps?.[0]?.totalBytes !== 300) process.exit(74);
      if (projection.artifacts[1]?.path !== 'reports/report.md') process.exit(28);
      if (tuiProjection.artifacts[0]?.addedLines !== 12) process.exit(29);
      const unsafeArtifact = {
        eventName: 'artifact.created',
        eventId: 'artifact-unsafe',
        artifactId: 'file:reports/safe.md',
        artifactType: 'file',
        path: 'reports/safe.md',
        title: 'safe.md token=SECRET_VALUE',
        secret: 'SHOULD_NOT_SURVIVE',
        content: 'private body',
        addedLines: 2,
      };
      projection = projectAgentEvent(projection, unsafeArtifact).projection;
      tuiProjection = projectRunEvent(tuiProjection, unsafeArtifact);
      const webArtifact = projection.artifacts.find(item => item.artifactId === unsafeArtifact.artifactId);
      const tuiArtifact = tuiProjection.artifacts.find(item => item.artifactId === unsafeArtifact.artifactId);
      if (!webArtifact || !tuiArtifact) process.exit(41);
      if (webArtifact.secret !== undefined || webArtifact.content !== undefined) process.exit(42);
      if (tuiArtifact.secret !== undefined || tuiArtifact.content !== undefined) process.exit(43);
      if (JSON.stringify([webArtifact, tuiArtifact]).includes('SECRET_VALUE')) process.exit(44);
      const escapedArtifact = {...unsafeArtifact, artifactId: 'file:escaped', path: '../escaped.txt'};
      projection = projectAgentEvent(projection, escapedArtifact).projection;
      tuiProjection = projectRunEvent(tuiProjection, escapedArtifact);
      if (projection.artifacts.some(item => item.artifactId === 'file:escaped')) process.exit(45);
      if (tuiProjection.artifacts.some(item => item.artifactId === 'file:escaped')) process.exit(46);
      const verificationEvent = {
        eventName: 'tool.completed',
        runId: 'run_fixture',
        toolCallId: 'call_verify',
        toolName: 'run_sandbox_command',
        normalizedStatus: 'completed',
        verification: {
          id: 'verification:call_verify',
          kind: 'test',
          tool: 'npm_test',
          status: 'passed',
          exitCode: 0,
          durationMs: 1200,
          command: 'npm test -- --token SECRET',
        },
      };
      projection = projectAgentEvent(projection, verificationEvent).projection;
      tuiProjection = projectRunEvent(tuiProjection, verificationEvent);
      const expectedVerification = {
        id: 'verification:call_verify',
        kind: 'test',
        status: 'passed',
        tool: 'npm_test',
        exitCode: 0,
        durationMs: 1200,
      };
      const matchesVerification = item => (
        item?.id === expectedVerification.id
        && item?.kind === expectedVerification.kind
        && item?.status === expectedVerification.status
        && item?.tool === expectedVerification.tool
        && item?.exitCode === expectedVerification.exitCode
        && item?.durationMs === expectedVerification.durationMs
        && item?.command === undefined
      );
      if (projection.verifications.length !== 1 || !matchesVerification(projection.verifications[0])) process.exit(36);
      if (projection.run.verifications.length !== 1 || !matchesVerification(projection.run.verifications[0])) process.exit(37);
      if (tuiProjection.verifications.length !== 1 || !matchesVerification(tuiProjection.verifications[0])) process.exit(38);
      if (JSON.stringify(projection.verifications).includes('SECRET')) process.exit(39);
      const invalidVerification = {
        ...verificationEvent,
        toolCallId: 'call_invalid',
        verification: {id: 'verification:call_invalid', kind: 'other', tool: 'shell', status: 'passed'},
      };
      projection = projectAgentEvent(projection, invalidVerification).projection;
      tuiProjection = projectRunEvent(tuiProjection, invalidVerification);
      if (projection.verifications.length !== 1 || tuiProjection.verifications.length !== 1) process.exit(40);
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
      const retryEvent = {
        eventName: 'model.retrying',
        retryAttempt: 2,
        maxRetries: 3,
        retryInMs: 10000,
        statusCode: 429,
        errorType: 'rate_limit',
      };
      const retryStartedAt = Date.now();
      let retryProjection = projectAgentEvent(
        createAgentProjection({run: {id: 'run_retry', status: 'running'}}),
        retryEvent,
      ).projection;
      let retryTuiProjection = projectRunEvent(createRunProjection(), retryEvent);
      if (retryProjection.modelRetry?.reason !== '模型限流') process.exit(60);
      if (retryProjection.run?.modelRetry?.attempt !== 2) process.exit(61);
      if (retryTuiProjection.modelRetry?.maxRetries !== 3) process.exit(62);
      if (retryProjection.modelRetry.retryAt < retryStartedAt + 10000) process.exit(63);
      if (retryTuiProjection.modelRetry.retryAt < retryStartedAt + 10000) process.exit(64);
      retryProjection = projectAgentEvent(
        retryProjection,
        {eventName: 'message.delta', content: '继续'},
      ).projection;
      retryTuiProjection = projectRunEvent(
        retryTuiProjection,
        {eventName: 'message.delta', content: '继续'},
      );
      if (retryProjection.modelRetry !== null || retryProjection.run?.modelRetry !== null) process.exit(65);
      if (retryTuiProjection.modelRetry !== null) process.exit(66);
      const failure = {
        eventName: 'error.raised',
        error: {code: 'fixture_failed', message: '失败', retryable: true},
        recoveryActions: ['continue', 'retry'],
      };
      projection = projectAgentEvent(projection, failure).projection;
      tuiProjection = projectRunEvent(tuiProjection, failure);
      if (projection.recoveryActions.join(',') !== 'continue,retry') process.exit(24);
      if (tuiProjection.recoveryActions.join(',') !== 'continue,retry') process.exit(25);
      const stableProjection = projectRunEvent(tuiProjection, {eventName: 'message.delta', content: 'x'});
      if (stableProjection !== tuiProjection) process.exit(26);
      let terminalProjection = createAgentProjection({
        trace: [
          {stepId: 'step_live', kind: 'tool', name: 'web_fetch', status: 'running'},
          {stepId: 'memory_live', kind: 'memory', name: 'memory_write', status: 'running'},
        ],
        toolCalls: [{toolCallId: 'call_live', toolName: 'web_fetch', status: 'running'}],
        run: {
          id: 'run_live',
          status: 'running',
          currentStepId: 'plan_live',
          steps: [{id: 'plan_live', status: 'running'}],
        },
        runSummary: {
          runId: 'run_live',
          status: 'running',
          completedSteps: 0,
          totalSteps: 1,
        },
      });
      terminalProjection = projectAgentEvent(terminalProjection, {
        eventName: 'tool.completed',
        toolCallId: 'call_live',
        toolName: 'web_fetch',
      }).projection;
      if (terminalProjection.toolCalls[0]?.status !== 'completed') process.exit(53);
      terminalProjection = projectAgentEvent(terminalProjection, {
        eventName: 'run.completed',
        runId: 'run_live',
        occurredAt: '2026-08-14T00:00:00Z',
      }).projection;
      if (terminalProjection.trace[0]?.status !== 'completed') process.exit(54);
      if (terminalProjection.trace[1]?.status !== 'running') process.exit(55);
      if (terminalProjection.runSummary?.status !== 'completed') process.exit(56);
      if (terminalProjection.runSummary?.completedSteps !== 1) process.exit(57);
      if (terminalProjection.run?.status !== 'completed') process.exit(58);
      if (terminalProjection.run?.steps?.[0]?.status !== 'completed') process.exit(59);
      if (terminalProjection.run?.currentStepId !== null) process.exit(60);
      projection = projectAgentEvent(projection, {eventName: 'run.completed'}).projection;
      tuiProjection = projectRunEvent(tuiProjection, {eventName: 'run.completed'});
      if (projection.recoveryActions.length || tuiProjection.recoveryActions.length) process.exit(27);
    """
    subprocess.run(
        ["node", "--input-type=module", "-e", web_check],
        cwd=ROOT,
        check=True,
    )

    print("Unified Agent event protocol checks passed")


if __name__ == "__main__":
    main()
