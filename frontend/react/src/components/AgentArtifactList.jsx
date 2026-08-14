import { useState } from "react";
import { workspaceApi } from "../api/client.js";
import { mergeAgentArtifactUpdate } from "../controller/agentEvents.js";
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
  const [loadingId, setLoadingId] = useState("");
  const [confirmId, setConfirmId] = useState("");

  const handleArtifact = async (artifact) => {
    const target = artifactTarget(artifact);
    if (!target) return;
    if (/^https?:\/\//i.test(target)) {
      const opened = window.open(target, "_blank", "noopener,noreferrer");
      if (opened) opened.opener = null;
      return;
    }
    try {
      await navigator.clipboard.writeText(target);
      notifyToast("产物路径已复制");
    } catch (error) {
      notifyError(error, "复制产物路径失败");
    }
  };

  const toggleDiff = async (artifact, identifier) => {
    if (selectedId === identifier) {
      setSelectedId("");
      setConfirmId("");
      return;
    }
    setSelectedId(identifier);
    setConfirmId("");
    if (diffs[identifier]) return;
    if (!artifact.diffAvailable || !runId || !artifact.path) {
      setDiffs((current) => ({
        ...current,
        [identifier]: "该变更没有可显示的文本差异。",
      }));
      return;
    }
    setLoadingId(identifier);
    try {
      const result = await workspaceApi.diff({ runId, path: artifact.path });
      setDiffs((current) => ({
        ...current,
        [identifier]: result?.patch || "没有可显示的文本差异。",
      }));
    } catch (error) {
      notifyError(error, "读取文件差异失败");
      setDiffs((current) => ({ ...current, [identifier]: "文件差异暂不可用。" }));
    } finally {
      setLoadingId("");
    }
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
    <div className={`agent-artifact-list${compact ? " compact" : ""}`} aria-label={"运行产物"}>
      {artifacts.map((artifact, index) => {
        const target = artifactTarget(artifact);
        const displayTarget = artifactDisplayTarget(artifact);
        const metrics = artifactMetrics(artifact);
        const external = /^https?:\/\//i.test(target);
        const identifier = artifactIdentifier(artifact, index);
        const selected = selectedId === identifier;
        const canInspect = !external && Boolean(artifact.diffAvailable || artifact.operationId);
        return (
          <div
            className={`agent-artifact-row${artifact.reverted ? " is-reverted" : ""}`}
            key={identifier}
            onKeyDown={(event) => {
              if (event.key !== "Escape" || (!selected && confirmId !== identifier)) return;
              event.preventDefault();
              event.stopPropagation();
              if (confirmId === identifier) {
                setConfirmId("");
                return;
              }
              const row = event.currentTarget;
              setSelectedId("");
              window.requestAnimationFrame(() => {
                row.querySelector("button[aria-expanded]")?.focus();
              });
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
              <div className={"agent-artifact-detail"}>
                <AgentDiffView patch={diffs[identifier]} loading={loadingId === identifier} />
                {!artifact.reverted && artifact.operationId && ["completed", "failed", "cancelled"].includes(runStatus) ? (
                  <div className={"agent-artifact-undo"}>
                    <button type={"button"} onClick={() => undoChange(artifact, identifier)}>
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
