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


def check_workbench_keyboard_navigation_fixture() -> None:
    source = read(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx"
    )
    declaration = extract_function(source, "nextWorkbenchItemIndex")
    script = f"""
{declaration}
const result = {{
  empty: nextWorkbenchItemIndex(0, -1, "ArrowDown"),
  first: nextWorkbenchItemIndex(1000, -1, "ArrowUp"),
  next: nextWorkbenchItemIndex(1000, 400, "ArrowDown"),
  previous: nextWorkbenchItemIndex(1000, 400, "ArrowUp"),
  wrappedNext: nextWorkbenchItemIndex(1000, 999, "ArrowDown"),
  wrappedPrevious: nextWorkbenchItemIndex(1000, 0, "ArrowUp"),
  home: nextWorkbenchItemIndex(1000, 700, "Home"),
  end: nextWorkbenchItemIndex(1000, 2, "End"),
}};
console.log(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == {
        "empty": -1,
        "first": 0,
        "next": 401,
        "previous": 399,
        "wrappedNext": 0,
        "wrappedPrevious": 999,
        "home": 0,
        "end": 999,
    }


def check_skill_renderer_fixture() -> None:
    path = (
        "frontend/react/src/components/"
        "agentTracePresentation.js"
    )
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


def check_workspace_sandbox_renderer_fixture() -> None:
    module_path = (
        ROOT
        / "frontend"
        / "react"
        / "src"
        / "components"
        / "agentTracePresentation.js"
    ).as_uri()
    script = f"""
import {{
  traceKindLabel,
  traceStepFields,
  traceStepReason,
  traceStepTitle,
}} from {json.dumps(module_path)};
const workspaceFields = traceStepFields({{
  kind: "workspace",
  name: "write_workspace_file",
  status: "success",
  details: {{
    readOnly: false,
    destructive: true,
    secret: "must-not-render",
  }},
  inputSummary: {{ path: "src/main.py" }},
  outputSummary: {{ path: "src/main.py", writtenBytes: 42 }},
}});
const sandboxFields = traceStepFields({{
  kind: "sandbox",
  name: "run_sandbox_command",
  status: "success",
  details: {{
    readOnly: false,
    destructive: true,
    token: "must-not-render",
  }},
  inputSummary: {{ command: "pytest tests", timeout_seconds: 30 }},
  outputSummary: {{
    exit_code: 0,
    timed_out: false,
    stdout: "ok",
    stderr: "",
  }},
}});
const referenceStep = {{
  kind: "workspace",
  name: "workspace_references",
  status: "success",
  title: "已读取2个工作区文件，跳过1个",
  inputSummary: {{ files: ["README.md", "src/main.py", ".env"] }},
  outputSummary: {{
    loaded: ["README.md", "src/main.py"],
    skipped: [{{ path: ".env", code: "workspace_path_denied" }}],
  }},
}};
const referenceFields = traceStepFields(referenceStep);
const readable = {{
  kindLabel: traceKindLabel("workspace"),
  sandboxLabel: traceKindLabel("sandbox"),
  title: traceStepTitle({{
    kind: "workspace",
    name: "read_workspace_file",
    status: "success",
  }}),
  reason: traceStepReason({{ kind: "sandbox" }}),
  referenceTitle: traceStepTitle(referenceStep),
  referenceReason: traceStepReason(referenceStep),
}};
console.log(JSON.stringify({{ workspaceFields, sandboxFields, referenceFields, readable }}));
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
    assert result["workspaceFields"] == [
        {"label": "工具", "value": "写入工作区文件"},
        {"label": "权限", "value": "需要确认 · 可写"},
        {"label": "路径", "value": "src/main.py"},
        {"label": "写入字节", "value": "42"},
    ]
    assert result["sandboxFields"] == [
        {"label": "工具", "value": "沙箱命令"},
        {"label": "权限", "value": "需要确认 · 沙箱执行"},
        {"label": "命令", "value": "pytest tests"},
        {"label": "超时", "value": "30s"},
        {"label": "退出码", "value": "0"},
        {"label": "是否超时", "value": "否"},
        {"label": "标准输出", "value": "ok"},
    ]
    assert result["referenceFields"] == [
        {"label": "已读取", "value": "README.md、src/main.py"},
        {"label": "已跳过", "value": "1"},
    ]
    assert result["readable"] == {
        "kindLabel": "WORKSPACE",
        "sandboxLabel": "SANDBOX",
        "title": "读取工作区文件已完成",
        "reason": "在受限沙箱中执行命令，读写范围限定在当前用户工作区。",
        "referenceTitle": "已读取2个工作区文件，跳过1个",
        "referenceReason": "把用户明确引用的工作区文件作为受控上下文读取，不改变原始问题。",
    }


