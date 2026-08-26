import { useCallback, useEffect, useRef, useState } from "react";
import { workspaceApi } from "../api/client.js";
import { safeAgentText } from "../controller/agentEvents.js";
import { notifyError, notifyToast } from "./errorFeedback.js";


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
          <span className={status?.enabled ? "ready" : ""}>{status?.enabled ? "工作区已启用" : "工作区未启用"}</span>
          <span className={status?.isolation === "user" ? "ready" : ""}>{status?.isolation === "user" ? "仅当前用户可见" : "隔离状态未知"}</span>
          <span className={status?.protectedPatterns?.length ? "ready" : ""}>{status?.protectedPatterns?.length ? "敏感路径受保护" : "敏感路径保护未知"}</span>
          <span className={status?.sandboxReady ? "ready" : ""}>{status?.sandboxReady ? "Linux沙箱可用" : "命令执行未启用"}</span>
          <span className={projectInstructionPaths.length ? "ready" : ""} title={projectInstructionPaths.join("、")}>{projectInstructionPaths.length ? `项目指令：${projectInstructionPaths.join("、")}` : "未发现项目指令"}</span>
        </div>

        <nav className="workspace-breadcrumb" aria-label="工作区路径">
          <button type="button" onClick={() => load("")}>工作区</button>
          {crumbs.map((part, index) => {
            const target = crumbs.slice(0, index + 1).join("/");
            return <button type="button" key={target} onClick={() => load(target)}>{part}</button>;
          })}
        </nav>

        <div className="workspace-file-list" aria-busy={loading}>
          {path ? (
            <button className="workspace-file-row directory" type="button" onClick={() => load(parentPath(path))}>
              <span className="workspace-file-icon">↰</span><strong>返回上一级</strong>
            </button>
          ) : null}
          {!loading && !entries.length ? <div className="workspace-empty">工作区为空。上传文件，或让Agent在这里生成产物。</div> : null}
          {entries.map((entry) => (
            <div className="workspace-file-row" key={entry.path}>
              <button className="workspace-file-open" type="button" onClick={() => entry.kind === "directory" ? load(entry.path) : window.location.assign(workspaceApi.downloadUrl(entry.path))}>
                <span className="workspace-file-icon">{entry.kind === "directory" ? "▢" : "·"}</span>
                <strong>{entry.path.split("/").pop()}</strong>
                <span>{entry.kind === "directory" ? "文件夹" : "下载"}</span>
              </button>
              {entry.kind === "file" ? <button className="workspace-file-delete" type="button" onClick={() => handleDelete(entry)}>删除</button> : null}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
