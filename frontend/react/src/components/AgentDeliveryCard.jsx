import { useEffect, useMemo, useState } from "react";
import { AgentArtifactList } from "./AgentArtifactList.jsx";
import {
  buildAgentDeliveryPresentation,
  buildAgentVerificationPresentation,
  verificationTraceStepId,
} from "./agentRunPresentation.js";

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
  const runStatus = run?.runSummary?.status || run?.status || "";
  const delivery = useMemo(() => buildAgentDeliveryPresentation({
    artifacts,
    verifications,
    runStatus,
  }), [artifacts, runStatus, verifications]);
  const [expanded, setExpanded] = useState(delivery.expandByDefault);

  useEffect(() => setArtifacts(sourceArtifacts), [sourceArtifacts]);
  useEffect(() => {
    if (delivery.expandByDefault) setExpanded(true);
  }, [delivery.expandByDefault, run?.id, run?.runId]);

  if ((!artifacts.length && !verifications.length) || ![
    "canceled",
    "cancelled",
    "completed",
    "error",
    "failed",
    "interrupted",
    "succeeded",
    "success",
  ].includes(String(runStatus).toLowerCase())) return null;

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
  const openWorkspace = () => {
    const currentRun = { ...run, artifacts };
    window.dispatchEvent(new CustomEvent("knowflow:react-workspace-open", {
      detail: {
        messageId,
        run: currentRun,
      },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
      detail: { page: "workspace" },
    }));
  };

  return (
    <section className={`agent-delivery-card${expanded ? " is-expanded" : ""}`} aria-label={delivery.title}>
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
          <strong>{delivery.title}</strong>
          {delivery.summary ? <span>{delivery.summary}</span> : null}
        </span>
        <span className={"agent-delivery-card-diff"} aria-label={"代码行变更"}>
          {delivery.added ? <b>{`+${delivery.added}`}</b> : null}
          {delivery.removed ? <i>{`−${delivery.removed}`}</i> : null}
        </span>
        <span className={`agent-delivery-card-status is-${delivery.state.className}`} aria-live={"polite"}>
          {delivery.state.label}
        </span>
      </button>
      {expanded ? (
        <div className={"agent-delivery-card-body"} id={`agent-delivery-${messageId}`}>
          {artifacts.length ? (
            <AgentArtifactList
              artifacts={artifacts}
              messageId={messageId}
              runId={run?.id || run?.runId}
              runStatus={runStatus}
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
              onClick={delivery.failedVerification
                ? () => openVerification(verifications.find((item) => item.status === "failed"))
                : delivery.actionTarget === "artifacts"
                  ? openArtifacts
                  : () => openRunPanel("trace")}
            >
              {delivery.actionLabel}
            </button>
          ) : null}
          {artifacts.length ? (
            <button
              className={"agent-delivery-card-open agent-delivery-card-workspace-open"}
              type={"button"}
              onClick={openWorkspace}
            >
              {"在工作区查看"}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
