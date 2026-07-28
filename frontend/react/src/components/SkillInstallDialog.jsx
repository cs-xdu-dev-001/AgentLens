import { useEffect, useRef, useState } from "react";
import { skillApi } from "../api/client.js";
import { notifyToast } from "./errorFeedback.js";

const githubPattern = /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+\/?$/i;
const focusableSelector =
  'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

const focusableElements = (container) =>
  Array.from(container?.querySelectorAll(focusableSelector) || []).filter(
    (element) => !element.hidden && element.getAttribute("aria-hidden") !== "true",
  );

const trapFocus = (event, container) => {
  if (event.key !== "Tab") return;
  const elements = focusableElements(container);
  if (!elements.length) return;
  const first = elements[0];
  const last = elements[elements.length - 1];
  const activeElement = document.activeElement;
  if (event.shiftKey && (activeElement === first || !container.contains(activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (activeElement === last || !container.contains(activeElement))) {
    event.preventDefault();
    first.focus();
  }
};

const bytesLabel = (value) => {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "未提供";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const dependencyLabel = (preview) => {
  const missing = [
    ...(preview?.missingTools || []),
    ...(preview?.missingMcp || []),
  ];
  return missing.length ? missing.join("、") : "依赖完整";
};

const dispatchSkillsUpdated = (skill) => {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-skills-updated", {
      detail: { skill },
    }),
  );
};

