export const CHAT_SCROLL_PIN_THRESHOLD = 96;

export function isChatViewportPinned(viewport, threshold = CHAT_SCROLL_PIN_THRESHOLD) {
  if (!viewport) return true;
  const scrollHeight = Math.max(0, Number(viewport.scrollHeight) || 0);
  const scrollTop = Math.max(0, Number(viewport.scrollTop) || 0);
  const clientHeight = Math.max(0, Number(viewport.clientHeight) || 0);
  const remaining = Math.max(0, scrollHeight - scrollTop - clientHeight);
  return remaining <= Math.max(0, Number(threshold) || 0);
}

export function shouldFollowChatUpdate({ pinned = true, force = false } = {}) {
  return Boolean(force || pinned);
}
