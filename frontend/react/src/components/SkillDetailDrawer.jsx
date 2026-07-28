import { useEffect, useState } from "react";
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

  useEffect(() => {
    if (!skill?.id) {
      setDetail(null);
      return undefined;
    }
    let cancelled = false;
    setLoading(true);
    setDetail(null);
    setDetailError("");
    setActionError("");
    setContent("");
    setContentError("");
    setUpdateInfo(null);
    skillApi.get(skill.id)
      .then((item) => {
        if (!cancelled) setDetail(item);
      })
      .catch((error) => {
        if (!cancelled) {
          setDetailError(error?.message || "无法加载Skill详情。");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [skill?.id]);

  useEffect(() => {
    if (!skill) return undefined;
    const handleKeyDown = (event) => {
      if (event.key === "Escape" && !busyAction) onClose?.();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [busyAction, onClose, skill]);

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
    setContentLoading(true);
    setContentError("");
    try {
      const result = await skillApi.content(current.id);
      setContent(result?.content || "");
    } catch (error) {
      setContentError(error?.message || "无法读取SKILL.md。");
    } finally {
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
        if (event.target === event.currentTarget && !busyAction) onClose?.();
      }}
    >
      <aside
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
            onClick={onClose}
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
