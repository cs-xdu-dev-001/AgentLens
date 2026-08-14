import { evidenceReferences } from "./agentEvidencePresentation.js";

export function AgentEvidenceStrip({ messageId, run = null, trace = [], approvals = [] }) {
  const references = evidenceReferences(run);
  if (!references.length) return null;

  const openEvidence = () => {
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-trace-open", {
      detail: {
        messageId,
        trace,
        approvals,
        run,
        references: references.map((item) => item.source),
        activeTab: "evidence",
      },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-open", {
      detail: { focus: true },
    }));
  };

  return (
    <button
      className={"agent-evidence-strip"}
      type={"button"}
      onClick={openEvidence}
      aria-label={`查看${references.length}个引用来源`}
    >
      <span className={"agent-evidence-strip-label"}>{`来源 ${references.length}`}</span>
      <span className={"agent-evidence-strip-items"}>
        {references.slice(0, 3).map((reference) => (
          <span className={"agent-evidence-source"} key={reference.id}>
            {reference.label}
            {reference.score != null ? <small>{reference.score}%</small> : null}
          </span>
        ))}
        {references.length > 3 ? <span>{`+${references.length - 3}`}</span> : null}
      </span>
      <svg viewBox={"0 0 20 20"} aria-hidden={"true"} focusable={"false"}>
        <path d={"M7 4l6 6-6 6"} fill={"none"} stroke={"currentColor"} strokeWidth={"1.7"} strokeLinecap={"round"} strokeLinejoin={"round"} />
      </svg>
    </button>
  );
}
