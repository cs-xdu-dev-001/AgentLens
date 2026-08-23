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
import {{agentWindowFeedback, shouldNotifyAgentWindow, agentWindowFaviconDataUrl}} from {MODULE.as_uri()!r};
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
"""
completed = subprocess.run(
    ["node", "--input-type=module", "--eval", script],
    cwd=ROOT,
    check=False,
    capture_output=True,
    text=True,
)
assert completed.returncode == 0, completed.stderr
print("agent window feedback checks passed")
