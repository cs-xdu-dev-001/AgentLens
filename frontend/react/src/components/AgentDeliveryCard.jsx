import { useEffect, useMemo, useState } from "react";
import { AgentArtifactList, artifactTarget } from "./AgentArtifactList.jsx";
import {
  buildAgentVerificationPresentation,
  verificationTraceStepId,
} from "./agentRunPresentation.js";

function changeMetrics(artifacts) {
  return artifacts.reduce((total, artifact) => ({
    added: total.added + Math.max(0, Number(artifact?.addedLines) || 0),
    removed: total.removed + Math.max(0, Number(artifact?.removedLines) || 0),
  }), { added: 0, removed: 0 });
}

function deliveryState(verifications) {
  if (!verifications.length) {
    return { className: "unverified", label: "未验证" };
  }
  if (verifications.some((item) => item.status === "failed")) {
    return { className: "failed", label: "验证失败" };
  }
  return { className: "passed", label: "验证通过" };
}

export function AgentDeliveryCard({ messageId, run = null, trace = [], approvals = [] }) {
  const sourceArtifacts = useMemo(() => (
    Array.isArray(run?.artifacts)
      ? run.artifacts.filter((artifact) => artifact?.artifactType !== "reference")
      : []
  ), [run?.artifacts]);
  const [artifacts, setArtifacts] = useState(sourceArtifacts);
  const verifications = useMemo(
    () => buildAgentVerificationPresentation(trace, run?.verifications),
    [run?.verifications, trace],
  );
  const failedVerification = verifications.some((item) => item.status === "failed");
  const delivery = deliveryState(verifications);
  const [expanded, setExpanded] = useState(failedVerification);

  useEffect(() => setArtifacts(sourceArtifacts), [sourceArtifacts]);
  useEffect(() => {
    if (failedVerification) setExpanded(true);
  }, [failedVerification, run?.id, run?.runId]);

  if ((!artifacts.length && !verifications.length) || !["cancelled", "completed", "failed", "success"].includes(run?.status)) return null;
  const metrics = changeMetrics(artifacts);
  const externalCount = artifacts.filter((artifact) => /^https?:\/\//i.test(artifactTarget(artifact))).length;
  const fileCount = artifacts.length - externalCount;
  const revertedCount = artifacts.filter((artifact) => artifact?.reverted).length;
  const summary = [
    fileCount ? `${fileCount}个文件已更改` : "",
    externalCount ? `${externalCount}个链接已生成` : "",
    revertedCount ? `${revertedCount}项已撤销` : "",
  ].filter(Boolean).join(" · ");
  const title = artifacts.length ? "本轮交付" : "本轮验收";

  const openRunPanel = (activeTab, focusStepId = "") => {
    const currentRun = { ...run, artifacts };
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-trace-open", {
      detail: {
        messageId,
        trace,
        approvals,
        run: currentRun,
        activeTab,
        focusStepId,
      },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-open", {
      detail: { focus: true },
    }));
  };
  const openArtifacts = () => openRunPanel("artifacts");
  const openVerification = (item) => openRunPanel(
    "trace",
    verificationTraceStepId(item, trace),
  );

  return (
    <section className={`agent-delivery-card${expanded ? " is-expanded" : ""}`} aria-label={title}>
      <button
        type={"button"}
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        aria-controls={`agent-delivery-${messageId}`}
      >
        <svg className={"agent-delivery-card-chevron"} viewBox={"0 0 20 20"} aria-hidden={"true"} focusable={"false"}>
          <path d={"M7 4l6 6-6 6"} fill={"none"} stroke={"currentColor"} strokeWidth={"1.8"} strokeLinecap={"round"} strokeLinejoin={"round"} />
        </svg>
        <span className={"agent-delivery-card-copy"}>
          <strong>{title}</strong>
          {summary ? <span>{summary}</span> : null}
        </span>
        <span className={"agent-delivery-card-diff"} aria-label={"代码行变更"}>
          {metrics.added ? <b>{`+${metrics.added}`}</b> : null}
          {metrics.removed ? <i>{`−${metrics.removed}`}</i> : null}
        </span>
        <span className={`agent-delivery-card-status is-${delivery.className}`}>
          {delivery.label}
        </span>
        <span className={"agent-delivery-card-state"}>{expanded ? "收起" : "查看"}</span>
      </button>
      {expanded ? (
        <div className={"agent-delivery-card-body"} id={`agent-delivery-${messageId}`}>
          {artifacts.length ? (
            <AgentArtifactList
              artifacts={artifacts}
              messageId={messageId}
              runId={run?.id || run?.runId}
              runStatus={run?.status}
              onChange={setArtifacts}
              compact
            />
          ) : null}
          {verifications.length ? (
            <div className={"agent-delivery-verification"} aria-label={"验收结果"}>
              <div className={"agent-delivery-verification-head"}>
                <strong>{"验证"}</strong>
                <span>{`${verifications.filter((item) => item.status === "passed").length}/${verifications.length}通过`}</span>
              </div>
              <div className={"agent-delivery-verification-list"}>
                {verifications.map((item) => (
                  <button
                    className={`agent-delivery-verification-row is-${item.status}`}
                    type={"button"}
                    aria-label={`查看${item.label}过程：${item.statusLabel}`}
                    onClick={() => openVerification(item)}
                    key={item.id}
                  >
                    <span className={"agent-delivery-verification-mark"} aria-hidden={"true"} />
                    <span className={"agent-delivery-verification-copy"}>
                      <strong>{item.label}</strong>
                      <code>{item.tool}</code>
                    </span>
                    <span className={"agent-delivery-verification-meta"}>
                      {item.duration ? `${item.duration} · ` : ""}{item.statusLabel}
                      {item.exitCode != null && item.exitCode !== 0 ? ` · 退出码${item.exitCode}` : ""}
                    </span>
                    <svg className={"agent-delivery-verification-open"} viewBox={"0 0 20 20"} aria-hidden={"true"} focusable={"false"}>
                      <path d={"M7 4l6 6-6 6"} fill={"none"} stroke={"currentColor"} strokeWidth={"1.8"} strokeLinecap={"round"} strokeLinejoin={"round"} />
                    </svg>
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {artifacts.length || verifications.length ? (
            <button
              className={"agent-delivery-card-open"}
              type={"button"}
              onClick={failedVerification
                ? () => openVerification(verifications.find((item) => item.status === "failed"))
                : artifacts.length
                  ? openArtifacts
                  : () => openRunPanel("trace")}
            >
              {failedVerification
                ? "查看失败步骤与恢复操作"
                : artifacts.length
                  ? "在运行面板查看全部"
                  : "查看完整运行过程"}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
