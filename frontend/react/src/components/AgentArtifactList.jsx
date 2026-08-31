import { useRef, useState } from "react";
import { workspaceApi } from "../api/client.js";
import { mergeAgentArtifactUpdate } from "../controller/agentEvents.js";
import { copyTextToClipboard } from "../controller/clipboard.js";
import { publishReactAgentArtifactsUpdated } from "../controller/messageEvents.js";
import { notifyError, notifyToast } from "./errorFeedback.js";
import { AgentDiffView } from "./AgentDiffView.jsx";

function artifactLabel(artifact) {
  if (artifact?.reverted) return "已撤销";
  return ({ edit: "已修改", write: "已写入" }[artifact?.operation] || "已生成");
}

function artifactMetrics(artifact) {
  const parts = [];
  const added = Math.max(0, Number(artifact?.addedLines) || 0);
  const removed = Math.max(0, Number(artifact?.removedLines) || 0);
  const bytes = Math.max(0, Number(artifact?.writtenBytes) || 0);
  if (added) parts.push(`+${added}`);
  if (removed) parts.push(`−${removed}`);
  if (bytes) parts.push(`${bytes} B`);
  return parts.join(" · ");
}

export function artifactTarget(artifact) {
  return String(
    artifact?.path || artifact?.url || artifact?.href || artifact?.title || "",
  ).trim();
}

