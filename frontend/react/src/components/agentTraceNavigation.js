export function nextTraceStepId(stepIds, currentId, key) {
  const ids = Array.isArray(stepIds) ? stepIds.filter(Boolean) : [];
  if (!ids.length) return "";
  if (key === "Home") return ids[0];
  if (key === "End") return ids[ids.length - 1];
  const foundIndex = ids.indexOf(currentId);
  if (foundIndex < 0) return ids[0];
  const currentIndex = foundIndex;
  if (key === "ArrowDown") return ids[(currentIndex + 1) % ids.length];
  if (key === "ArrowUp") return ids[(currentIndex - 1 + ids.length) % ids.length];
  return ids[currentIndex];
}

export function visibleTraceWindow(rows, activeId, limit = 5) {
  const source = Array.isArray(rows) ? rows.filter(Boolean) : [];
  if (!source.length) return { rows: [], hiddenBefore: 0, hiddenAfter: 0 };

  const requestedLimit = Number(limit);
  const windowSize = Math.min(
    source.length,
    Math.max(1, Number.isFinite(requestedLimit) ? Math.floor(requestedLimit) : 5),
  );
  const normalizedActiveId = String(activeId || "");
  const activeIndex = source.findIndex(
    (row) => String(row?.id || "") === normalizedActiveId,
  );
  const maxStart = Math.max(0, source.length - windowSize);
  const centerOffset = Math.floor((windowSize - 1) / 2);
  const start = activeIndex < 0
    ? 0
    : Math.min(maxStart, Math.max(0, activeIndex - centerOffset));
  const end = start + windowSize;

  return {
    rows: source.slice(start, end),
    hiddenBefore: start,
    hiddenAfter: Math.max(0, source.length - end),
  };
}

export function resolveTreeSelectionId(
  stepIds,
  currentId,
  preferredId,
  userPinned = false,
) {
  const ids = Array.isArray(stepIds) ? stepIds.filter(Boolean) : [];
  if (!ids.length) return "";
  if (userPinned && !currentId) return "";
  if (userPinned && ids.includes(currentId)) return currentId;
  if (ids.includes(preferredId)) return preferredId;
  if (ids.includes(currentId)) return currentId;
  return ids[0];
}

export function matchesFocusScope(eventScope, componentScope) {
  if (!eventScope) return true;
  return eventScope === componentScope;
}
