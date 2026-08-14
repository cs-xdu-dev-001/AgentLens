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
