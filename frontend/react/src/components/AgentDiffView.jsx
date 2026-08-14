import { useMemo } from "react";
import { buildAgentDiffPresentation } from "./agentRunPresentation.js";

export function AgentDiffView({ patch = "", loading = false }) {
  const rows = useMemo(() => buildAgentDiffPresentation(patch), [patch]);
  if (loading) return <div className={"agent-diff-loading"}>{"正在读取差异…"}</div>;
  if (!rows.length) return <div className={"agent-diff-empty"}>{"没有可显示的文本差异。"}</div>;
  return (
    <div className={"agent-diff-view"} role={"region"} aria-label={"文件差异"} tabIndex={0}>
      {rows.map((row, index) => (
        <div className={`agent-diff-line is-${row.kind}`} key={`${index}:${row.oldLine}:${row.newLine}`}>
          <span className={"agent-diff-old"}>{row.oldLine ?? ""}</span>
          <span className={"agent-diff-new"}>{row.newLine ?? ""}</span>
          <code>{row.text || " "}</code>
        </div>
      ))}
    </div>
  );
}
