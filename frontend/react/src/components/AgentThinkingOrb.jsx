import { useEffect, useMemo, useRef, useState } from "react";
import { ThinkingOrb } from "thinking-orbs";


function currentThinkingStep(trace) {
  const steps = Array.isArray(trace) ? trace : [];
  return (
    [...steps].reverse().find((step) => [
      "planning",
      "running",
      "waiting",
      "waiting_approval",
      "waiting_input",
    ].includes(String(step?.status || "")))
    || null
  );
}

function resolveOrbTheme() {
  if (typeof document === "undefined") return "light";
  return document.documentElement?.dataset?.theme === "mono-dark"
    ? "dark"
    : "light";
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

export function AgentThinkingOrb({ trace = [], state: requestedState = "", label: requestedLabel = "" }) {
  const next = useMemo(() => {
    const state = requestedState || agentThinkingState(trace);
    return {
      label: requestedLabel || stateLabels[state] || stateLabels.solving,
      state,
    };
  }, [requestedLabel, requestedState, trace]);
  const [stable, setStable] = useState(next);
  const [orbTheme, setOrbTheme] = useState(resolveOrbTheme);
  const committedAtRef = useRef(Date.now());

  useEffect(() => {
    const root = document.documentElement;
    const updateTheme = () => setOrbTheme(resolveOrbTheme());
    updateTheme();
    if (typeof MutationObserver === "undefined") return undefined;
    const observer = new MutationObserver(updateTheme);
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (stable.state === next.state && stable.label === next.label) return undefined;
    const remaining = Math.max(0, 2000 - (Date.now() - committedAtRef.current));
    const commit = () => {
      committedAtRef.current = Date.now();
      setStable(next);
    };
    if (!remaining) {
      commit();
      return undefined;
    }
    const timer = window.setTimeout(commit, remaining);
    return () => window.clearTimeout(timer);
  }, [next, stable.label, stable.state]);

  return (
    <div className={"agent-thinking-orb"} aria-atomic={"true"} aria-live={"polite"}>
      <ThinkingOrb
        aria-label={stable.label}
        className={"agent-thinking-orb-canvas"}
        size={20}
        speed={0.9}
        state={stable.state}
        theme={orbTheme}
      />
      <span>{stable.label}</span>
    </div>
  );
}
