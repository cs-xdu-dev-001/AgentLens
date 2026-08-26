import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


commands = read("frontend/react/src/components/composerCommands.js")
composer = read("frontend/react/src/components/ChatComposerForm.jsx")
messages = read("frontend/react/src/components/ChatMessages.jsx")
drawer = read("frontend/react/src/components/ChatEvidenceDrawer.jsx")
flow = read("frontend/react/src/controller/chatFlow.js")

for needle in (
    'value: "/continue"',
    'value: "/retry"',
    'value: "/fix"',
    'value: "/search"',
    'aliases: ["/find"]',
    'when: "continue"',
    'when: "retry"',
    'when: "fix"',
    'value: "/copy"',
    'value: "/edit"',
    'value: "/rewind"',
    'value: "/diff"',
    'value: "/undo"',
):
    assert needle in commands, f"missing contextual recovery command: {needle}"

for needle in (
    'knowflow:react-agent-run-action',
    'knowflow:react-transcript-search-open',
    'action === "continue" ? "resume" : action === "fix" ? "fix" : "restart"',
    'handleQueueAction("resume")',
    "agentState.recoveryActions",
    'knowflow:react-message-command',
    'knowflow:react-agent-artifacts-open',
    'doubleEscapeWindowMs = 800',
    'lastEmptyEscapeAtRef',
    'handleQuickRewindEscape',
    'notifyCommandUnavailable("再按一次Esc，从最近问题创建新分支")',
    'className={"composer-follow-up"}',
    'acceptFollowUpSuggestion',
    'dismissFollowUpSuggestion',
    'aria-label={"忽略下一步建议"}',
):
    assert needle in composer, f"missing composer recovery bridge: {needle}"

assert 'data-message-action="${action}"' in messages
assert 'knowflow:react-message-command' in messages
assert '["copy", "edit", "retry", "rewind"]' in messages
assert 'knowflow:react-agent-artifacts-open' in drawer

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
for (const required of ["/help", "/reasoning", "/status", "/copy", "/edit", "/rewind", "/diff", "/undo"]) {
  if (!idle.includes(required)) throw new Error(`missing Web parity command: ${required}`);
}
if (!idle.includes("/compact")) {
  throw new Error("Web composer omitted manual context compaction");
}
if (values({ usage: { "/status": 3 } })[0] !== "/status") {
  throw new Error("frequently used commands are not promoted");
}
if (idle.includes("/continue") || idle.includes("/retry") || idle.includes("/fix")) {
  throw new Error("idle composer exposed recovery commands");
}
const failed = values({ recoveryActions: ["continue", "retry", "fix"] });
if (!failed.includes("/continue") || !failed.includes("/retry") || !failed.includes("/fix")) {
  throw new Error("failed composer omitted recovery commands");
}
const queued = values({ queuePaused: true });
if (!queued.includes("/continue") || queued.includes("/retry") || queued.includes("/fix")) {
  throw new Error("paused queue recovery commands are incorrect");
}
const retrySearch = composerCommandSuggestions("重新", { recoveryActions: ["retry"] });
if (retrySearch.length !== 1 || retrySearch[0].value !== "/retry") {
  throw new Error("localized recovery search failed");
}
const fixSearch = composerCommandSuggestions("分析错误", { recoveryActions: ["fix"] });
if (fixSearch.length !== 1 || fixSearch[0].value !== "/fix") {
  throw new Error("localized fix recovery search failed");
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
const compact = parseComposerCommand("/compact 优先保留工作区边界");
if (compact?.command?.action !== "session-compact" || compact?.args !== "优先保留工作区边界") {
  throw new Error("context compaction command did not preserve instructions");
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
