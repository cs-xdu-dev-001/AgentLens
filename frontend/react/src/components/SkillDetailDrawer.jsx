import { useEffect, useRef, useState } from "react";
import { skillApi } from "../api/client.js";
import { notifyToast } from "./errorFeedback.js";

const dispatchSkillsUpdated = (skill = null) => {
  window.dispatchEvent(
    new CustomEvent("knowflow:react-skills-updated", {
      detail: { skill },
    }),
  );
};

const missingDependencies = (skill) => [
  ...(skill?.missingTools || []),
  ...(skill?.missingMcp || []),
];

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

export function SkillDetailDrawer({ skill, onClose, onMutated }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [actionError, setActionError] = useState("");
  const [content, setContent] = useState("");
  const [contentLoading, setContentLoading] = useState(false);
  const [contentError, setContentError] = useState("");
  const [updateInfo, setUpdateInfo] = useState(null);
  const drawerRef = useRef(null);
  const mountedRef = useRef(false);
  const openRef = useRef(Boolean(skill));
  const activeSkillIdRef = useRef(skill?.id ?? null);
  const detailRequestGenerationRef = useRef(0);
  const contentRequestGenerationRef = useRef(0);
  const restoreFocusRef = useRef(null);
  const busyActionRef = useRef(busyAction);
  const onCloseRef = useRef(onClose);
  const drawerOpen = Boolean(skill);
  openRef.current = drawerOpen;
  activeSkillIdRef.current = skill?.id ?? null;
  busyActionRef.current = busyAction;
  onCloseRef.current = onClose;

  const canCommitDetailRequest = (requestId, skillId) =>
    mountedRef.current &&
    openRef.current &&
    activeSkillIdRef.current === skillId &&
    requestId === detailRequestGenerationRef.current;

  const canCommitContentRequest = (requestId, skillId) =>
    mountedRef.current &&
    openRef.current &&
    activeSkillIdRef.current === skillId &&
    requestId === contentRequestGenerationRef.current;

  const requestClose = () => {
    if (busyActionRef.current) return;
    onCloseRef.current?.();
  };

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      openRef.current = false;
      detailRequestGenerationRef.current += 1;
      contentRequestGenerationRef.current += 1;
    };
  }, []);

  useEffect(() => {
    if (!skill?.id) {
      detailRequestGenerationRef.current += 1;
      contentRequestGenerationRef.current += 1;
      setDetail(null);
      return undefined;
    }
    const skillId = skill.id;
    const requestId = ++detailRequestGenerationRef.current;
    contentRequestGenerationRef.current += 1;
    setLoading(true);
    setDetail(null);
    setDetailError("");
    setActionError("");
    setContent("");
    setContentLoading(false);
    setContentError("");
    setUpdateInfo(null);
    skillApi.get(skillId)
      .then((item) => {
        if (!canCommitDetailRequest(requestId, skillId)) return;
        setDetail(item);
      })
      .catch((error) => {
        if (!canCommitDetailRequest(requestId, skillId)) return;
        setDetailError(error?.message || "无法加载Skill详情。");
      })
      .finally(() => {
        if (!canCommitDetailRequest(requestId, skillId)) return;
        setLoading(false);
      });
    return () => {
      if (detailRequestGenerationRef.current === requestId) {
        detailRequestGenerationRef.current += 1;
      }
      contentRequestGenerationRef.current += 1;
    };
  }, [skill?.id]);

  useEffect(() => {
    if (!drawerOpen) return undefined;
    restoreFocusRef.current = document.activeElement;
    const focusFrame = window.requestAnimationFrame(() => {
      focusableElements(drawerRef.current)[0]?.focus();
    });
    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        if (busyActionRef.current) return;
        event.preventDefault();
        onCloseRef.current?.();
        return;
      }
      trapFocus(event, drawerRef.current);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      window.removeEventListener("keydown", handleKeyDown);
      detailRequestGenerationRef.current += 1;
      contentRequestGenerationRef.current += 1;
      if (restoreFocusRef.current?.isConnected) {
        restoreFocusRef.current.focus();
      }
      restoreFocusRef.current = null;
    };
  }, [drawerOpen]);

  if (!skill) return null;

  const current = detail || skill;
  const missing = missingDependencies(current);
  const isBuiltin =
    current.sourceKind === "builtin" || current.owner === "builtin";
  const isGitHub = current.sourceKind === "github";

  const mutate = async (action, operation, successMessage) => {
    setBusyAction(action);
    setActionError("");
    try {
      const updated = await operation();
      if (updated?.id) setDetail(updated);
      dispatchSkillsUpdated(updated?.id ? updated : null);
      notifyToast(successMessage);
      await onMutated?.(updated);
      return updated;
    } catch (error) {
      setActionError(error?.message || "操作失败。");
      return null;
    } finally {
      setBusyAction("");
    }
  };

  const toggleEnabled = () =>
    mutate(
      "enabled",
      () => skillApi.setEnabled(current.id, !current.enabled),
      current.enabled ? "Skill已停用" : "Skill已启用",
    );

  const loadContent = async () => {
    const skillId = current.id;
    const requestId = ++contentRequestGenerationRef.current;
    setContentLoading(true);
    setContentError("");
    try {
      const result = await skillApi.content(skillId);
      if (!canCommitContentRequest(requestId, skillId)) return;
      setContent(result?.content || "");
    } catch (error) {
      if (!canCommitContentRequest(requestId, skillId)) return;
      setContentError(error?.message || "无法读取SKILL.md。");
    } finally {
      if (!canCommitContentRequest(requestId, skillId)) return;
      setContentLoading(false);
    }
  };

  const checkUpdate = async () => {
    setBusyAction("check");
    setActionError("");
    try {
      const result = await skillApi.checkUpdate(current.id);
      setUpdateInfo(result);
    } catch (error) {
      setActionError(error?.message || "检查更新失败。");
    } finally {
      setBusyAction("");
    }
  };

  const updateSkill = () =>
    mutate(
      "update",
      () => skillApi.update(current.id, Boolean(current.enabled && current.available)),
      "Skill已更新",
    ).then((updated) => {
      if (updated) setUpdateInfo(null);
    });

  const deleteSkill = async () => {
    if (
      !window.confirm(
        `删除“${current.name || current.slug}”？此操作会移除个人Skill文件。`,
      )
    ) {
      return;
    }
    const deleted = await mutate(
      "delete",
      () => skillApi.delete(current.id),
      "Skill已删除",
    );
    if (deleted !== null) {
      await onMutated?.(null);
      onClose?.();
    }
  };

  return (
    <div
      className={"mcp-tool-drawer-backdrop skill-detail-backdrop"}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) requestClose();
      }}
    >
      <aside
        ref={drawerRef}
        className={"mcp-tool-drawer skill-detail-drawer"}
        role={"dialog"}
        aria-modal={"true"}
        aria-labelledby={"skill-detail-title"}
      >
        <header className={"mcp-tool-drawer-head skill-detail-head"}>
          <div>
            <span className={"skill-detail-kicker"}>
              {isBuiltin ? "内置Skill" : "个人Skill"}
            </span>
            <h2 id={"skill-detail-title"}>
              {current.name || current.slug || "未命名Skill"}
            </h2>
          </div>
          <button
            className={"icon-button"}
            type={"button"}
            aria-label={"关闭Skill详情"}
            disabled={Boolean(busyAction)}
            onClick={requestClose}
          >
            {"×"}
          </button>
        </header>

        <div className={"skill-detail-body"}>
          {loading ? (
            <div className={"skills-list-state"}>{"正在加载详情..."}</div>
          ) : null}
          {!loading && detailError ? (
            <div className={"skill-inline-error"} role={"alert"}>
              {detailError}
            </div>
          ) : null}
          {!loading && !detailError ? (
            <>
              <div className={"skill-detail-summary"}>
                <p>{current.description || "此Skill没有说明。"}</p>
                <dl>
                  <div>
                    <dt>{"版本"}</dt>
                    <dd>{current.version || "未标版本"}</dd>
                  </div>
                  <div>
                    <dt>{"来源"}</dt>
                    <dd>{current.sourceKind || current.owner || "未知"}</dd>
                  </div>
                  <div>
                    <dt>{"状态"}</dt>
                    <dd>
                      {!current.available
                        ? "依赖缺失"
                        : current.enabled
                          ? "已启用"
                          : "已停用"}
                    </dd>
                  </div>
                </dl>
              </div>

              <section className={"skill-detail-section"}>
                <h3>{"依赖"}</h3>
                {missing.length ? (
                  <p className={"skill-dependency-missing"}>
                    {`缺少：${missing.join("、")}`}
                  </p>
                ) : (
                  <p>{"依赖完整，可以启用。"}</p>
                )}
              </section>

              <section className={"skill-detail-section"}>
                <h3>{"操作"}</h3>
                <div className={"skill-detail-actions"}>
                  <button
                    className={"skill-detail-primary"}
                    type={"button"}
                    disabled={
                      Boolean(busyAction) ||
                      (!current.available && !current.enabled)
                    }
                    onClick={toggleEnabled}
                  >
                    {busyAction === "enabled"
                      ? "正在更新..."
                      : current.enabled
                        ? "停用"
                        : "启用"}
                  </button>
                  {isGitHub ? (
                    <button
                      type={"button"}
                      disabled={Boolean(busyAction)}
                      onClick={checkUpdate}
                    >
                      {busyAction === "check" ? "正在检查..." : "检查更新"}
                    </button>
                  ) : null}
                  {isGitHub && updateInfo?.updateAvailable ? (
                    <button
                      type={"button"}
                      disabled={Boolean(busyAction)}
                      onClick={updateSkill}
                    >
                      {busyAction === "update"
                        ? "正在更新..."
                        : `更新到${updateInfo.latestVersion || "最新版"}`}
                    </button>
                  ) : null}
                  {!isBuiltin ? (
                    <button
                      className={"danger"}
                      type={"button"}
                      disabled={Boolean(busyAction)}
                      onClick={deleteSkill}
                    >
                      {busyAction === "delete" ? "正在删除..." : "删除"}
                    </button>
                  ) : null}
                </div>
                {updateInfo && !updateInfo.updateAvailable ? (
                  <p className={"skill-action-note"}>{"当前已是最新版。"}</p>
                ) : null}
                {actionError ? (
                  <div className={"skill-inline-error"} role={"alert"}>
                    {actionError}
                  </div>
                ) : null}
              </section>

              <section className={"skill-detail-section skill-content-section"}>
                <div className={"skill-detail-section-head"}>
                  <h3>{"SKILL.md"}</h3>
                  {!content ? (
                    <button
                      type={"button"}
                      disabled={contentLoading}
                      onClick={loadContent}
                    >
                      {contentLoading ? "正在读取..." : "查看 SKILL.md"}
                    </button>
                  ) : null}
                </div>
                {contentError ? (
                  <div className={"skill-inline-error"} role={"alert"}>
                    {contentError}
                  </div>
                ) : null}
                {content ? (
                  <pre className={"skill-source-view"}>{content}</pre>
                ) : null}
              </section>
            </>
          ) : null}
        </div>
      </aside>
    </div>
  );
}
