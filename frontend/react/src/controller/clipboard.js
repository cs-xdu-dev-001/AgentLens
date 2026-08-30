function restoreSelection(selection, ranges) {
  if (!selection) return;
  selection.removeAllRanges?.();
  ranges.forEach((range) => selection.addRange?.(range));
}

function copyWithLegacyCommand(value) {
  const document = globalThis.document;
  if (!document?.createElement || !document.body?.appendChild) {
    throw new Error("Clipboard API unavailable");
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute?.("readonly", "true");
  textarea.setAttribute?.("aria-hidden", "true");
  if (textarea.style) {
    textarea.style.position = "fixed";
    textarea.style.top = "-9999px";
    textarea.style.left = "-9999px";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
  }
  const selection = document.getSelection?.();
  const ranges = selection
    ? Array.from(
      { length: selection.rangeCount || 0 },
      (_, index) => selection.getRangeAt(index).cloneRange(),
    )
    : [];
  document.body.appendChild(textarea);
  let copied = false;
  try {
    textarea.focus?.({ preventScroll: true });
    textarea.select?.();
    textarea.setSelectionRange?.(0, value.length);
    copied = Boolean(document.execCommand?.("copy"));
  } finally {
    textarea.remove?.();
    restoreSelection(selection, ranges);
  }
  if (!copied) throw new Error("Clipboard API unavailable");
}

export async function copyTextToClipboard(value) {
  const text = String(value ?? "");
  const clipboard = globalThis.navigator?.clipboard;
  if (typeof clipboard?.writeText === "function") {
    try {
      await clipboard.writeText(text);
      return;
    } catch {
      // Fall through when permissions or the browser context block Clipboard API.
    }
  }
  copyWithLegacyCommand(text);
}
