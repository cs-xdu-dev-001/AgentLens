import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


commands = read("frontend/react/src/components/composerCommands.js")
composer = read("frontend/react/src/components/ChatComposerForm.jsx")
flow = read("frontend/react/src/controller/chatFlow.js")

for needle in (
    'value: "/continue"',
    'value: "/retry"',
    'value: "/search"',
    'aliases: ["/find"]',
    'when: "continue"',
    'when: "retry"',
):
    assert needle in commands, f"missing contextual recovery command: {needle}"

for needle in (
    'knowflow:react-agent-run-action',
    'knowflow:react-transcript-search-open',
    'action === "continue" ? "resume" : "restart"',
    'handleQueueAction("resume")',
    "agentState.recoveryActions",
):
    assert needle in composer, f"missing composer recovery bridge: {needle}"

for needle in (
    "composerRecoveryContext",
    "projection?.recoveryActions",
    "messageId: message.messageId",
):
    assert needle in flow, f"missing recovery projection context: {needle}"

script = r'''
import { composerCommandSuggestions, parseComposerCommand, resolveComposerCommand } from "./frontend/react/src/components/composerCommands.js";

const values = (options = {}) => composerCommandSuggestions("", options).map((item) => item.value);
const idle = values();
for (const required of ["/help", "/reasoning", "/status"]) {
  if (!idle.includes(required)) throw new Error(`missing Web parity command: ${required}`);
}
if (values({ usage: { "/status": 3 } })[0] !== "/status") {
  throw new Error("frequently used commands are not promoted");
}
if (idle.includes("/continue") || idle.includes("/retry")) {
  throw new Error("idle composer exposed recovery commands");
}
const failed = values({ recoveryActions: ["continue", "retry"] });
if (!failed.includes("/continue") || !failed.includes("/retry")) {
  throw new Error("failed composer omitted recovery commands");
}
const queued = values({ queuePaused: true });
if (!queued.includes("/continue") || queued.includes("/retry")) {
  throw new Error("paused queue recovery commands are incorrect");
}
const retrySearch = composerCommandSuggestions("重新", { recoveryActions: ["retry"] });
if (retrySearch.length !== 1 || retrySearch[0].value !== "/retry") {
  throw new Error("localized recovery search failed");
}
const feedback = resolveComposerCommand("/bug");
if (feedback?.value !== "/feedback" || feedback?.action !== "feedback") {
  throw new Error("feedback alias did not resolve to the local diagnostic action");
}
if (resolveComposerCommand("/?")?.value !== "/help") {
  throw new Error("help alias did not resolve");
}
if (!composerCommandSuggestions("bug").some((item) => item.value === "/feedback")) {
  throw new Error("feedback alias is not searchable");
}
if (composerCommandSuggestions("renme")[0]?.value !== "/rename") {
  throw new Error("fuzzy command search did not recover a typo");
}
const rename = parseComposerCommand("/rename 发布复盘");
if (rename?.command?.value !== "/rename" || rename?.args !== "发布复盘") {
  throw new Error("session command arguments were not parsed");
}
const fork = parseComposerCommand("/fork 方案B");
if (fork?.command?.value !== "/branch" || fork?.args !== "方案B") {
  throw new Error("session command alias did not preserve arguments");
}
const search = parseComposerCommand("/find 发布状态");
if (search?.command?.value !== "/search" || search?.args !== "发布状态") {
  throw new Error("transcript search alias did not preserve arguments");
}
'''

result = subprocess.run(
    ["node", "--input-type=module", "-e", script],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=False,
)
if result.returncode:
    raise AssertionError(result.stderr or result.stdout)

print("frontend composer recovery checks passed")
