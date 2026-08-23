import Fuse from "fuse.js";

const MAX_WORKSPACE_MENTIONS = 15;

export function workspaceMentionAtCursor(input, cursorOffset = String(input ?? "").length) {
  const value = String(input ?? "");
  const cursor = Math.max(0, Math.min(value.length, Number(cursorOffset) || 0));
  const prefix = value.slice(0, cursor);
  const quoted = prefix.match(/(?:^|\s)(@"([^"\n]*))$/u);
  const bare = prefix.match(/(?:^|\s)(@([^\s@]*))$/u);
  const match = quoted ?? bare;
  if (!match) return null;
  const token = match[1];
  return {
    start: cursor - token.length,
    end: cursor,
    query: match[2] ?? "",
  };
}

export function workspaceMentionSuggestions(paths, query, limit = MAX_WORKSPACE_MENTIONS) {
  const available = [...new Set((paths ?? []).map((path) => String(path || "")).filter(Boolean))];
  const normalizedQuery = String(query || "").trim().toLocaleLowerCase();
  if (!normalizedQuery) {
    return available.filter((path) => !path.slice(0, -1).includes("/")).slice(0, limit);
  }
  return new Fuse(available.map((path) => ({ path })), {
    threshold: 0.35,
    location: 0,
    distance: 120,
    ignoreLocation: false,
    keys: ["path"],
  }).search(normalizedQuery, { limit }).map((result) => result.item.path);
}

export function workspaceMentionCommonPrefix(paths) {
  const available = (paths ?? []).map((path) => String(path || "")).filter(Boolean);
  if (!available.length) return "";
  let prefix = available[0];
  for (const path of available.slice(1)) {
    let index = 0;
    while (index < prefix.length && index < path.length && prefix[index] === path[index]) {
      index += 1;
    }
    prefix = prefix.slice(0, index);
    if (!prefix) break;
  }
  return prefix;
}

export function applyWorkspaceMention(input, range, path, { complete = true } = {}) {
  const value = String(input ?? "");
  const mentionPath = String(path ?? "");
  const replacement = mentionPath.includes(" ")
    ? complete ? `@"${mentionPath}"` : `@"${mentionPath}`
    : `@${mentionPath}`;
  const suffix = complete ? " " : "";
  const next = `${value.slice(0, range.start)}${replacement}${suffix}${value.slice(range.end)}`;
  return {
    value: next,
    cursor: range.start + replacement.length + suffix.length,
  };
}
