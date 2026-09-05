import { useCallback, useEffect, useRef, useState } from "react";
import { CornerUpLeft, FileText, Folder } from "lucide-react";
import { workspaceApi } from "../api/client.js";
import { safeAgentText } from "../controller/agentEvents.js";
import { copyTextToClipboard } from "../controller/clipboard.js";
import { notifyError, notifyToast } from "./errorFeedback.js";
import { workspaceGitPresentation } from "./workspaceGitPresentation.js";
import { AgentArtifactList } from "./AgentArtifactList.jsx";


function parentPath(path) {
  const parts = String(path || "").split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}


function fileName(path) {
  return String(path || "").split("/").filter(Boolean).pop() || "文件";
}


function formatFileSize(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}


const RUN_STATUS_LABELS = Object.freeze({
  planning: "规划中",
  running: "运行中",
  waiting_approval: "等待确认",
  waiting_input: "等待输入",
  paused: "已暂停",
  checkpoint: "已暂停",
  completed: "已完成",
  succeeded: "已完成",
  success: "已完成",
  failed: "失败",
  error: "失败",
  cancelled: "已取消",
  canceled: "已取消",
  interrupted: "已中断",
});


function runIdOf(run) {
  return String(run?.id || run?.runId || "");
}


function runStatusOf(run) {
  return String(run?.runSummary?.status || run?.status || "").trim().toLowerCase();
}


function runStatusClass(status) {
  if (["completed", "succeeded", "success"].includes(status)) return "passed";
  if (["failed", "error"].includes(status)) return "failed";
  if (["cancelled", "canceled", "interrupted"].includes(status)) return "cancelled";
  return "running";
}


function runGoalOf(run) {
  const candidates = [
    run?.goal,
    run?.goalSummary,
    run?.runSummary?.goalSummary,
    run?.task,
    run?.title,
  ];
  for (const candidate of candidates) {
    const text = safeAgentText(candidate, 180);
    if (text) return text;
  }
  return "当前Agent运行";
}


function runArtifactsOf(run) {
  return Array.isArray(run?.artifacts)
    ? run.artifacts.filter((artifact) => artifact?.artifactType !== "reference")
    : [];
}


