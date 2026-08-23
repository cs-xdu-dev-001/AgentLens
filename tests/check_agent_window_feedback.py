from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "frontend" / "react" / "src" / "components" / "agentWindowFeedback.js"
COMPONENT = ROOT / "frontend" / "react" / "src" / "components" / "AgentWindowFeedback.jsx"
APP = ROOT / "frontend" / "react" / "src" / "App.jsx"

assert MODULE.exists()
assert COMPONENT.exists()
assert '<AgentWindowFeedback />' in APP.read_text(encoding="utf-8")

script = f"""
import assert from 'node:assert/strict';
import {{agentWindowFeedback, buildAgentDiagnosticReport, shouldNotifyAgentWindow, agentWindowFaviconDataUrl}} from {MODULE.as_uri()!r};
assert.equal(agentWindowFeedback({{status: 'running'}}).state, 'running');
assert.equal(agentWindowFeedback({{status: 'waiting_approval'}}).state, 'waiting');
assert.equal(agentWindowFeedback({{runSummary: {{status: 'completed'}}}}).state, 'completed');
assert.equal(agentWindowFeedback({{status: 'failed'}}).state, 'failed');
assert.equal(agentWindowFeedback({{status: 'cancelled'}}).state, 'idle');
const previous = agentWindowFeedback({{id: 'run-1', status: 'running'}});
const completed = agentWindowFeedback({{id: 'run-1', status: 'completed'}});
assert.equal(shouldNotifyAgentWindow(previous, completed, {{visibilityState: 'hidden', hasFocus: false}}), true);
assert.equal(shouldNotifyAgentWindow(previous, completed, {{visibilityState: 'visible', hasFocus: true}}), false);
assert.match(agentWindowFaviconDataUrl('failed'), /^data:image\/svg\+xml,/);
const report = buildAgentDiagnosticReport({{
  id: 'run-safe',
  status: 'failed',
  failure: {{code: 'upstream_error', message: 'api_key=sk-do-not-copy'}},
  runSummary: {{completedSteps: 2, totalSteps: 3, toolCalls: 4}},
  prompt: 'private user prompt',
  trace: [{{kind: 'tool', name: 'web_search', status: 'failed', inputSummary: '{{"token":"hidden"}}'}}],
}}, {{now: 0}});
assert.match(report, /AgentLens脱敏诊断/);
assert.match(report, /进度: 2\/3/);
assert.match(report, /工具调用: 4/);
assert.doesNotMatch(report, /sk-do-not-copy|private user prompt|hidden/);
const unsafeIdentifiers = buildAgentDiagnosticReport({{
  id: '/home/alice/private/run-1',
  status: 'failed',
  failure: {{code: String.raw`C:\\Users\\alice\\secret.txt`}},
}}, {{now: 0}});
assert.doesNotMatch(unsafeIdentifiers, /\/home\/alice|C:\\\\Users|secret\.txt/);
"""
completed = subprocess.run(
    ["node", "--input-type=module", "--eval", script],
    cwd=ROOT,
    check=False,
    capture_output=True,
    text=True,
)
assert completed.returncode == 0, completed.stderr
component_source = COMPONENT.read_text(encoding="utf-8")
assert "knowflow:react-diagnostic-copy-request" in component_source
assert "脱敏诊断已复制" in component_source
assert "自动复制失败，已打开脱敏诊断" in component_source
assert 'role={"dialog"}' in component_source
assert "全选诊断" in component_source
print("agent window feedback checks passed")