def check_agent_run_presentation_fixture() -> None:
    module_path = (
        ROOT
        / "frontend"
        / "react"
        / "src"
        / "components"
        / "agentRunPresentation.js"
    ).as_uri()
    script = f"""
import {{ agentWorkbenchDefaultTab, buildAgentDiffPresentation, buildAgentOperationPresentation, buildAgentRunPresentation, buildAgentToolOutputPresentation, buildAgentVerificationPresentation, mergeAgentArtifactUpdate, verificationTraceStepId }} from {json.dumps(module_path)};
const completed = buildAgentRunPresentation({{
  now: Date.parse("2026-08-12T00:00:03Z"),
  run: {{
    id: "run_fixture",
    status: "completed",
    startedAt: "2026-08-12T00:00:00Z",
    finishedAt: "2026-08-12T00:00:03Z",
    usage: {{ totalTokens: 1200 }},
    context: {{
      usedTokens: 72000,
      maxTokens: 96000,
      remainingTokens: 24000,
      usagePercent: 75,
      warningAtPercent: 75,
      shouldWarn: true,
      contextTrimmed: true,
    }},
    artifacts: [{{ artifactType: "file", path: "report.md" }}],
  }},
  trace: [
    {{ stepId: "root", kind: "agent", name: "agent_run", status: "success" }},
    {{ stepId: "model", kind: "model", name: "model_completion", status: "success" }},
    {{ stepId: "tool", kind: "tool", name: "web_search", status: "success" }},
  ],
}});
const waiting = buildAgentRunPresentation({{
  run: {{ id: "run_wait", status: "waiting_approval" }},
  trace: [{{
    stepId: "approval",
    kind: "approval",
    name: "tool_approval",
    status: "waiting",
  }}],
}});
const retrying = buildAgentRunPresentation({{
  now: Date.parse("2026-08-12T00:00:03Z"),
  run: {{
    id: "run_retry",
    status: "running",
    modelRetry: {{
      attempt: 2,
      maxRetries: 3,
      reason: "模型限流",
      retryAt: Date.parse("2026-08-12T00:00:10Z"),
    }},
  }},
  trace: [{{
    stepId: "model-retry",
    kind: "model",
    name: "model_completion",
    status: "running",
  }}],
}});
const compacted = buildAgentRunPresentation({{
  run: {{
    id: "run_compacted",
    goalSummary: "调研最新模型趋势",
    status: "completed",
    artifacts: [{{ artifactType: "file", path: "report.md" }}],
  }},
  trace: [
    {{ stepId: "root-2", kind: "agent", name: "agent_run", status: "success" }},
    {{ stepId: "model-2", kind: "model", name: "model_completion", status: "success" }},
    {{ stepId: "search-1", kind: "tool", name: "web_search", status: "success", durationMs: 100 }},
    {{ stepId: "search-2", kind: "tool", name: "web_search", status: "success", durationMs: 200 }},
    {{ stepId: "search-3", kind: "tool", name: "web_search", status: "success", durationMs: 300 }},
  ],
}});
const targeted = [
  {{ stepId: "write-a", kind: "workspace", name: "write_workspace_file", status: "success", inputSummary: {{ path: "src/a.py" }}, outputSummary: {{ writtenBytes: 12 }} }},
  {{ stepId: "write-b", kind: "workspace", name: "write_workspace_file", status: "success", inputSummary: {{ path: "src/b.py" }}, outputSummary: {{ writtenBytes: 20 }} }},
  {{ stepId: "fetch", kind: "tool", name: "web_fetch", status: "running", inputSummary: {{ url: "https://example.com/news?token=SECRET" }} }},
  {{ stepId: "model-only", kind: "model", name: "model_completion", status: "success" }},
].map(buildAgentOperationPresentation).filter(Boolean);
const planned = buildAgentRunPresentation({{
  run: {{
    id: "run-planned",
    status: "running",
    steps: [{{ id: "plan-1", kind: "plan", name: "inspect", title: "检查现状", status: "running" }}],
  }},
  trace: [
    {{ stepId: "plan-1-trace", kind: "plan", name: "inspect", status: "running", details: {{ planStepId: "plan-1" }} }},
    {{ stepId: "read-a", kind: "workspace", name: "read_workspace_file", status: "success", inputSummary: {{ path: "src/a.py", token: "SECRET" }} }},
  ],
}});
const verifications = buildAgentVerificationPresentation([
  {{ stepId: "check-ok", kind: "sandbox", name: "run_sandbox_command", status: "success", durationMs: 1200, inputSummary: {{ command: "npm test -- --token SECRET" }}, outputSummary: {{ exit_code: 0 }} }},
  {{ stepId: "build-failed", kind: "sandbox", name: "run_sandbox_command", status: "failed", inputSummary: {{ command: "npm run build" }}, outputSummary: {{ exit_code: 2 }} }},
  {{ stepId: "read-only", kind: "sandbox", name: "run_sandbox_command", status: "success", inputSummary: {{ command: "cat README.md" }} }},
]);
const verificationFocus = verificationTraceStepId(
  {{ id: "verification:call-build" }},
  [{{ stepId: "build-failed", details: {{ toolCallId: "call-build" }} }}],
);
const protocolVerifications = buildAgentVerificationPresentation(
  [{{ stepId: "legacy-secret", name: "run_sandbox_command", status: "success", inputSummary: {{ command: "npm test -- --token SECRET" }} }}],
  [{{
    id: "verification:protocol",
    kind: "check",
    tool: "git_diff_check",
    status: "passed",
    exitCode: 0,
    durationMs: 90,
    command: "git diff --check --token SECRET",
  }}],
);
const diffRows = buildAgentDiffPresentation(`diff --git a/src/app.js b/src/app.js
--- a/src/app.js
+++ b/src/app.js
@@ -3,2 +3,3 @@
 keep
-old value
+new value
+extra line`);
const artifactUpdate = mergeAgentArtifactUpdate(
  [{{ artifactId: "file:src/app.js", artifactType: "file", path: "src/app.js", operationId: "edit-app", addedLines: 2, reverted: false }}],
  {{ artifactId: "file:src/app.js", artifactType: "file", path: "src/app.js", operationId: "edit-app", reverted: true, changeStatus: "reverted" }},
);
const toolOutput = buildAgentToolOutputPresentation({{
  toolCallId: "shell-fixture",
  toolName: "run_sandbox_command",
  status: "failed",
  durationMs: 1280,
  arguments: {{ command: "npm test -- --token \\\"SECRET VALUE\\\"" }},
  output: {{
    stdout: "first line\\n\\u001b[31msecond line\\u001b[0m\\nvisible\\u202etext\\nAuthorization: Bearer abcdefghijklmnop",
    stderr: "apiKey=abcdefghijklmnop\\npassword: 'quoted secret value'\\nOPENAI_API_KEY=sk-openai-environment-secret\\nGITHUB_TOKEN=github-environment-secret\\nAWS_SECRET_ACCESS_KEY='aws environment secret'\\n<unsafe-tag>text only</unsafe-tag>",
    result: "-----BEGIN PRIVATE KEY-----\\nprivate-material\\n-----END PRIVATE KEY-----",
    exit_code: 2,
  }},
}});
const workbenchTabs = {{
  running: agentWorkbenchDefaultTab({{
    run: {{ status: "running" }},
    artifacts: [{{ path: "src/app.js" }}],
    references: [{{ url: "https://example.com" }}],
  }}),
  failed: agentWorkbenchDefaultTab({{
    run: {{ status: "failed" }},
    artifacts: [{{ path: "src/app.js" }}],
  }}),
  delivered: agentWorkbenchDefaultTab({{
    run: {{ status: "completed" }},
    artifacts: [{{ path: "src/app.js" }}],
    references: [{{ url: "https://example.com" }}],
  }}),
  researched: agentWorkbenchDefaultTab({{
    run: {{ status: "completed" }},
    references: [{{ url: "https://example.com" }}],
  }}),
  executed: agentWorkbenchDefaultTab({{
    run: {{ status: "completed" }},
    toolCalls: [{{ toolCallId: "tool-only" }}],
  }}),
  answered: agentWorkbenchDefaultTab({{
    run: {{ status: "completed" }},
  }}),
}};
console.log(JSON.stringify({{
  completed: {{
    active: completed.active,
    status: completed.status,
    progress: [completed.completed, completed.total],
    tokenLabel: completed.tokenLabel,
    toolCalls: completed.toolCalls,
    artifacts: completed.artifacts.length,
    context: completed.context,
  }},
  waiting: {{
    active: waiting.active,
    status: waiting.status,
  }},
  retrying: {{
    active: retrying.active,
    processSummary: retrying.processSummary,
    status: retrying.status,
  }},
  compacted: {{
    headline: compacted.headline,
    processSummary: compacted.processSummary,
    rows: compacted.rows.map((row) => ({{
      name: row.name,
      repeatCount: row.repeatCount,
      durationMs: row.durationMs,
    }})),
    toolCalls: compacted.toolCalls,
  }},
  targeted: targeted.map((row) => ({{ ...row, title: row.title, outcome: row.outcome }})),
  planned: {{
    hasPlan: planned.hasPlan,
    rows: planned.rows.map((row) => row.title),
    operations: planned.operations.map((row) => row.title),
  }},
  verifications,
  verificationFocus,
  protocolVerifications,
  diffRows,
  artifactUpdate,
  toolOutput,
  workbenchTabs,
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
    assert result["completed"] == {
        "active": False,
        "status": {
            "className": "success",
            "freshness": "已保存",
            "label": "已完成",
        },
        "progress": [1, 1],
        "tokenLabel": "1.2k tokens",
        "toolCalls": 1,
        "artifacts": 1,
        "context": {
            "label": "上下文已安全裁剪",
            "detail": "已保留系统规则和最近完整工具轮次",
            "percent": 75,
            "trimmed": True,
        },
    }
    assert result["waiting"] == {
        "active": True,
        "status": {
            "className": "waiting",
            "freshness": "等待",
            "label": "等待确认",
        },
    }
    assert result["retrying"] == {
        "active": True,
        "processSummary": "模型限流，7秒后重试（2/3）",
        "status": {
            "className": "waiting",
            "freshness": "自动恢复中",
            "label": "等待重试",
        },
    }
    assert result["compacted"] == {
        "headline": "调研最新模型趋势",
        "processSummary": "已完成并保存1个产物",
        "rows": [
            {
                "name": "web_search",
                "repeatCount": 3,
                "durationMs": 600,
            },
        ],
        "toolCalls": 3,
    }
    targeted = result["targeted"]
    assert [
        {"title": row["title"], "outcome": row["outcome"]}
        for row in targeted
    ] == [
        {"title": "已更新 src/a.py", "outcome": "12 B"},
        {"title": "已更新 src/b.py", "outcome": "20 B"},
        {"title": "正在读取网页 example.com/news", "outcome": ""},
    ]
    assert "SECRET" not in json.dumps(targeted)
    assert all("inputSummary" not in row for row in targeted)
    assert result["planned"] == {
        "hasPlan": True,
        "rows": ["检查现状"],
        "operations": ["已读取 src/a.py"],
    }
    assert result["verifications"] == [
        {
            "duration": "1s",
            "durationMs": 1200,
            "exitCode": 0,
            "id": "check-ok",
            "label": "测试",
            "status": "passed",
            "statusLabel": "通过",
            "tool": "npm test",
        },
        {
            "duration": "",
            "durationMs": None,
            "exitCode": 2,
            "id": "build-failed",
            "label": "构建",
            "status": "failed",
            "statusLabel": "失败",
            "tool": "npm run build",
        },
    ]
    assert "SECRET" not in json.dumps(result["verifications"])
    assert result["verificationFocus"] == "build-failed"
    assert result["protocolVerifications"] == [
        {
            "duration": "90ms",
            "durationMs": 90,
            "exitCode": 0,
            "id": "verification:protocol",
            "label": "差异检查",
            "status": "passed",
            "statusLabel": "通过",
            "tool": "git diff --check",
        },
    ]
    assert "SECRET" not in json.dumps(result["protocolVerifications"])
    assert result["diffRows"] == [
        {"kind": "meta", "oldLine": None, "newLine": None, "text": "diff --git a/src/app.js b/src/app.js"},
        {"kind": "meta", "oldLine": None, "newLine": None, "text": "--- a/src/app.js"},
        {"kind": "meta", "oldLine": None, "newLine": None, "text": "+++ b/src/app.js"},
        {"kind": "hunk", "oldLine": None, "newLine": None, "text": "@@ -3,2 +3,3 @@"},
        {"kind": "context", "oldLine": 3, "newLine": 3, "text": " keep"},
        {"kind": "remove", "oldLine": 4, "newLine": None, "text": "-old value"},
        {"kind": "add", "oldLine": None, "newLine": 4, "text": "+new value"},
        {"kind": "add", "oldLine": None, "newLine": 5, "text": "+extra line"},
    ]
    assert result["artifactUpdate"] == [
        {
            "artifactId": "file:src/app.js",
            "artifactType": "file",
            "path": "src/app.js",
            "operationId": "edit-app",
            "addedLines": 2,
            "reverted": True,
            "title": "src/app.js",
            "changeStatus": "reverted",
        }
    ]
    tool_output = result["toolOutput"]
    assert tool_output["id"] == "shell-fixture"
    assert tool_output["statusLabel"] == "失败"
    assert tool_output["statusTone"] == "danger"
    assert tool_output["exitCode"] == 2
    assert tool_output["latencyMs"] == 1280
    assert tool_output["command"] == "npm test -- --token=[已隐藏]"
    assert "first line\nsecond line" in tool_output["copyText"]
    assert "<unsafe-tag>text only</unsafe-tag>" in tool_output["copyText"]
    assert "\u001b" not in tool_output["copyText"]
    assert "\u202e" not in tool_output["copyText"]
    assert "SECRET VALUE" not in tool_output["copyText"]
    assert "quoted secret value" not in tool_output["copyText"]
    assert "sk-openai-environment-secret" not in tool_output["copyText"]
    assert "github-environment-secret" not in tool_output["copyText"]
    assert "aws environment secret" not in tool_output["copyText"]
    assert "abcdefghijklmnop" not in tool_output["copyText"]
    assert "private-material" not in tool_output["copyText"]
    assert "[私钥已隐藏]" in tool_output["copyText"]
    assert [section["label"] for section in tool_output["sections"]] == [
        "stdout",
        "stderr",
        "结果",
    ]
    assert result["workbenchTabs"] == {
        "running": "trace",
        "failed": "trace",
        "delivered": "artifacts",
        "researched": "evidence",
        "executed": "output",
        "answered": "trace",
    }


def check_evidence_presentation_fixture() -> None:
    module_url = (
        ROOT
        / "frontend/react/src/components/agentEvidencePresentation.js"
    ).resolve().as_uri()
    script = f"""
