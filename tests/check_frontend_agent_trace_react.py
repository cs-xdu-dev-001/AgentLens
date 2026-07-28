import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(path: str, token: str, label: str) -> None:
    assert token in read(path), (
        f"Missing {label}: {path} -> {token}"
    )


def forbid(path: str, token: str, label: str) -> None:
    assert token not in read(path), (
        f"Unexpected {label}: {path} -> {token}"
    )


def extract_function(source: str, name: str) -> str:
    match = re.search(
        rf"(?:export\s+)?function\s+{re.escape(name)}\s*\(",
        source,
    )
    assert match, f"Missing JavaScript function: {name}"
    opening = source.find("{", match.end())
    assert opening >= 0, f"Missing function body: {name}"
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return re.sub(
                    r"^export\s+",
                    "",
                    source[match.start():index + 1],
                )
    raise AssertionError(f"Unclosed JavaScript function: {name}")


def extract_object_const(source: str, name: str) -> str:
    match = re.search(
        rf"const\s+{re.escape(name)}\s*=\s*\{{",
        source,
    )
    assert match, f"Missing JavaScript object constant: {name}"
    end = source.find("};", match.end())
    assert end >= 0, f"Unclosed JavaScript object constant: {name}"
    return source[match.start():end + 2]


def check_skill_renderer_fixture() -> None:
    path = "frontend/react/src/components/AgentTraceView.jsx"
    source = read(path)
    declarations = "\n".join(
        [
            extract_object_const(source, "kindLabels"),
            extract_object_const(source, "nameLabels"),
            extract_object_const(source, "statusLabels"),
            extract_object_const(source, "skillSourceLabels"),
            extract_function(source, "safeText"),
            extract_function(source, "mappedLabel"),
            extract_function(source, "skillDisplayName"),
            extract_function(source, "safeDependencyNames"),
            extract_function(source, "skillDetailsForDisplay"),
            extract_function(source, "summaryText"),
            extract_function(source, "traceDetailsForDisplay"),
            extract_function(source, "normalizeTraceStatus"),
            extract_function(source, "traceStatusClass"),
            extract_function(source, "displayName"),
            extract_function(source, "traceKindLabel"),
            extract_function(source, "traceStatusLabel"),
            extract_function(source, "traceDurationLabel"),
            extract_function(source, "traceStepTitle"),
            extract_function(source, "mcpServerName"),
            extract_function(source, "traceContextForDisplay"),
        ]
    )
    fixture = {
        "kind": "skill",
        "status": "success",
        "details": {
            "displayName": "研究助理",
            "version": "1.2.3",
            "sourceKind": "builtin",
            "requiredTools": ["web_search", "reader"],
            "requiredMcp": ["notion"],
            "systemMessage": "SECRET system",
            "system_message": "SECRET snake",
            "body": "SECRET body",
            "instructions": "SECRET instructions",
            "rawManifest": {"secret": True},
            "manifest": {"secret": True},
            "packagePath": "C:/private/package",
            "path": "C:/private",
            "localPath": "C:/private/local",
            "token": "secret-token",
            "key": "secret-key",
            "email": "private@example.com",
        },
    }
    script = f"""
{declarations}
const fixture = {json.dumps(fixture, ensure_ascii=False)};
const statuses = ["running", "success", "completed", "failed", "error"];
const titles = statuses.map((status) => traceStepTitle({{
  ...fixture,
  status,
}}));
const fallbacks = statuses.map((status) => traceStepTitle({{
  kind: "skill",
  status,
  details: {{}},
}}));
const sources = ["builtin", "personal", "github", "upload"].map(
  (sourceKind) => skillDetailsForDisplay({{
    details: {{ ...fixture.details, sourceKind }},
  }}).sourceKind,
);
const missingSource = skillDetailsForDisplay({{
  details: {{ ...fixture.details, sourceKind: undefined }},
}}).sourceKind;
const unknownSource = skillDetailsForDisplay({{
  details: {{ ...fixture.details, sourceKind: "unknown" }},
}}).sourceKind;
const statusClasses = statuses.map(traceStatusClass);
const unsafeDetails = skillDetailsForDisplay({{
  details: {{
    displayName: {{ unsafe: true }},
    version: 7,
    sourceKind: "other",
    requiredTools: [
      " valid-tool ",
      "",
      "   ",
      null,
      42,
      {{ unsafe: true }},
    ],
    requiredMcp: "not-an-array",
    extra: "must not escape the whitelist",
  }},
}});
const skillTraceDetails = traceDetailsForDisplay({{
  ...fixture,
  inputSummary: {{
    systemMessage: "SECRET input system",
    path: "C:/private/input",
    token: "secret-input-token",
  }},
  outputSummary: {{
    body: "SECRET output body",
    manifest: {{ key: "secret-output-key" }},
    email: "private@example.com",
  }},
  errorCode: "SECRET_ERROR_CODE",
}});
const toolTraceDetails = traceDetailsForDisplay({{
  kind: "tool",
  inputSummary: "tool input",
  outputSummary: "tool output",
  errorCode: "TOOL_ERROR",
}});
const unsafeStep = {{
  kind: {{ secret: "kind" }},
  status: ["SECRET status"],
  name: {{ secret: "name" }},
  details: {{
    serverName: {{ secret: "server" }},
    toolName: ["SECRET tool"],
    risk: {{ secret: "risk" }},
  }},
  inputSummary: {{ token: "SECRET input" }},
  outputSummary: {{
    decision: {{ secret: "decision" }},
    path: "C:/private/output",
  }},
  errorCode: {{ key: "SECRET error" }},
}};
const unsafeRenderable = {{
  kindLabel: traceKindLabel(unsafeStep.kind),
  statusLabel: traceStatusLabel(unsafeStep.status),
  statusClass: traceStatusClass(unsafeStep.status),
  duration: traceDurationLabel({{ secret: "duration" }}),
  title: traceStepTitle(unsafeStep),
  context: traceContextForDisplay(unsafeStep),
  details: traceDetailsForDisplay(unsafeStep),
}};
const safeScalars = [
  safeText("text", "fallback"),
  safeText(7, "fallback"),
  safeText(false, "fallback"),
  safeText({{ secret: true }}, "fallback"),
];
const prototypeKeys = {{
  kindLabel: traceKindLabel("__proto__"),
  statusLabel: traceStatusLabel("constructor"),
  displayName: displayName({{ name: "toString" }}),
  sourceKind: skillDetailsForDisplay({{
    details: {{ sourceKind: "__proto__" }},
  }}).sourceKind,
}};
const normalContext = traceContextForDisplay({{
  kind: "mcp",
  name: "mcp__notion__search",
  details: {{
    serverName: "notion",
    toolName: "search",
    risk: "write",
  }},
  outputSummary: {{ decision: "allow" }},
}});
const completedSteps = [
  {{ kind: "skill", status: "completed", details: fixture.details }},
  {{ kind: "agent", name: "agent_run", status: "completed" }},
  {{ kind: "model", name: "model_completion", status: "completed" }},
  {{ kind: "tool", name: "web_search", status: "completed" }},
  {{ kind: "tool", name: "calculator", status: "completed" }},
  {{ kind: "mcp", name: "notion_search", status: "completed" }},
  {{ kind: "approval", status: "completed" }},
].map((step) => ({{
  title: traceStepTitle(step),
  statusClass: traceStatusClass(step.status),
}}));
const errorSteps = [
  {{ kind: "skill", status: "error", details: fixture.details }},
  {{ kind: "agent", name: "agent_run", status: "error" }},
  {{ kind: "model", name: "model_completion", status: "failed" }},
  {{ kind: "tool", name: "web_search", status: "error" }},
  {{ kind: "tool", name: "calculator", status: "failed" }},
].map((step) => traceStepTitle(step));
const runningSteps = [
  {{ kind: "skill", status: "running", details: fixture.details }},
  {{ kind: "agent", name: "agent_run", status: "running" }},
  {{ kind: "model", name: "model_completion", status: "running" }},
  {{ kind: "tool", name: "web_search", status: "running" }},
  {{ kind: "approval", status: "running" }},
].map((step) => traceStepTitle(step));
console.log(JSON.stringify({{
  titles,
  fallbacks,
  sources,
  missingSource,
  unknownSource,
  statusClasses,
  details: skillDetailsForDisplay(fixture),
  unsafeDetails,
  skillTraceDetails,
  toolTraceDetails,
  unsafeRenderable,
  safeScalars,
  prototypeKeys,
  normalContext,
  completedSteps,
  errorSteps,
  runningSteps,
}}));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT / "frontend",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["titles"] == [
        "正在激活 研究助理",
        "已激活 研究助理",
        "已激活 研究助理",
        "Skill 激活失败",
        "Skill 激活失败",
    ]
    assert result["fallbacks"] == [
        "正在激活 Skill",
        "已激活 Skill",
        "已激活 Skill",
        "Skill 激活失败",
        "Skill 激活失败",
    ]
    assert result["sources"] == ["内置", "个人", "个人", "个人"]
    assert result["missingSource"] == "个人"
    assert result["unknownSource"] == "个人"
    assert result["statusClasses"] == [
        "running",
        "success",
        "success",
        "failed",
        "failed",
    ]
    assert result["details"] == {
        "displayName": "研究助理",
        "version": "1.2.3",
        "sourceKind": "内置",
        "requiredTools": ["web_search", "reader"],
        "requiredMcp": ["notion"],
    }
    assert result["unsafeDetails"] == {
        "displayName": "Skill",
        "version": "无",
        "sourceKind": "个人",
        "requiredTools": ["valid-tool"],
        "requiredMcp": [],
    }
    assert result["skillTraceDetails"] == {
        "skillDetails": {
            "displayName": "研究助理",
            "version": "1.2.3",
            "sourceKind": "内置",
            "requiredTools": ["web_search", "reader"],
            "requiredMcp": ["notion"],
        },
        "inputSummary": None,
        "outputSummary": None,
        "errorCode": None,
    }
    assert result["toolTraceDetails"] == {
        "skillDetails": None,
        "inputSummary": "tool input",
        "outputSummary": "tool output",
        "errorCode": "TOOL_ERROR",
    }
    assert result["unsafeRenderable"] == {
        "kindLabel": "STEP",
        "statusLabel": "",
        "statusClass": "",
        "duration": "…",
        "title": "步骤",
        "context": {
            "serverName": "MCP",
            "toolName": "步骤",
            "risk": None,
            "decision": None,
        },
        "details": {
            "skillDetails": None,
            "inputSummary": "无",
            "outputSummary": "无",
            "errorCode": None,
        },
    }
    assert result["safeScalars"] == ["text", "7", "false", "fallback"]
    assert result["prototypeKeys"] == {
        "kindLabel": "__proto__",
        "statusLabel": "constructor",
        "displayName": "toString",
        "sourceKind": "个人",
    }
    assert result["normalContext"] == {
        "serverName": "notion",
        "toolName": "search",
        "risk": "write",
        "decision": "allow",
    }
    assert result["completedSteps"] == [
        {"title": "已激活 研究助理", "statusClass": "success"},
        {"title": "Agent处理完成", "statusClass": "success"},
        {"title": "模型步骤完成", "statusClass": "success"},
        {"title": "联网搜索完成", "statusClass": "success"},
        {"title": "calculator已完成", "statusClass": "success"},
        {"title": "notion search已完成", "statusClass": "success"},
        {"title": "已允许工具执行", "statusClass": "success"},
    ]
    assert result["errorSteps"] == [
        "Skill 激活失败",
        "Agent处理失败",
        "模型调用失败",
        "联网搜索失败",
        "calculator失败",
    ]
    assert result["runningSteps"] == [
        "正在激活 研究助理",
        "Agent正在处理",
        "模型正在分析",
        "正在联网搜索",
        "等待工具确认",
    ]


def main() -> None:
    require(
        "frontend/react/src/controller/chatFlow.js",
        'eventPayload.type === "agent_step"',
        "Agent SSE branch",
    )
    require(
        "frontend/react/src/controller/chatFlow.js",
        "markTraceInterrupted",
        "interrupted run terminal state",
    )
    require(
        "frontend/react/src/controller/chatFlow.js",
        "message.trace",
        "history trace restore",
    )
    require(
        "frontend/react/src/controller/messageEvents.js",
        "updateReactMessageTrace",
        "message trace bridge",
    )
    require(
        "frontend/react/src/components/ChatMessages.jsx",
        "AgentTraceStrip",
        "message status strip",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "parentId",
        "nested trace protocol",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        'aria-current={',
        "current step accessibility",
    )
    view = "frontend/react/src/components/AgentTraceView.jsx"
    require(view, 'kind === "skill"', "Skill title branch")
    require(view, 'skill: "SKILL"', "Skill kind badge")
    for token in (
        "displayName",
        "version",
        "sourceKind",
        "requiredTools",
        "requiredMcp",
    ):
        require(view, token, f"safe Skill detail {token}")
    for token in (
        "systemMessage",
        "system_message",
        "body",
        "instructions",
        "rawManifest",
        "manifest",
        "packagePath",
        "localPath",
    ):
        forbid(view, token, f"private Skill detail {token}")
    for token in (
        "selected.details?.token",
        "selected.details?.key",
        "selected.details?.email",
        "summaryText(selected.inputSummary",
        "summaryText(selected.outputSummary",
        "selected.errorCode",
        "JSON.stringify(selected.details",
        "JSON.stringify(details",
        "summaryText(selected.details",
    ):
        forbid(view, token, "whole/private Skill detail rendering")
    require(
        view,
        "traceDetailsForDisplay(selected)",
        "Skill and generic detail isolation",
    )
    require(
        view,
        "selectedDetails.inputSummary",
        "generic input reads isolated detail",
    )
    require(
        view,
        "selectedDetails.outputSummary",
        "generic output reads isolated detail",
    )
    for token in (
        "selected.details?.toolName",
        "selected.details?.risk",
        "selected.outputSummary?.decision",
        "kindLabels[step.kind] || step.kind",
        "statusLabels[step.status] || step.status",
    ):
        forbid(view, token, "unsafe direct React child")
    require(
        view,
        "traceContextForDisplay(selected)",
        "safe MCP and approval context",
    )
    require(
        view,
        "traceKindLabel(step.kind)",
        "safe kind badge fallback",
    )
    require(
        view,
        "traceStatusLabel(step.status)",
        "safe status fallback",
    )
    check_skill_renderer_fixture()
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "AgentTraceView",
        "drawer trace view",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "AgentRunSummary",
        "drawer live run summary",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "当前进度",
        "run progress metric",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "已用时间",
        "run elapsed metric",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "工具调用",
        "run tool count metric",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "setInterval",
        "live elapsed timer",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        'step.status === "waiting"',
        "waiting run status",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        'step.kind === "tool" || step.kind === "mcp"',
        "native and MCP tool count",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        '"等待确认"',
        "approval waiting status",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        '"已取消"',
        "cancelled run status",
    )
    require(
        "frontend/react/src/App.jsx",
        "knowflow:react-drawer-open",
        "programmatic drawer open",
    )
    require(
        "frontend/styles.css",
        "prefers-reduced-motion",
        "reduced motion support",
    )
    require(
        "frontend/react/src/styles.css",
        "text-overflow: ellipsis",
        "long Skill name containment",
    )
    require(
        "frontend/react/src/styles.css",
        "overflow-wrap: anywhere",
        "long Skill dependency wrapping",
    )
    print(
        "React agent trace surfaces preserve live, "
        "nested, and replay states"
    )


if __name__ == "__main__":
    main()
