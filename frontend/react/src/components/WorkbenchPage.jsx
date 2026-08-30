import { useCallback, useEffect, useRef, useState } from "react";
import { workspaceApi } from "../api/client.js";
import { safeAgentText } from "../controller/agentEvents.js";
import { notifyError, notifyToast } from "./errorFeedback.js";
import { workspaceGitPresentation } from "./workspaceGitPresentation.js";


function parentPath(path) {
  const parts = String(path || "").split("/").filter(Boolean);
  parts.pop();
  return parts.join("/");
}


export function WorkbenchPage({ active = false }) {
  const [status, setStatus] = useState(null);
  const [path, setPath] = useState("");
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(false);
  const fileInputRef = useRef(null);

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
      await load(path);
      window.dispatchEvent(new CustomEvent("knowflow:react-workspace-updated"));
    } catch (error) {
      notifyError(error, "删除失败");
    }
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

        <nav className="workspace-breadcrumb" aria-label="工作区路径">
          <button type="button" onClick={() => load("")}>工作区</button>
          {crumbs.map((part, index) => {
            const target = crumbs.slice(0, index + 1).join("/");
            return <button type="button" key={target} onClick={() => load(target)}>{part}</button>;
          })}
        </nav>

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
            <button className="workspace-file-row directory" type="button" onClick={() => load(parentPath(path))} disabled={loading}>
              <span className="workspace-file-icon">↰</span><strong>返回上一级</strong>
            </button>
          ) : null}
          {!loading && !entries.length ? <div className="workspace-empty">工作区为空。上传文件，或让Agent在这里生成产物。</div> : null}
          {entries.map((entry) => (
            <div className="workspace-file-row" key={entry.path}>
              <button className="workspace-file-open" type="button" onClick={() => entry.kind === "directory" ? load(entry.path) : window.location.assign(workspaceApi.downloadUrl(entry.path))} disabled={loading}>
                <span className="workspace-file-icon">{entry.kind === "directory" ? "▢" : "·"}</span>
                <strong>{entry.path.split("/").pop()}</strong>
                <span>{entry.kind === "directory" ? "文件夹" : "下载"}</span>
              </button>
              {entry.kind === "file" ? <button className="workspace-file-delete" type="button" onClick={() => handleDelete(entry)} disabled={loading}>删除</button> : null}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
