const HIGHLIGHT_NAME = "agentlens-transcript-search";

function normalizedQuery(query) {
  return String(query ?? "").trim().toLocaleLowerCase();
}

/** Highlight rendered transcript text without mutating React-owned nodes. */
export function applyTranscriptSearchHighlights(container, query, currentIndex = 0) {
  const needle = normalizedQuery(query);
  if (!container || !needle || typeof document === "undefined") return () => {};
  const ranges = [];
  const roots = container.querySelectorAll(".message-markdown, .message.user");
  let matchIndex = 0;
  for (const root of roots) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const value = String(node.nodeValue ?? "");
      const lower = value.toLocaleLowerCase();
      let offset = 0;
      while (offset <= lower.length - needle.length) {
        const found = lower.indexOf(needle, offset);
        if (found < 0) break;
        const range = document.createRange();
        range.setStart(node, found);
        range.setEnd(node, found + needle.length);
        ranges.push({range, index: matchIndex, row: root.closest(".message-row")});
        matchIndex += 1;
        offset = found + Math.max(1, needle.length);
      }
      node = walker.nextNode();
    }
  }
  const highlights = window.CSS?.highlights;
  const fallbackMarks = [];
  if (highlights && typeof Highlight === "function") {
    highlights.delete(HIGHLIGHT_NAME);
    if (ranges.length) highlights.set(
      HIGHLIGHT_NAME,
      new Highlight(...ranges.map((entry) => entry.range)),
    );
  } else {
    // Older embedded Chromium/WebView builds do not expose CSS Custom
    // Highlight. Wrap only the transient hit text and unwrap it on cleanup.
    for (const entry of [...ranges].sort(
      (left, right) => right.range.startOffset - left.range.startOffset,
    )) {
      const mark = document.createElement("mark");
      mark.className = "agentlens-search-hit";
      try {
        entry.range.surroundContents(mark);
        fallbackMarks.push(mark);
      } catch {
        // A malformed DOM boundary should not make search unusable.
      }
    }
  }
  const selected = ranges[currentIndex] || null;
  if (selected?.row) {
    selected.row.dataset.searchHitCurrent = "true";
    const viewport = container.getBoundingClientRect();
    const rangeRect = selected.range.getBoundingClientRect();
    const rect = rangeRect.height ? rangeRect : selected.row.getBoundingClientRect();
    const outOfView = rect.top < viewport.top + 48 || rect.bottom > viewport.bottom - 48;
    if (outOfView) {
      const top = container.scrollTop + rect.top - viewport.top - (viewport.height - rect.height) / 2;
      const behavior = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
      if (typeof container.scrollTo === "function") {
        container.scrollTo({top, behavior});
      } else {
        container.scrollTop = top;
      }
    }
  }
  return () => {
    highlights?.delete(HIGHLIGHT_NAME);
    fallbackMarks.forEach((mark) => mark.replaceWith(document.createTextNode(mark.textContent || "")));
    container.querySelectorAll("[data-search-hit-current]").forEach((row) => {
      delete row.dataset.searchHitCurrent;
    });
    ranges.forEach(({range}) => range.detach?.());
  };
}
