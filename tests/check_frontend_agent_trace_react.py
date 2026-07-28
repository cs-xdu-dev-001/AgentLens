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
            extract_object_const(source, "skillSourceLabels"),
            extract_function(source, "skillDisplayName"),
            extract_function(source, "safeDependencyNames"),
            extract_function(source, "skillDetailsForDisplay"),
            extract_function(source, "traceStatusClass"),
            extract_function(source, "traceStepTitle"),
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
console.log(JSON.stringify({{
  titles,
  fallbacks,
  sources,
  statusClasses,
  details: skillDetailsForDisplay(fixture),
  unsafeDetails,
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
        "sourceKind": "未知",
        "requiredTools": ["valid-tool"],
        "requiredMcp": [],
    }


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
    require(view, 'step.kind === "skill"', "Skill title branch")
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
        "JSON.stringify(selected.details",
        "JSON.stringify(details",
        "summaryText(selected.details",
    ):
        forbid(view, token, "whole/private Skill detail rendering")
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