export function WorkbenchPage({
  active = false,
  run = null,
  messageId = "",
  onRunChange,
  onClearRun,
}) {
  const [status, setStatus] = useState(null);
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const [preview, setPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const fileInputRef = useRef(null);
  const previewPanelRef = useRef(null);
  const previewTriggerRef = useRef(null);
  const previewRequestRef = useRef(0);
  const [runCardExpanded, setRunCardExpanded] = useState(true);
  const runId = runIdOf(run);
  const runStatus = runStatusOf(run);
  const runArtifacts = runArtifactsOf(run);
  const hasRun = Boolean(runId);

  useEffect(() => {
    if (runId) setRunCardExpanded(true);
  }, [runId]);

  const closePreview = useCallback((restoreFocus = true) => {
    previewRequestRef.current += 1;
    setPreview(null);
    setPreviewLoading(false);
    setPreviewError("");
    if (restoreFocus) {
      window.requestAnimationFrame(() => previewTriggerRef.current?.focus());
    }
  }, []);

  const load = useCallback(async (nextPath = path) => {
    if (!active) return;
    setLoading(true);
    try {
      const nextStatus = await workspaceApi.status();
      setStatus(nextStatus);
      setPath(nextPath);
      if (!nextStatus?.enabled) {
        setEntries([]);
        return;
      }
      const listing = await workspaceApi.list(nextPath);
      setEntries(Array.isArray(listing?.entries) ? listing.entries : []);
    } catch (error) {
      setEntries([]);
      notifyError(error, "无法读取工作区");
    } finally {
      setLoading(false);
    }
  }, [active, path]);

  useEffect(() => {
    if (active) load(path);
  }, [active]);

  useEffect(() => {
    const handleArtifactsUpdated = (event) => {
      const eventRunId = String(event.detail?.runId || "");
      if (eventRunId && runId && eventRunId !== runId) return;
      if (active) void load(path);
    };
    window.addEventListener("knowflow:react-agent-artifacts-updated", handleArtifactsUpdated);
    return () => window.removeEventListener("knowflow:react-agent-artifacts-updated", handleArtifactsUpdated);
  }, [active, load, path, runId]);

  const navigateTo = (nextPath) => {
    closePreview(false);
    load(nextPath);
  };

  const openPreview = async (entry, trigger) => {
    const requestId = previewRequestRef.current + 1;
    previewRequestRef.current = requestId;
    previewTriggerRef.current = trigger || null;
    setPreview({
      path: entry.path,
      name: fileName(entry.path),
      size: Number(entry.size) || 0,
      mimeType: "",
      previewable: null,
      truncated: false,
      content: "",
    });
    setPreviewLoading(true);
    setPreviewError("");
    window.requestAnimationFrame(() => previewPanelRef.current?.focus({ preventScroll: true }));
    try {
      const result = await workspaceApi.preview(entry.path);
      if (previewRequestRef.current !== requestId) return;
      setPreview(result);
    } catch (error) {
      if (previewRequestRef.current !== requestId) return;
      setPreviewError(safeAgentText(error?.message, 240) || "无法预览文件");
      notifyError(error, "无法预览文件");
    } finally {
      if (previewRequestRef.current === requestId) setPreviewLoading(false);
    }
  };

  const handleCopyPreview = async () => {
    if (!preview?.previewable || !preview.content) return;
    try {
      await copyTextToClipboard(preview.content);
      notifyToast("文件内容已复制");
    } catch (error) {
      notifyError(error, "复制失败");
    }
  };

  const handleUpload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const target = [path, file.name].filter(Boolean).join("/");
    try {
      await workspaceApi.upload(target, file, false);
      notifyToast("文件已加入工作区");
      await load(path);
      window.dispatchEvent(new CustomEvent("knowflow:react-workspace-updated"));
    } catch (error) {
      notifyError(error, "上传失败");
    }
  };

  const handleDelete = async (entry) => {
    if (!window.confirm(`删除${entry.path}？`)) return;
    try {
      await workspaceApi.delete(entry.path);
      notifyToast("文件已删除");
      if (preview?.path === entry.path) closePreview(false);
      await load(path);
      window.dispatchEvent(new CustomEvent("knowflow:react-workspace-updated"));
    } catch (error) {
      notifyError(error, "删除失败");
    }
  };

  const handleRunArtifactChange = (nextArtifacts) => {
    if (!run) return;
    onRunChange?.({ ...run, artifacts: Array.isArray(nextArtifacts) ? nextArtifacts : [] });
  };

  const handleOpenRunInChat = () => {
    window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
      detail: { page: "chat" },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-trace-open", {
      detail: {
        messageId,
        run,
        activeTab: "artifacts",
      },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-open", {
      detail: { focus: true },
    }));
  };

  const crumbs = path.split("/").filter(Boolean);
  const projectInstructionPaths = Array.isArray(status?.projectInstructions?.sources)
    ? status.projectInstructions.sources
      .map((item) => safeAgentText(item?.path, 120))
      .filter(Boolean)
    : [];
  const git = workspaceGitPresentation(status);
  const gitStateClass = git.state === "conflict"
    ? "danger"
    : git.state === "behind"
      ? "warning"
      : git.state === "ready"
        ? "ready"
        : "";

  return (
    <section className={active ? "page active" : "page"} id="page-workspace">
      <div className="workspace-page workspace-browser">
        <header className="workspace-browser-header">
          <h1>工作区</h1>
          <div className="workspace-browser-actions">
            <button type="button" onClick={() => load(path)} disabled={loading}>刷新</button>
            <button className="primary" type="button" onClick={() => fileInputRef.current?.click()} disabled={!status?.enabled}>上传文件</button>
            <input ref={fileInputRef} type="file" hidden onChange={handleUpload} />
          </div>
        </header>

        <div className="workspace-runtime-strip" role="status">
          <span className={status?.enabled && status?.isolation === "user" ? "ready" : ""}>{status?.enabled && status?.isolation === "user" ? "隔离工作区已启用" : "工作区隔离状态未知"}</span>
          <span className={gitStateClass} title={git.title}>{git.repository ? `Git：${git.label}` : "未检测到Git仓库"}</span>
          <span className={status?.protectedPatterns?.length ? "ready" : ""}>{status?.protectedPatterns?.length ? "敏感路径受保护" : "敏感路径保护未知"}</span>
          <span className={status?.sandboxReady ? "ready" : ""}>{status?.sandboxReady ? "Linux沙箱可用" : "命令执行未启用"}</span>
          <span className={projectInstructionPaths.length ? "ready" : ""} title={projectInstructionPaths.join("、")}>{projectInstructionPaths.length ? `项目指令：${projectInstructionPaths.join("、")}` : "未发现项目指令"}</span>
        </div>

        <section className="workspace-boundary-card" aria-label="Agent可见范围">
          <div className="workspace-boundary-head">
            <strong>Agent可见范围</strong>
            <span className={status?.enabled ? "ready" : "warning"}>
              {status?.scopeLabel || (status?.enabled ? "当前用户隔离工作区" : "工作区已关闭")}
            </span>
          </div>
          <div className="workspace-boundary-grid">
            <div>
              <span>工作目录</span>
              <strong>{status?.cwdLabel || "工作区根目录"}</strong>
            </div>
            <div>
              <span>工作区类型</span>
              <strong>{({ project: "项目", directory: "目录", home: "HOME" }[status?.workspaceKind] || "受控目录")}</strong>
            </div>
            <div>
              <span>允许目录</span>
              <strong>{`${Math.max(0, Number(status?.allowedDirectoryCount) || 0)}个`}</strong>
            </div>
            <div>
              <span>保护规则</span>
              <strong>{status?.protectedPatterns?.length ? status.protectedPatterns.join(" · ") : "未知"}</strong>
            </div>
          </div>
        </section>

        {hasRun ? (
          <section
            className={`agent-delivery-card workspace-run-card${runCardExpanded ? " is-expanded" : ""}`}
            aria-label="当前运行产物"
          >
            <button
              type="button"
              onClick={() => setRunCardExpanded((value) => !value)}
              aria-expanded={runCardExpanded}
              aria-controls="workspace-run-card-body"
            >
              <svg className="agent-delivery-card-chevron" viewBox="0 0 20 20" aria-hidden="true" focusable="false">
                <path d="M7 4l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="agent-delivery-card-copy">
                <strong>当前运行</strong>
                <span title={runGoalOf(run)}>{runGoalOf(run)}</span>
              </span>
              <span className="agent-delivery-card-diff" aria-label="运行产物数量">
                {`${runArtifacts.length}个产物`}
              </span>
              <span className={`agent-delivery-card-status is-${runStatusClass(runStatus)}`} aria-live="polite">
                {RUN_STATUS_LABELS[runStatus] || "运行"}
              </span>
            </button>
            {runCardExpanded ? (
              <div className="agent-delivery-card-body workspace-run-card-body" id="workspace-run-card-body">
                <AgentArtifactList
                  artifacts={runArtifacts}
                  messageId={messageId}
                  runId={runId}
                  runStatus={runStatus}
                  onChange={handleRunArtifactChange}
                />
                <div className="workspace-run-actions">
                  <button type="button" onClick={handleOpenRunInChat}>在对话中打开</button>
                  <button type="button" onClick={() => onClearRun?.()}>隐藏运行</button>
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        <nav className="workspace-breadcrumb" aria-label="工作区路径">
          <button type="button" onClick={() => navigateTo("")}>工作区</button>
          {crumbs.map((part, index) => {
            const target = crumbs.slice(0, index + 1).join("/");
            return <button type="button" key={target} onClick={() => navigateTo(target)}>{part}</button>;
          })}
        </nav>

        <div className={`workspace-file-workarea${preview ? " has-preview" : ""}`}>
          <div className={`workspace-file-list${loading ? " is-loading" : ""}`} aria-busy={loading}>
            {loading && !entries.length ? (
              <div className="workspace-loading" role="status" aria-live="polite">
                <div className="workspace-loading-heading">
                  <span className="workspace-loading-dot" aria-hidden="true" />
                  <strong>正在读取工作区…</strong>
                </div>
                <div className="workspace-loading-skeleton" aria-hidden="true">
                  {[0, 1, 2, 3].map((index) => (
                    <div className="workspace-loading-row" key={index}>
                      <span className="workspace-loading-icon" />
                      <span className="workspace-loading-name" />
                      <span className="workspace-loading-meta" />
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
            {loading && entries.length ? (
              <div className="workspace-refreshing" role="status" aria-live="polite">
                <span className="workspace-loading-dot" aria-hidden="true" />
                <span>正在更新列表…</span>
              </div>
            ) : null}
            {path ? (
              <button className="workspace-file-row directory" type="button" onClick={() => navigateTo(parentPath(path))} disabled={loading}>
                <span className="workspace-file-icon" aria-hidden="true"><CornerUpLeft size={17} strokeWidth={1.7} /></span><strong>返回上一级</strong>
              </button>
            ) : null}
            {!loading && !entries.length ? (
              <div className="workspace-empty">
                <strong>工作区还没有文件</strong>
                <span>上传文件，或回到对话让Agent在这里生成产物。</span>
                <div className="workspace-empty-actions">
                  <button type="button" onClick={() => fileInputRef.current?.click()}>上传文件</button>
                  <button
                    type="button"
                    onClick={() => window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
                      detail: { page: "chat" },
                    }))}
                  >
                    去对话
                  </button>
                </div>
              </div>
            ) : null}
            {entries.map((entry) => {
              const selected = entry.kind === "file" && preview?.path === entry.path;
              return (
                <div className={`workspace-file-row${selected ? " is-active" : ""}`} key={entry.path}>
                  <button
                    className="workspace-file-open"
                    type="button"
                    onClick={(event) => entry.kind === "directory"
                      ? navigateTo(entry.path)
                      : openPreview(entry, event.currentTarget)}
                    disabled={loading}
                    aria-pressed={entry.kind === "file" ? selected : undefined}
                  >
                    <span className="workspace-file-icon" aria-hidden="true">
                      {entry.kind === "directory"
                        ? <Folder size={17} strokeWidth={1.7} />
                        : <FileText size={17} strokeWidth={1.7} />}
                    </span>
                    <strong>{fileName(entry.path)}</strong>
                    <span>{entry.kind === "directory" ? "文件夹" : "预览"}</span>
                  </button>
                  {entry.kind === "file" ? (
                    <div className="workspace-file-actions">
                      <a href={workspaceApi.downloadUrl(entry.path)}>下载</a>
                      <button className="workspace-file-delete" type="button" onClick={() => handleDelete(entry)} disabled={loading}>删除</button>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>

          {preview ? (
            <aside
              className="workspace-file-preview"
              ref={previewPanelRef}
              tabIndex={-1}
              aria-label={`${preview.name || fileName(preview.path)}文件预览`}
              onKeyDown={(event) => {
                if (event.key === "Escape") closePreview();
              }}
            >
              <header className="workspace-preview-header">
                <div className="workspace-preview-title">
                  <strong>{preview.name || fileName(preview.path)}</strong>
                  <span title={preview.path}>{preview.path}</span>
                </div>
                <div className="workspace-preview-actions">
                  <button type="button" onClick={handleCopyPreview} disabled={previewLoading || !preview.previewable || !preview.content}>复制</button>
                  <a href={workspaceApi.downloadUrl(preview.path)}>下载</a>
                  <button type="button" onClick={() => closePreview()} aria-label="关闭文件预览">关闭</button>
                </div>
              </header>
              <div className="workspace-preview-meta" role="status">
                <span>{previewLoading ? "正在识别文件" : preview.mimeType || "未知类型"}</span>
                <span>{formatFileSize(preview.size)}</span>
              </div>

              {previewLoading ? (
                <div className="workspace-preview-state" role="status" aria-live="polite">
                  <span className="workspace-loading-dot" aria-hidden="true" />
                  <strong>正在读取{preview.name || fileName(preview.path)}…</strong>
                </div>
              ) : previewError ? (
                <div className="workspace-preview-state error" role="alert">
                  <strong>预览失败</strong>
                  <span>{previewError}</span>
                  <button type="button" onClick={() => openPreview(preview, previewTriggerRef.current)}>重试</button>
                </div>
              ) : !preview.previewable ? (
                <div className="workspace-preview-state">
                  <strong>此文件不支持文本预览</strong>
                  <span>可直接下载后使用本地应用打开。</span>
                  <a href={workspaceApi.downloadUrl(preview.path)}>下载文件</a>
                </div>
              ) : preview.content ? (
                <div className="workspace-preview-content">
                  {preview.truncated ? <div className="workspace-preview-truncated">仅显示前256 KB，下载可查看完整文件。</div> : null}
                  <pre tabIndex={0}><code>{preview.content}</code></pre>
                </div>
              ) : (
                <div className="workspace-preview-state"><strong>文件为空</strong></div>
              )}
            </aside>
          ) : null}
        </div>
      </div>
    </section>
  );
}
