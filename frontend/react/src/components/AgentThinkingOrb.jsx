import { ThinkingOrb } from "thinking-orbs";


function currentThinkingStep(trace) {
  const steps = Array.isArray(trace) ? trace : [];
  return (
    [...steps].reverse().find((step) => [
      "planning",
      "running",
      "waiting",
      "waiting_approval",
    ].includes(String(step?.status || "")))
    || null
  );
}

export function agentThinkingState(trace = []) {
  const step = currentThinkingStep(trace);
  const signature = [
    step?.kind,
    step?.name,
    step?.title,
  ].filter(Boolean).join(" ").toLowerCase();

  if (/web[_ -]?(search|fetch)|联网|搜索/.test(signature)) {
    return "searching";
  }
  if (/mcp|connect|连接/.test(signature)) return "connecting";
  if (/memory|记忆|recall/.test(signature)) return "listening";
  if (/skill|技能|激活/.test(signature)) return "weaving";
  if (/workspace|sandbox|tool|工作区|沙箱|工具/.test(signature)) {
    return "working";
  }
  return "solving";
}

const stateLabels = {
  connecting: "正在连接工具",
  listening: "正在读取记忆",
  searching: "正在搜索",
  solving: "正在思考",
  weaving: "正在加载Skill",
  working: "正在执行",
};

export function AgentThinkingOrb({ trace = [] }) {
  const state = agentThinkingState(trace);
  const label = stateLabels[state] || stateLabels.solving;
  return (
    <div className={"agent-thinking-orb"} aria-live={"polite"}>
      <ThinkingOrb
        aria-label={label}
        className={"agent-thinking-orb-canvas"}
        size={20}
        speed={0.9}
        state={state}
        theme={"light"}
      />
      <span>{label}</span>
    </div>
  );
}
