import { safeAgentText } from "../controller/agentEvents.js";


function count(value) {
  return Math.max(0, Number(value) || 0);
}


export function workspaceGitPresentation(status) {
  const git = status?.git && typeof status.git === "object" ? status.git : {};
  if (!git.repository) {
    return {
      repository: false,
      label: "",
      state: "available",
      title: "当前工作区不是Git仓库",
      details: [],
    };
  }
  const branch = safeAgentText(
    git.branch || (git.detached ? `detached@${git.head || "HEAD"}` : "Git仓库"),
    120,
  );
  const upstream = safeAgentText(git.upstream, 120);
  const changed = count(git.changedFiles);
  const staged = count(git.stagedFiles);
  const modified = count(git.modifiedFiles);
  const untracked = count(git.untrackedFiles);
  const conflicted = count(git.conflictedFiles);
  const ahead = count(git.ahead);
  const behind = count(git.behind);
  const sync = [ahead ? `↑${ahead}` : "", behind ? `↓${behind}` : ""]
    .filter(Boolean)
    .join(" ");
  const state = conflicted ? "conflict" : behind ? "behind" : changed ? "dirty" : "ready";
  const label = [
    branch,
    conflicted ? `${conflicted}个冲突` : changed ? `${changed}处改动` : "",
    sync,
  ].filter(Boolean).join(" · ");
  const details = [
    staged ? `${staged}个已暂存` : "",
    modified ? `${modified}个未暂存` : "",
    untracked ? `${untracked}个未跟踪` : "",
    conflicted ? `${conflicted}个冲突` : "",
  ].filter(Boolean);
  const tracking = upstream
    ? `${upstream}${ahead || behind ? `（领先${ahead}，落后${behind}）` : "（已同步）"}`
    : "未设置上游分支";
  return {
    repository: true,
    branch,
    label,
    state,
    details,
    title: [`Git：${branch}`, tracking, details.join("，") || "工作树干净"].join("。"),
  };
}
