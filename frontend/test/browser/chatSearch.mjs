// Run against the local Vite server with Playwright installed (or on NODE_PATH).
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const page = await browser.newPage({ viewport: { width: 960, height: 640 } });
await page.emulateMedia({ reducedMotion: "reduce" });
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";

try {
  await page.goto(baseUrl);
  const result = await page.evaluate(async () => {
    const { applyTranscriptSearchHighlights } = await import("/src/controller/chatSearch.js");
    const container = document.createElement("div");
    container.style.cssText = "height:120px;overflow:auto;border:1px solid transparent";
    container.innerHTML = Array.from({length: 12}, (_, index) => (
      `<div class="message-row"><div class="message user">第${index + 1}条内容</div></div>`
    )).join("");
    document.body.append(container);
    const cleanup = applyTranscriptSearchHighlights(container, "内容", 8);
    await new Promise((resolve) => setTimeout(resolve, 120));
    const current = container.querySelector('[data-search-hit-current="true"]');
    const highlighted = Boolean(window.CSS?.highlights?.has("agentlens-transcript-search"));
    const scrolled = container.scrollTop > 0;
    cleanup();
    return {
      highlighted: highlighted || container.querySelectorAll(".agentlens-search-hit").length === 12,
      scrolled,
      current: current?.textContent || "",
      cleaned: !window.CSS?.highlights?.has("agentlens-transcript-search")
        && !container.querySelector(".agentlens-search-hit")
        && !container.querySelector("[data-search-hit-current]"),
    };
  });
  console.log(result);
  assert.equal(result.highlighted, true);
  assert.equal(result.scrolled, true);
  assert.equal(result.current, "第9条内容");
  assert.equal(result.cleaned, true);
  console.log("chat search browser checks passed: all-hit highlight, exact occurrence reveal, and cleanup");
} finally {
  await browser.close();
}