export function artifactDisplayTarget(artifact) {
  const target = artifactTarget(artifact);
  if (!/^https?:\/\//i.test(target)) return target;
  try {
    const url = new URL(target);
    return `${url.origin}${url.pathname}`;
  } catch {
    return "外部链接";
  }
}

function artifactIdentifier(artifact, index = 0) {
  return artifact?.artifactId
    || artifact?.operationId
    || artifact?.id
    || artifact?.eventId
    || `${artifactTarget(artifact)}-${index}`;
}

export function AgentArtifactList({
  artifacts = [],
  messageId = "",
  runId = "",
  runStatus = "",
  onChange,
  compact = false,
}) {
  const [selectedId, setSelectedId] = useState("");
  const [diffs, setDiffs] = useState({});
  const [diffErrors, setDiffErrors] = useState({});
  const [loadingId, setLoadingId] = useState("");
  const [confirmId, setConfirmId] = useState("");
  const [reviewedIds, setReviewedIds] = useState([]);
  const [lastReviewId, setLastReviewId] = useState("");
  const listRef = useRef(null);
  const detailRef = useRef(null);
  const reviewLauncherRef = useRef(null);
  const diffRequestRef = useRef(0);

  const reviewableArtifacts = artifacts
    .map((artifact, index) => ({
      artifact,
      identifier: artifactIdentifier(artifact, index),
    }))
    .filter(({ artifact }) => {
      const target = artifactTarget(artifact);
      return !/^https?:\/\//i.test(target)
        && Boolean(artifact.diffAvailable || artifact.operationId);
    });
  const reviewedCount = reviewableArtifacts.filter(({ identifier }) => (
    reviewedIds.includes(identifier)
  )).length;
  const activeReviewIndex = reviewableArtifacts.findIndex(({ identifier }) => (
    identifier === selectedId
  ));

  const focusReviewDetail = () => {
    window.requestAnimationFrame(() => detailRef.current?.focus());
  };

  const markReviewed = (identifier) => {
    setReviewedIds((current) => (
      current.includes(identifier) ? current : [...current, identifier]
    ));
  };

  const handleArtifact = async (artifact) => {
    const target = artifactTarget(artifact);
    if (!target) return;
    if (/^https?:\/\//i.test(target)) {
      const opened = window.open(target, "_blank", "noopener,noreferrer");
      if (opened) opened.opener = null;
      return;
    }
    try {
      await copyTextToClipboard(target);
      notifyToast("产物路径已复制");
    } catch (error) {
      notifyError(error, "复制产物路径失败");
    }
  };

  const downloadArtifact = (artifact) => {
    const path = String(artifact?.path || "").trim();
    if (!path || artifact?.reverted) return;
    try {
      window.location.assign(workspaceApi.downloadUrl(path));
      notifyToast("正在下载产物");
    } catch (error) {
      notifyError(error, "下载产物失败");
    }
  };

  const openDiff = async (artifact, identifier) => {
    const requestId = diffRequestRef.current + 1;
    diffRequestRef.current = requestId;
    setSelectedId(identifier);
    setLastReviewId(identifier);
    setConfirmId("");
    focusReviewDetail();
    if (diffs[identifier]) {
      markReviewed(identifier);
      setLoadingId("");
      return;
    }
    if (!artifact.diffAvailable || !runId || !artifact.path) {
      setLoadingId("");
      setDiffErrors((current) => ({ ...current, [identifier]: "" }));
      setDiffs((current) => ({
        ...current,
        [identifier]: "该变更没有可显示的文本差异。",
      }));
      markReviewed(identifier);
      return;
    }
    setLoadingId(identifier);
    setDiffErrors((current) => ({ ...current, [identifier]: "" }));
    try {
      const result = await workspaceApi.diff({ runId, path: artifact.path });
      if (diffRequestRef.current !== requestId) return;
      setDiffs((current) => ({
        ...current,
        [identifier]: result?.patch || "没有可显示的文本差异。",
      }));
      markReviewed(identifier);
    } catch (error) {
      if (diffRequestRef.current !== requestId) return;
      notifyError(error, "读取文件差异失败");
      setDiffErrors((current) => ({ ...current, [identifier]: "文件差异暂不可用。" }));
    } finally {
      if (diffRequestRef.current === requestId) setLoadingId("");
    }
  };

  const closeReview = (focusId = selectedId) => {
    setSelectedId("");
    setConfirmId("");
    window.requestAnimationFrame(() => {
      if (reviewLauncherRef.current) {
        reviewLauncherRef.current.focus();
        return;
      }
      const button = Array.from(
        listRef.current?.querySelectorAll("button[data-workbench-item-id]") || [],
      ).find((item) => item.dataset.workbenchItemId === focusId);
      button?.focus();
    });
  };

  const toggleDiff = async (artifact, identifier) => {
    if (selectedId === identifier) {
      closeReview(identifier);
      return;
    }
    await openDiff(artifact, identifier);
  };

  const navigateReview = (direction) => {
    if (!reviewableArtifacts.length) return;
    const currentIndex = activeReviewIndex >= 0
      ? activeReviewIndex
      : Math.max(0, reviewableArtifacts.findIndex(({ identifier }) => identifier === lastReviewId));
    const nextIndex = Math.max(
      0,
      Math.min(reviewableArtifacts.length - 1, currentIndex + direction),
    );
    if (nextIndex === currentIndex && activeReviewIndex >= 0) return;
    const next = reviewableArtifacts[nextIndex];
    void openDiff(next.artifact, next.identifier);
  };

  const resumeReview = () => {
    const rememberedIndex = reviewableArtifacts.findIndex(({ identifier }) => identifier === lastReviewId);
    const firstUnreviewedIndex = reviewableArtifacts.findIndex(({ identifier }) => !reviewedIds.includes(identifier));
    const next = reviewableArtifacts[
      rememberedIndex >= 0 ? rememberedIndex : Math.max(0, firstUnreviewedIndex)
    ];
    if (next) void openDiff(next.artifact, next.identifier);
  };

  const undoChange = async (artifact, identifier) => {
    if (confirmId !== identifier) {
      setConfirmId(identifier);
      return;
    }
    setLoadingId(identifier);
    try {
      const result = await workspaceApi.undoChange({ runId, operationId: artifact.operationId });
      const updatedArtifact = result?.artifact || {
        ...artifact,
        reverted: true,
        changeStatus: "reverted",
      };
      const nextArtifacts = mergeAgentArtifactUpdate(artifacts, updatedArtifact);
      onChange?.(nextArtifacts);
      publishReactAgentArtifactsUpdated({ messageId, runId, artifacts: nextArtifacts });
      setDiffs((current) => ({ ...current, [identifier]: "该文件变更已安全撤销。" }));
      setConfirmId("");
      notifyToast("文件变更已撤销");
    } catch (error) {
      notifyError(error, "撤销失败，文件可能已被后续修改");
    } finally {
      setLoadingId("");
    }
  };

  if (!artifacts.length) {
    return compact ? null : <p className={"empty-state"}>{"本次运行没有生成文件或链接。"}</p>;
  }

  return (
    <div
      ref={listRef}
      className={`agent-artifact-list${compact ? " compact" : ""}`}
      aria-label={"运行产物"}
    >
      {reviewableArtifacts.length > 1 ? (
        <div className={"agent-artifact-review-toolbar"}>
          <div className={"agent-artifact-review-summary"}>
            <strong>{"变更审阅"}</strong>
            <span aria-live={"polite"}>{`${reviewedCount}/${reviewableArtifacts.length}已查看`}</span>
          </div>
          <button
            ref={reviewLauncherRef}
            type={"button"}
            onClick={selectedId ? closeReview : resumeReview}
          >
            {selectedId
              ? "收起审阅"
              : (lastReviewId ? "返回审阅" : "开始审阅")}
          </button>
        </div>
      ) : null}
      {artifacts.map((artifact, index) => {
        const target = artifactTarget(artifact);
        const displayTarget = artifactDisplayTarget(artifact);
        const metrics = artifactMetrics(artifact);
        const external = /^https?:\/\//i.test(target);
        const downloadable = !external && Boolean(String(artifact?.path || "").trim()) && !artifact.reverted;
        const identifier = artifactIdentifier(artifact, index);
        const selected = selectedId === identifier;
        const canInspect = !external && Boolean(artifact.diffAvailable || artifact.operationId);
        return (
          <div
            className={`agent-artifact-row${artifact.reverted ? " is-reverted" : ""}`}
            key={identifier}
            onKeyDown={(event) => {
              if (selected && event.key === "ArrowLeft") {
                event.preventDefault();
                event.stopPropagation();
                navigateReview(-1);
                return;
              }
              if (selected && event.key === "ArrowRight") {
                event.preventDefault();
                event.stopPropagation();
                navigateReview(1);
                return;
              }
              if (event.key !== "Escape" || (!selected && confirmId !== identifier)) return;
              event.preventDefault();
              event.stopPropagation();
              if (confirmId === identifier) {
                setConfirmId("");
                return;
              }
              closeReview(identifier);
            }}
          >
            <span className={"agent-artifact-kind"}>{artifactLabel(artifact)}</span>
            <div className={"agent-artifact-copy"}>
              <strong title={displayTarget}>{displayTarget || "运行产物"}</strong>
              {metrics ? <small>{metrics}</small> : null}
            </div>
            <div className={"agent-artifact-actions"}>
              {canInspect ? (
                <button
                  type={"button"}
                  aria-expanded={selected}
                  data-workbench-item={"artifact"}
                  data-workbench-item-id={identifier}
                  tabIndex={index === 0 ? 0 : -1}
                  onClick={() => toggleDiff(artifact, identifier)}
                >
                  {selected ? "收起" : "详情"}
                </button>
              ) : null}
              {downloadable ? (
                <button
                  type={"button"}
                  title={"下载到本地"}
                  onClick={() => downloadArtifact(artifact)}
                >
                  {"下载"}
                </button>
              ) : null}
              {target ? (
                <button
                  type={"button"}
                  data-workbench-item={canInspect ? undefined : "artifact"}
                  data-workbench-item-id={canInspect ? undefined : identifier}
                  tabIndex={!canInspect ? (index === 0 ? 0 : -1) : undefined}
                  onClick={() => handleArtifact(artifact)}
                >
                  {external ? "打开" : "复制路径"}
                </button>
              ) : null}
            </div>
            {selected ? (
              <div
                ref={detailRef}
                className={"agent-artifact-detail"}
                tabIndex={-1}
                aria-label={`变更审阅 ${activeReviewIndex + 1}/${reviewableArtifacts.length}`}
                aria-keyshortcuts={"ArrowLeft ArrowRight Escape"}
              >
                {reviewableArtifacts.length > 1 ? (
                  <div className={"agent-artifact-review-head"}>
                    <div>
                      <strong>{`变更 ${activeReviewIndex + 1}/${reviewableArtifacts.length}`}</strong>
                      <span>{`${reviewedCount}/${reviewableArtifacts.length}已查看`}</span>
                    </div>
                    <div className={"agent-artifact-review-nav"}>
                      <button
                        type={"button"}
                        disabled={activeReviewIndex <= 0}
                        onClick={() => navigateReview(-1)}
                      >
                        {"上一个"}
                      </button>
                      <button
                        type={"button"}
                        disabled={activeReviewIndex >= reviewableArtifacts.length - 1}
                        onClick={() => navigateReview(1)}
                      >
                        {"下一个"}
                      </button>
                    </div>
                  </div>
                ) : null}
                <AgentDiffView
                  patch={diffs[identifier] || diffErrors[identifier]}
                  loading={loadingId === identifier}
                />
                {!artifact.reverted && artifact.operationId && ["completed", "failed", "cancelled"].includes(runStatus) ? (
                  <div className={"agent-artifact-undo"}>
                    <button
                      type={"button"}
                      disabled={loadingId === identifier}
                      onClick={() => undoChange(artifact, identifier)}
                    >
                      {confirmId === identifier ? "确认安全撤销" : "撤销此文件"}
                    </button>
                    {confirmId === identifier ? (
                      <button type={"button"} onClick={() => setConfirmId("")}>{"取消"}</button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