export function SkillInstallDialog({ open = false, onClose, onInstalled }) {
  const [sourceTab, setSourceTab] = useState("github");
  const [phase, setPhase] = useState("input");
  const [url, setUrl] = useState("");
  const [ref, setRef] = useState("main");
  const [subpath, setSubpath] = useState("");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [importId, setImportId] = useState("");
  const [inlineError, setInlineError] = useState("");
  const [enableAfterInstall, setEnableAfterInstall] = useState(false);
  const fileInputRef = useRef(null);
  const dialogRef = useRef(null);
  const phaseRef = useRef(phase);
  const openRef = useRef(open);
  const mountedRef = useRef(false);
  const dialogRequestGenerationRef = useRef(0);
  const restoreFocusRef = useRef(null);
  const closeDialogRef = useRef(null);
  phaseRef.current = phase;
  openRef.current = open;

  const setDialogPhase = (nextPhase) => {
    phaseRef.current = nextPhase;
    setPhase(nextPhase);
  };

  const canCommitDialogRequest = (requestId) =>
    mountedRef.current &&
    openRef.current &&
    requestId === dialogRequestGenerationRef.current;

  const reset = () => {
    setSourceTab("github");
    setDialogPhase("input");
    setUrl("");
    setRef("main");
    setSubpath("");
    setFile(null);
    setPreview(null);
    setImportId("");
    setInlineError("");
    setEnableAfterInstall(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const close = () => {
    if (phaseRef.current === "inspecting" || phaseRef.current === "installing") return;
    openRef.current = false;
    dialogRequestGenerationRef.current += 1;
    reset();
    onClose?.();
  };
  closeDialogRef.current = close;

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      openRef.current = false;
      dialogRequestGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    restoreFocusRef.current = document.activeElement;
    reset();
    const focusFrame = window.requestAnimationFrame(() => {
      focusableElements(dialogRef.current)[0]?.focus();
    });
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        if (phaseRef.current === "inspecting" || phaseRef.current === "installing") return;
        event.preventDefault();
        closeDialogRef.current?.();
        return;
      }
      trapFocus(event, dialogRef.current);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      window.removeEventListener("keydown", handleKeyDown);
      dialogRequestGenerationRef.current += 1;
      if (restoreFocusRef.current?.isConnected) {
        restoreFocusRef.current.focus();
      }
      restoreFocusRef.current = null;
    };
  }, [open]);

  if (!open) return null;

  const inspect = async (event) => {
    event.preventDefault();
    setInlineError("");
    if (sourceTab === "github" && !githubPattern.test(url.trim())) {
      setInlineError("请输入完整的GitHub仓库地址，例如https://github.com/owner/repo。");
      return;
    }
    if (sourceTab === "upload" && !file) {
      setInlineError("请选择一个ZIP文件。");
      return;
    }
    if (
      sourceTab === "upload" &&
      !file.name.toLocaleLowerCase().endsWith(".zip")
    ) {
      setInlineError("仅支持ZIP文件。");
      return;
    }

    const requestId = ++dialogRequestGenerationRef.current;
    setDialogPhase("inspecting");
    try {
      const inspected =
        sourceTab === "github"
          ? await skillApi.inspectGitHub({
              url: url.trim(),
              ref: ref.trim() || "main",
              subpath: subpath.trim(),
            })
          : await skillApi.inspectUpload(file);
      if (!canCommitDialogRequest(requestId)) return;
      setPreview(inspected);
      setImportId(inspected?.importId || "");
      setEnableAfterInstall(false);
      setDialogPhase("preview");
    } catch (error) {
      if (!canCommitDialogRequest(requestId)) return;
      setInlineError(error?.message || "无法检查此Skill。");
      setDialogPhase("input");
    }
  };

  const install = async () => {
    if (!importId) {
      setInlineError("预览已失效，请重新检查。");
      setDialogPhase("input");
      return;
    }
    setInlineError("");
    const requestId = ++dialogRequestGenerationRef.current;
    setDialogPhase("installing");
    try {
      const installed = await skillApi.install(
        importId,
        Boolean(preview?.available && enableAfterInstall),
      );
      if (!canCommitDialogRequest(requestId)) return;
      dispatchSkillsUpdated(installed);
      notifyToast("Skill已安装");
      await onInstalled?.(installed);
      if (!canCommitDialogRequest(requestId)) return;
      reset();
      openRef.current = false;
      onClose?.();
    } catch (error) {
      if (!canCommitDialogRequest(requestId)) return;
      setInlineError(error?.message || "安装Skill失败。");
      setDialogPhase("preview");
    }
  };

  const fileCount =
    preview?.fileCount ?? preview?.files?.length ?? preview?.manifest?.fileCount;
  const totalBytes =
    preview?.bytes ?? preview?.totalBytes ?? preview?.extractedBytes;
  const busy = phase === "inspecting" || phase === "installing";

  return (
    <div
      className={"modal-backdrop skill-install-backdrop"}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) close();
      }}
    >
      <section
        ref={dialogRef}
        className={"modal-panel skill-install-dialog"}
        role={"dialog"}
        aria-modal={"true"}
        aria-labelledby={"skill-install-title"}
      >
        <header className={"modal-head"}>
          <h2 id={"skill-install-title"}>{"安装Skill"}</h2>
          <button
            className={"icon-button"}
            type={"button"}
            aria-label={"关闭安装Skill窗口"}
            disabled={busy}
            onClick={close}
          >
            {"×"}
          </button>
        </header>

        <div className={"skill-install-tabs"} role={"tablist"} aria-label={"安装来源"}>
          <button
            className={sourceTab === "github" ? "active" : ""}
            type={"button"}
            role={"tab"}
            aria-selected={sourceTab === "github"}
            disabled={busy}
            onClick={() => {
              setSourceTab("github");
              setDialogPhase("input");
              setPreview(null);
              setImportId("");
              setInlineError("");
            }}
          >
            {"GitHub"}
          </button>
          <button
            className={sourceTab === "upload" ? "active" : ""}
            type={"button"}
            role={"tab"}
            aria-selected={sourceTab === "upload"}
            disabled={busy}
            onClick={() => {
              setSourceTab("upload");
              setDialogPhase("input");
              setPreview(null);
              setImportId("");
              setInlineError("");
            }}
          >
            {"上传ZIP"}
          </button>
        </div>

        {phase === "input" || phase === "inspecting" ? (
          <form className={"stack-form skill-install-form"} onSubmit={inspect}>
            {sourceTab === "github" ? (
              <>
                <label>
                  {"仓库地址"}
                  <input
                    value={url}
                    type={"url"}
                    autoFocus
                    required
                    placeholder={"https://github.com/owner/repo"}
                    onChange={(event) => setUrl(event.target.value)}
                  />
                </label>
                <div className={"skill-install-github-options"}>
                  <label>
                    {"分支或标签"}
                    <input
                      value={ref}
                      required
                      placeholder={"main"}
                      onChange={(event) => setRef(event.target.value)}
                    />
                  </label>
                  <label>
                    {"子目录（可选）"}
                    <input
                      value={subpath}
                      placeholder={"skills/research"}
                      onChange={(event) => setSubpath(event.target.value)}
                    />
                  </label>
                </div>
              </>
            ) : (
              <label className={"skill-file-field"}>
                {"Skill压缩包"}
                <input
                  ref={fileInputRef}
                  type={"file"}
                  accept={".zip,application/zip"}
                  required
                  onChange={(event) => {
                    setFile(event.target.files?.[0] || null);
                    setInlineError("");
                  }}
                />
                <span>{file ? file.name : "选择包含SKILL.md的ZIP文件"}</span>
              </label>
            )}
            {inlineError ? (
              <div className={"skill-inline-error"} role={"alert"}>
                {inlineError}
              </div>
            ) : null}
            <div className={"modal-actions"}>
              <button type={"button"} disabled={busy} onClick={close}>{"取消"}</button>
              <button className={"primary"} type={"submit"} disabled={busy}>
                {phase === "inspecting" ? "正在检查..." : "检查并预览"}
              </button>
            </div>
          </form>
        ) : (
          <div className={"skill-install-preview"}>
            <div className={"skill-preview-name"}>
              <strong>{preview?.name || preview?.slug || "未命名Skill"}</strong>
              <span>{preview?.version || "未标版本"}</span>
            </div>
            <p>{preview?.description || "此Skill没有说明。"}</p>
            <dl className={"skill-preview-facts"}>
              <div>
                <dt>{"文件"}</dt>
                <dd>{fileCount ?? "未提供"}</dd>
              </div>
              <div>
                <dt>{"大小"}</dt>
                <dd>{bytesLabel(totalBytes)}</dd>
              </div>
              <div>
                <dt>{"依赖"}</dt>
                <dd className={preview?.available ? "" : "missing"}>
                  {dependencyLabel(preview)}
                </dd>
              </div>
            </dl>
            <div className={"skill-script-note"}>
              <strong>{"脚本只保存，不执行"}</strong>
              <span>{"安装过程只写入Skill文件，不会运行其中脚本。"}</span>
            </div>
            <label className={"skill-enable-choice"}>
              <input
                checked={Boolean(preview?.available && enableAfterInstall)}
                type={"checkbox"}
                disabled={!preview?.available || phase === "installing"}
                onChange={(event) => setEnableAfterInstall(event.target.checked)}
              />
              <span>
                {preview?.available
                  ? "安装后启用"
                  : "依赖缺失，安装后保持停用"}
              </span>
            </label>
            {inlineError ? (
              <div className={"skill-inline-error"} role={"alert"}>
                {inlineError}
              </div>
            ) : null}
            <div className={"modal-actions"}>
              <button
                type={"button"}
                disabled={phase === "installing"}
                onClick={() => {
                  setDialogPhase("input");
                  setPreview(null);
                  setImportId("");
                  setInlineError("");
                }}
              >
                {"返回修改"}
              </button>
              <button
                className={"primary"}
                type={"button"}
                disabled={phase === "installing"}
                onClick={install}
              >
                {phase === "installing" ? "正在安装..." : "确认安装"}
              </button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