import {{ evidenceReferences }} from {json.dumps(module_url)};
const references = evidenceReferences({{
  artifacts: [
    {{
      artifactType: "reference",
      artifactId: "ref-url",
      url: "https://example.com/report?q=private&token=SECRET#section",
      score: 0.86,
    }},
    {{
      artifactType: "reference",
      chunkId: "chunk-1",
      filename: "安全报告.pdf",
      content: "正文不应进入证据带",
    }},
    {{ artifactType: "file", path: "src/app.js" }},
  ],
}});
console.log(JSON.stringify(references.map((item) => ({{
  id: item.id,
  label: item.label,
  score: item.score,
}}))));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    references = json.loads(result.stdout)
    assert references == [
        {"id": "ref-url", "label": "example.com/report", "score": 86},
        {"id": "chunk-1", "label": "安全报告.pdf", "score": None},
    ]
    serialized = json.dumps(references, ensure_ascii=False)
    for secret in ("private", "SECRET", "section", "正文不应进入证据带"):
        assert secret not in serialized


def check_trace_keyboard_navigation_fixture() -> None:
    module_url = (
        ROOT
        / "frontend/react/src/components/agentTraceNavigation.js"
    ).resolve().as_uri()
    script = f"""
import {{ matchesFocusScope, nextTraceStepId, resolveTreeSelectionId }} from {json.dumps(module_url)};
const ids = ["planning", "tool-failed", "answer"];
console.log(JSON.stringify({{
  down: nextTraceStepId(ids, "tool-failed", "ArrowDown"),
  wrapDown: nextTraceStepId(ids, "answer", "ArrowDown"),
  up: nextTraceStepId(ids, "tool-failed", "ArrowUp"),
  wrapUp: nextTraceStepId(ids, "planning", "ArrowUp"),
  home: nextTraceStepId(ids, "answer", "Home"),
  end: nextTraceStepId(ids, "planning", "End"),
  missing: nextTraceStepId(ids, "", "ArrowDown"),
  pinned: resolveTreeSelectionId(ids, "planning", "answer", true),
  automatic: resolveTreeSelectionId(ids, "planning", "answer", false),
  removed: resolveTreeSelectionId(ids, "removed", "answer", true),
  scoped: matchesFocusScope("workbench", "workbench"),
  foreignScope: matchesFocusScope("message", "workbench"),
}}));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "down": "answer",
        "wrapDown": "planning",
        "up": "planning",
        "wrapUp": "answer",
        "home": "planning",
        "end": "answer",
        "missing": "planning",
        "pinned": "planning",
        "automatic": "answer",
        "removed": "answer",
        "scoped": True,
        "foreignScope": False,
    }


def main() -> None:
    require(
        "frontend/react/src/controller/agentEvents.js",
        'name.startsWith("step.")',
        "Agent event projection branch",
    )
    require(
        "frontend/react/src/controller/agentEvents.js",
        "markAgentTraceInterrupted",
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
        "frontend/react/src/components/ChatMessages.jsx",
        "agent-turn-run-block",
        "stable per-turn run block",
    )
    require(
        "frontend/react/src/components/ChatMessages.jsx",
        "agent-turn-answer",
        "answer content separated from run block",
    )
    require(
        "frontend/react/src/components/ChatMessages.jsx",
        "memo(function AgentTurnRunBlock",
        "run block isolated from streaming answer rerenders",
    )
    for component in (
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "frontend/react/src/components/AgentRunSummary.jsx",
    ):
        require(
            component,
            "buildAgentRunPresentation",
            "shared run presentation projection",
        )
    require(
        "frontend/react/src/components/agentRunPresentation.js",
        "export function buildAgentRunPresentation",
        "single run presentation source",
    )
    require(
        "frontend/react/src/components/agentRunPresentation.js",
        "export function buildAgentVerificationPresentation",
        "truthful verification projection",
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
    detail = (
        "frontend/react/src/components/"
        "AgentTraceStepDetail.jsx"
    )
    presentation = (
        "frontend/react/src/components/"
        "agentTracePresentation.js"
    )
    require(
        view,
        "AgentTraceStepDetail",
        "inline trace detail component",
    )
    require(view, "aria-expanded={expanded}", "node expansion state")
    require(view, "userSelectedRef", "manual selection preservation")
    require(presentation, 'kind === "skill"', "Skill title branch")
    require(presentation, 'skill: "SKILL"', "Skill kind badge")
    for token in (
        "displayName",
        "version",
        "sourceKind",
        "requiredTools",
        "requiredMcp",
    ):
        require(presentation, token, f"safe Skill detail {token}")
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
        forbid(presentation, token, f"private Skill detail {token}")
    for token in (
        "step.details?.token",
        "step.details?.key",
        "step.details?.email",
        "JSON.stringify(step.details",
        "JSON.stringify(details",
        "summaryText(step.details",
    ):
        forbid(
            presentation,
            token,
            "whole/private Skill detail rendering",
        )
    require(
        presentation,
        "traceDetailsForDisplay(step)",
        "Skill and generic detail isolation",
    )
    require(
        detail,
        "traceStepFields(step)",
        "generic fields use isolated presentation",
    )
    require(
        detail,
        "traceStepReason(step)",
        "human-readable execution reason",
    )
    for token in (
        "step.details?.toolName",
        "step.details?.risk",
        "step.outputSummary?.decision",
        "kindLabels[step.kind] || step.kind",
        "statusLabels[step.status] || step.status",
    ):
        forbid(detail, token, "unsafe direct React child")
    require(
        presentation,
        "traceContextForDisplay(step)",
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
    for token in (
        "为什么执行",
        "复制详情",
        "管理长期记忆",
        "查看恢复操作",
    ):
        require(detail, token, f"interactive detail {token}")
    for token in (
        "traceStepReason",
        "traceStepFields",
        "traceCopyText",
        "traceStepTarget",
    ):
        require(
            presentation,
            token,
            f"trace presentation helper {token}",
        )
    require(detail, "memoryApi.retryOperation", "memory retry API")
    require(
        detail,
        "knowflow:react-agent-recovery-focus",
        "failed step returns to the centralized recovery surface",
    )
    require(detail, "run = null", "failed step recovery is scoped to a run")
    require(
        "frontend/react/src/components/AgentRecoveryPanel.jsx",
        "compactPublicText",
        "failed run reason is redacted before rendering",
    )
    require(
        "frontend/react/src/components/AgentRecoveryPanel.jsx",
        "failure.retryable === false",
        "non-retryable failures suppress retry actions",
    )
    require(
        detail,
        "knowflow:react-page-activated",
        "related page navigation",
    )
    forbid(
        detail,
        "JSON.stringify(step.details",
        "raw trace details rendering",
    )
    check_skill_renderer_fixture()
    check_evidence_presentation_fixture()
    check_trace_keyboard_navigation_fixture()
    check_workspace_sandbox_renderer_fixture()
    check_agent_run_presentation_fixture()
    check_workbench_keyboard_navigation_fixture()
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "AgentTraceView",
        "drawer trace view",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'data-workbench-tab={"output"}',
        "dedicated tool output tab",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "function ToolOutputPanel",
        "tool output console",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "messageIdRef",
        "drawer tool calls are scoped to the selected message",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "referencesRef.current = nextReferences",
        "drawer references stay current for lifecycle tab selection",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "selectLifecycleTab(nextRun)",
        "drawer follows run lifecycle until the user selects a tab",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'selectTab(requestedTab, { manual: true })',
        "manual workbench tab selection is preserved",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "handleTabKeyDown",
        "run workbench tabs expose keyboard navigation",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "knowflow:react-trace-focus",
        "workbench focus enters the critical trace step",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'event.key === "ArrowRight"',
        "run workbench tabs support forward arrow navigation",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'event.key === "ArrowLeft"',
        "run workbench tabs support reverse arrow navigation",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "focusWorkbenchItem",
        "run workbench lists share one keyboard navigation contract",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'event.key === "ArrowDown"',
        "run workbench tabs enter their active panel",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        '["1", "2", "3", "4"].includes(event.key)',
        "run workbench exposes direct numbered tab selection",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'aria-keyshortcuts={"1"}',
        "run workbench announces numbered tab shortcuts",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "if (event.defaultPrevented) return;",
        "nested workbench controls keep keyboard priority",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'data-workbench-item={"tool"}',
        "tool timeline participates in shared list navigation",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'data-workbench-item={"reference"}',
        "references participate in shared list navigation",
    )
    require(
        "frontend/react/src/components/AgentArtifactList.jsx",
        'data-workbench-item={"artifact"}',
        "artifacts participate in shared list navigation",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'tabIndex={activeTab === "trace" ? 0 : -1}',
        "run workbench tabs use roving tabindex",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'aria-labelledby={"agent-trace-tab"}',
        "run workbench panel is labelled by its active tab",
    )
    require(
        "frontend/react/src/controller/messageEvents.js",
        "updateReactMessageToolCalls",
        "tool calls persist on their assistant message",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'aria-pressed={autoFollow}',
        "tool output follow control",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "navigator.clipboard.writeText",
        "tool output copy action",
    )
    require(
        "frontend/react/src/components/agentRunPresentation.js",
        "publicAgentLogText",
        "tool output text sanitization",
    )
    forbid(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "dangerouslySetInnerHTML",
        "raw tool output HTML rendering",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "AgentRunSummary",
        "drawer live run summary",
    )
    require(
        "frontend/react/src/components/AgentArtifactList.jsx",
        "workspaceApi.diff",
        "lazy file diff loading",
    )
    require(
        "frontend/react/src/components/AgentArtifactList.jsx",
        "workspaceApi.undoChange",
        "conflict-safe file undo",
    )
    require(
        "frontend/react/src/components/AgentArtifactList.jsx",
        "publishReactAgentArtifactsUpdated",
        "artifact undo broadcasts its final state",
    )
    require(
        "frontend/react/src/components/ChatMessages.jsx",
        "knowflow:react-agent-artifacts-updated",
        "message artifact state follows undo broadcasts",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "knowflow:react-agent-artifacts-updated",
        "drawer artifact state follows undo broadcasts",
    )
    require(
        "frontend/react/src/components/AgentArtifactList.jsx",
        "AgentDiffView",
        "structured file diff presentation",
    )
    forbid(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "agent-task-capsule-artifacts",
        "duplicate inline artifact details",
    )
    forbid(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "function artifactChangeMeta",
        "obsolete inline artifact metrics",
    )
    forbid(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "操作记录",
        "duplicate inline operation log",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "rows.slice(0, 5)",
        "concise inline task rows",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "agent-task-capsule-summary",
        "readable inline task summary",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "AgentRecoveryPanel",
        "inline failed-run recovery",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "agent-context-pressure",
        "context pressure feedback",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        'handleOpen("artifacts")',
        "artifact drawer deep link",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "focusStepId",
        "inline task row deep link",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "agent-task-capsule-step-button",
        "keyboard accessible task rows",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "knowflow:react-agent-focus-updated",
        "inline task rows follow workbench focus",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "nextTraceStepId",
        "inline task rows share tree keyboard movement",
    )
    require(
        "frontend/react/src/components/AgentTraceStrip.jsx",
        "tabIndex={expanded && focusedStepId === itemId ? 0 : -1}",
        "inline task rows use roving tabindex",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "publishFocusStep",
        "workbench publishes its selected run step",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "knowflow:react-agent-focus-updated",
        "workbench focus update protocol",
    )
    require(
        "frontend/react/src/components/AgentTaskPlan.jsx",
        "onFocusStepChange",
        "plan tree reports focused steps",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "onFocusStepChange",
        "trace tree reports focused steps",
    )
    require(
        "frontend/styles.css",
        ".agent-task-capsule-steps li.selected",
        "inline selected step state",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "setFocusStepId",
        "drawer focused-step state",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "requestedId",
        "focused trace detail selection",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "nextTraceStepId",
        "trace tree keyboard movement projection",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "handleStepKeyDown",
        "trace tree keyboard interaction",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "tabIndex={focusedId === step.stepId ? 0 : -1}",
        "trace tree roving tabindex",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        'role={"tree"}',
        "trace navigation exposes tree semantics",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        'role={"treeitem"}',
        "trace steps expose treeitem semantics",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "onExitTree",
        "nested trace returns focus to its plan step",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "aria-level={step.depth + 1}",
        "trace tree exposes nesting depth",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        'event.key === "ArrowRight"',
        "trace detail expand key",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        'event.key === "ArrowLeft"',
        "trace detail collapse and parent key",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        'event.key === "Escape"',
        "trace detail Escape hierarchy",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "onDismiss",
        "nested trace dismissal contract",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "if (!atEnd && autoFollow) setAutoFollow(false);",
        "manual tool output scrolling pauses follow mode",
    )
    require(
        "frontend/react/src/components/AgentArtifactList.jsx",
        'event.key !== "Escape"',
        "artifact detail consumes Escape before the drawer",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "knowflow:react-trace-focus",
        "run workbench focuses its critical trace step",
    )
    require(
        "frontend/react/src/components/AgentTraceView.jsx",
        "focusedIdRef",
        "stable trace focus event subscription",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'detail: { scope: "workbench" }',
        "workbench focus event scope",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        "本轮交付",
        "post-answer delivery summary",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        'openRunPanel("artifacts")',
        "delivery card artifact deep link",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        "aria-expanded={expanded}",
        "inline delivery disclosure",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        "AgentArtifactList",
        "shared inline artifact list",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        "agent-delivery-verification",
        "post-answer verification evidence",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        "openVerification",
        "verification result deep links to its process step",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        "failedVerification",
        "failed verification is disclosed automatically",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        'label: "验证通过"',
        "delivery summary exposes verification success",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        'label: "未验证"',
        "delivery summary distinguishes missing verification",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        "查看失败步骤与恢复操作",
        "failed delivery deep links to recovery context",
    )
    require(
        "frontend/react/src/components/AgentDeliveryCard.jsx",
        "项已撤销",
        "delivery summary reports reverted changes",
    )
    require(
        "frontend/react/src/components/AgentArtifactList.jsx",
        "return `${url.origin}${url.pathname}`",
        "artifact URL query redaction",
    )
    require(
        "frontend/react/src/components/ChatMessages.jsx",
        "AgentDeliveryCard",
        "assistant delivery card placement",
    )
    require(
        "frontend/react/src/components/ChatMessages.jsx",
        "AgentEvidenceStrip",
        "assistant evidence strip placement",
    )
    require(
        "frontend/react/src/components/AgentEvidenceStrip.jsx",
        'activeTab: "evidence"',
        "evidence drawer deep link",
    )
    require(
        "frontend/react/src/components/agentEvidencePresentation.js",
        "url.hostname",
        "safe source label without URL query",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "event.detail?.references",
        "message-scoped reference handoff",
    )
    require(
        "frontend/react/src/components/AgentRecoveryPanel.jsx",
        "compact = false",
        "compact recovery presentation",
    )
    forbid(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        'setRun(event.detail?.run || null);\n      setActiveTab("trace");',
        "background run updates stealing the selected drawer tab",
    )
    forbid(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "agent-run-metrics",
        "duplicate run metric grid",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "agent-run-summary-meta",
        "compact run metadata",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "metrics || `${completed}/${total}`",
        "shared run metrics presentation",
    )
    require(
        "frontend/react/src/components/agentRunPresentation.js",
        'toolCalls ? `${toolCalls}次工具` : ""',
        "tool count in compact shared metrics",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "<h2 title={headline}>{headline}</h2>",
        "task goal as run workbench title",
    )
    forbid(
        "frontend/react/src/components/AgentRunSummary.jsx",
        '<h2>{"本次运行"}</h2>',
        "generic run heading hiding the real goal",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "{`引用 ${references.length}`}",
        "stable reference tab count",
    )
    require(
        "frontend/react/src/components/ChatEvidenceDrawer.jsx",
        "{`变更 ${artifacts.length}`}",
        "stable artifact tab count",
    )
    require(
        "frontend/react/src/controller/knowflowController.js",
        "state.autoOpenedRunId !== runId",
        "open the run workbench once per active run",
    )
    require(
        "frontend/react/src/controller/knowflowController.js",
        'dispatchReactEvent("knowflow:react-drawer-open")',
        "automatic run workbench reveal",
    )
    require(
        "frontend/react/src/controller/controllerState.js",
        "autoOpenedRunId",
        "run workbench reveal state",
    )
    require(
        "frontend/react/src/components/AgentRunSummary.jsx",
        "setInterval",
        "live elapsed timer",
    )
    require(
        "frontend/react/src/components/agentRunPresentation.js",
        'step.status === "waiting"',
        "waiting run status",
    )
    require(
        "frontend/react/src/components/agentRunPresentation.js",
        '["tool", "mcp", "sandbox", "workspace"].includes(item.kind)',
        "native and MCP tool count",
    )
    require(
        "frontend/react/src/components/agentRunPresentation.js",
        '"等待确认"',
        "approval waiting status",
    )
    require(
        "frontend/react/src/components/agentRunPresentation.js",
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
