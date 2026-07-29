import { useEffect, useState } from "react";
import { mergeMemoryActivityTrace } from "../controller/memoryActivity.js";
import { AgentApprovalPrompt } from "./AgentApprovalPrompt.jsx";
import { AgentRunSummary } from "./AgentRunSummary.jsx";
import { AgentTraceView } from "./AgentTraceView.jsx";
import { AgentTaskPlan } from "./AgentTaskPlan.jsx";

const toolLabels = {
  knowledge_search: "知识库检索",
  session_memory_search: "会话记忆",
  web_search: "网络搜索",
  calculator: "计算器",
};

const qualityLabels = {
  strong: "强匹配",
  usable: "可用",
  weak: "偏弱",
  no_match: "无匹配",
};

function formatScore(value) {
  const score = Number(value || 0);
  return Number.isFinite(score) ? score.toFixed(3) : "0.000";
}

function QualityMetric({ label, value }) {
  return (
    <span className={"quality-metric"}>
      <strong>{value}</strong>
      <small>{label}</small>
    </span>
  );
}

export function ChatEvidenceDrawer() {
  const [activeTab, setActiveTab] = useState("trace");
  const [references, setReferences] = useState([]);
  const [toolCalls, setToolCalls] = useState([]);
  const [ragQuality, setRagQuality] = useState(null);
  const [retrievalRun, setRetrievalRun] = useState(null);
  const [trace, setTrace] = useState([]);
  const [approvals, setApprovals] = useState([]);
  const [run, setRun] = useState(null);
  const [messageId, setMessageId] = useState("");

  useEffect(() => {
    const handleReferencesUpdated = (event) => setReferences(Array.isArray(event.detail?.references) ? event.detail.references : []);
    const handleToolTimelineUpdated = (event) => setToolCalls(Array.isArray(event.detail?.toolCalls) ? event.detail.toolCalls : []);
    const handleRagQualityUpdated = (event) => {
      setRagQuality(event.detail?.ragQuality || null);
      setRetrievalRun(event.detail?.retrievalRun || null);
    };
    const handleAgentTraceUpdated = (event) => {
      const nextTrace = Array.isArray(event.detail?.trace)
        ? event.detail.trace
        : [];
      setTrace(nextTrace);
      if (
        nextTrace.some(
          (step) =>
            step.status === "running" ||
            (
              step.status === "waiting" &&
              step.kind === "approval"
            ),
        )
      ) {
        setActiveTab("trace");
      }
    };
    const handleAgentTraceOpen = (event) => {
      setTrace(
        Array.isArray(event.detail?.trace)
          ? event.detail.trace
          : [],
      );
      setApprovals(
        Array.isArray(event.detail?.approvals)
          ? event.detail.approvals
          : [],
      );
      setRun(event.detail?.run || null);
      setMessageId(event.detail?.messageId || "");
      setActiveTab("trace");
    };
    const handleAgentRunUpdated = (event) => {
      setRun(event.detail?.run || null);
      if (event.detail?.messageId) {
        setMessageId(event.detail.messageId);
      }
      setActiveTab("trace");
    };
    const handleAgentApprovalsUpdated = (event) => {
      setApprovals(
        Array.isArray(event.detail?.approvals)
          ? event.detail.approvals
          : [],
      );
      if (
        event.detail?.approvals?.some(
          (approval) => approval.status === "waiting",
        )
      ) {
        setActiveTab("trace");
      }
    };
    window.addEventListener("knowflow:react-references-updated", handleReferencesUpdated);
    window.addEventListener("knowflow:react-tool-timeline-updated", handleToolTimelineUpdated);
    window.addEventListener("knowflow:react-rag-quality-updated", handleRagQualityUpdated);
    window.addEventListener("knowflow:react-agent-trace-updated", handleAgentTraceUpdated);
    window.addEventListener("knowflow:react-agent-trace-open", handleAgentTraceOpen);
    window.addEventListener("knowflow:react-agent-approvals-updated", handleAgentApprovalsUpdated);
    window.addEventListener("knowflow:react-agent-run-updated", handleAgentRunUpdated);
    return () => {
      window.removeEventListener("knowflow:react-references-updated", handleReferencesUpdated);
      window.removeEventListener("knowflow:react-tool-timeline-updated", handleToolTimelineUpdated);
      window.removeEventListener("knowflow:react-rag-quality-updated", handleRagQualityUpdated);
      window.removeEventListener("knowflow:react-agent-trace-updated", handleAgentTraceUpdated);
      window.removeEventListener("knowflow:react-agent-trace-open", handleAgentTraceOpen);
      window.removeEventListener("knowflow:react-agent-approvals-updated", handleAgentApprovalsUpdated);
      window.removeEventListener("knowflow:react-agent-run-updated", handleAgentRunUpdated);
    };
  }, []);

  useEffect(() => {
    const handleMemoryActivityUpdated = (event) => {
      if (
        !messageId
        || event.detail?.messageId !== messageId
      ) {
        return;
      }
      setTrace((current) => mergeMemoryActivityTrace(
        current,
        event.detail?.memoryActivity,
      ));
    };
    window.addEventListener(
      "knowflow:react-memory-activity-updated",
      handleMemoryActivityUpdated,
    );
    return () => window.removeEventListener(
      "knowflow:react-memory-activity-updated",
      handleMemoryActivityUpdated,
    );
  }, [messageId]);

  const handleDrawerClose = () => window.dispatchEvent(new CustomEvent("knowflow:react-drawer-close"));
  const qualityLevel = ragQuality?.qualityLevel || "no_match";
  const scoreBuckets = ragQuality?.scoreBuckets || {};

  return (
    <aside className={"evidence-drawer"} id={"evidence-drawer"}>
      <div className={"drawer-header"}>
        <AgentRunSummary trace={trace} run={run} />
        <button className={"icon-button"} id={"inspector-close"} type={"button"} title={"收起运行面板"} aria-label={"收起运行面板"} onClick={handleDrawerClose}>
          <svg viewBox={"0 0 24 24"} aria-hidden={"true"} focusable={"false"}>
            <path d={"M6 6l12 12M18 6 6 18"} fill={"none"} stroke={"currentColor"} strokeWidth={"2"} strokeLinecap={"round"} />
          </svg>
        </button>
      </div>
      <div
        className={"drawer-tabs"}
        role={"tablist"}
        aria-label={"运行详情"}
      >
        <button
          type={"button"}
          role={"tab"}
          aria-selected={activeTab === "trace"}
          aria-controls={"agent-trace-panel"}
          onClick={() => setActiveTab("trace")}
        >
          {"过程"}
        </button>
        <button
          type={"button"}
          role={"tab"}
          aria-selected={activeTab === "evidence"}
          aria-controls={"agent-evidence-panel"}
          onClick={() => setActiveTab("evidence")}
        >
          {"引用"}
        </button>
      </div>
      {activeTab === "trace" ? (
        <div
          className={"drawer-section agent-trace-section"}
          id={"agent-trace-panel"}
          role={"tabpanel"}
        >
          {approvals.length ? (
            <div className={"agent-approval-drawer-list"}>
              {approvals.map((approval) => (
                <AgentApprovalPrompt
                  approval={approval}
                  compact
                  key={approval.approvalId}
                />
              ))}
            </div>
          ) : null}
          <AgentTaskPlan
            messageId={messageId}
            run={run}
            trace={trace}
          />
          {!run?.steps?.length ? (
            <AgentTraceView trace={trace} />
          ) : null}
        </div>
      ) : (
        <div
          id={"agent-evidence-panel"}
          role={"tabpanel"}
        >
          <div className={"drawer-section"}>
            <div className={"section-label"}>{"引用来源"}</div>
            {ragQuality?.enabled ? (
              <div className={"rag-quality-card"} id={"rag-quality-card"}>
                <span className={"quality-level " + qualityLevel}>{qualityLabels[qualityLevel] || qualityLevel}</span>
                <strong>{"可信度"}</strong>
                <p>{ragQuality.reason || "已评估本次引用。"}</p>
                <div className={"quality-metrics"} id={"rag-quality-metrics"}>
                  <QualityMetric label={"命中"} value={ragQuality.hitCount || 0} />
                  <QualityMetric label={"最高分"} value={formatScore(ragQuality.maxScore)} />
                  <QualityMetric label={"平均分"} value={formatScore(ragQuality.avgScore)} />
                  <QualityMetric label={"偏弱"} value={ragQuality.belowThresholdCount || 0} />
                </div>
                <small>
                  {"强 " + (scoreBuckets.strong || 0) + " / 可用 " + (scoreBuckets.usable || 0) + " / 偏弱 " + (scoreBuckets.weak || 0)}
                  {retrievalRun?.id ? "，#" + retrievalRun.id : ""}
                </small>
              </div>
            ) : null}
            <div className={"reference-list"} id={"reference-list"}>
              {references.length ? (
                references.map((reference, index) => {
                  const score = Math.round(Number(reference.score || 0) * 100);
                  return (
                    <article className={"item"} key={reference.chunkId || reference.chunk_id || index}>
                      <h3>{reference.filename || "分段 #" + (reference.chunkId || reference.chunk_id)}</h3>
                      <p><span className={"badge ok"}>{"匹配 " + score + "%"}</span></p>
                      <p>{reference.content || reference.chunk_text || ""}</p>
                    </article>
                  );
                })
              ) : (
                <p className={"empty-state"}>{"本次回答没有引用片段。"}</p>
              )}
            </div>
          </div>
          <div className={"drawer-section"}>
            <div className={"section-label"}>{"工具记录"}</div>
            <div className={"timeline"} id={"tool-timeline-mini"}>
              {toolCalls.length ? (
                toolCalls.map((call, index) => {
                  const name = call.toolName || call.tool_name || call.name || "knowledge_search";
                  const input = call.inputJson || call.input_json || "";
                  const output = call.outputText || call.output_text || call.content || "";
                  const latency = call.latencyMs ?? call.latency_ms ?? 0;
                  return (
                    <div className={"timeline-item"} key={name + "-" + index}>
                      <div className={"timeline-dot"}></div>
                      <div>
                        <h4>{toolLabels[name] || name}</h4>
                        <p>{latency ? latency + " ms" : "已记录"}</p>
                        {input ? <pre>{typeof input === "string" ? input : JSON.stringify(input, null, 2)}</pre> : null}
                        {output ? <p>{output}</p> : null}
                      </div>
                    </div>
                  );
                })
              ) : (
                <p className={"empty-state"}>{"暂无工具记录"}</p>
              )}
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
