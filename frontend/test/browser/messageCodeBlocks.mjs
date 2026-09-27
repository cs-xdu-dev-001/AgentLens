// Run against local Vite with Playwright installed (or supplied via NODE_PATH).
// The message is injected through the public React event bridge; APIs are fixtures.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
await context.grantPermissions(["clipboard-read", "clipboard-write"], { origin: baseUrl });
const page = await context.newPage();
const screenshotDir = process.env.AGENTLENS_SCREENSHOT_DIR;
const errors = [];
const writes = [];

page.on("pageerror", (error) => errors.push(error.message));
await page.route("**/api/**", async (route) => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (!path.startsWith("/api/")) {
    await route.continue();
    return;
  }
  if (request.method() !== "GET") writes.push(path);
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 813, username: "code-blocks", display_name: "代码块测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/sessions": [],
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/skills": [],
  };
  await route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});

async function screenshot(name) {
  if (!screenshotDir) return;
  await mkdir(screenshotDir, { recursive: true });
  await page.screenshot({ path: resolve(screenshotDir, name), fullPage: false });
}

const markdown = [
  "可以直接运行：",
  "",
  "```js",
  "const answer = 42;",
  "token=SECRET_VALUE",
  "console.log(answer);",
  "```",
].join("\n");

try {
  await page.goto(baseUrl);
  await page.getByRole("textbox", { name: "消息", exact: true }).waitFor({ state: "visible" });
  const messageId = await page.evaluate((rawContent) => {
    const detail = { role: "assistant", rawContent, thinking: false, streaming: false };
    window.dispatchEvent(new CustomEvent("knowflow:react-message-append", { detail }));
    if (!detail.handled || !detail.messageId) throw new Error("assistant code message was not accepted");
    return detail.messageId;
  }, markdown);

  const block = page.locator(".message-code-block");
  const code = block.locator("code.hljs");
  const copy = block.getByRole("button", { name: "复制代码", exact: true });
  await block.waitFor({ state: "visible" });
  assert.equal(await block.getAttribute("data-code-language"), "JavaScript");
  assert.equal(await block.locator(".message-code-language").innerText(), "JavaScript");
  await code.locator(".hljs-keyword").waitFor({ state: "attached" });
  assert.ok(await code.locator(".hljs-keyword").count());
  assert.ok(await code.locator(".hljs-number").count());
  assert.match(await code.innerText(), /const answer = 42;/);
  await copy.click();
  await page.getByRole("button", { name: "已复制代码", exact: true }).waitFor();
  const copied = await page.evaluate(() => navigator.clipboard.readText());
  assert.match(copied, /const answer = 42;/);
  assert.match(copied, /token=\[已隐藏\]/);
  assert.doesNotMatch(copied, /SECRET_VALUE/);
  await screenshot("desktop.png");

  await page.setViewportSize({ width: 390, height: 844 });
  const buttonBounds = await copy.boundingBox();
  const blockBounds = await block.boundingBox();
  assert.ok((buttonBounds?.height || 0) >= 44, JSON.stringify(buttonBounds));
  assert.ok((blockBounds?.x || 0) >= 0 && (blockBounds?.x || 0) + (blockBounds?.width || 0) <= 390, JSON.stringify(blockBounds));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await screenshot("mobile.png");

  const longCode = Array.from({ length: 100 }, (_, i) => (
    `const result${i} = "${"long-workspace-path/".repeat(12)}";`
  )).join("\n");
  let streamContent = `正在检查代码：\n\n\`\`\`js\n${longCode}\n\`\`\`\n`;
  async function updateContent(rawContent, streaming = true) {
    await page.evaluate((detail) => {
      window.dispatchEvent(new CustomEvent("knowflow:react-message-content", { detail }));
      if (!detail.handled) throw new Error("stream content update was not accepted");
    }, { messageId, rawContent, streaming });
    await page.waitForFunction((expected) => (
      document.querySelector(".message.assistant")?.dataset.rawContent === expected
    ), rawContent);
  }
  await updateContent(streamContent);
  const pre = block.locator("pre");
  await pre.evaluate((node) => { node.scrollLeft = 200; });
  assert.equal(await pre.evaluate((node) => node.scrollLeft), 200);
  streamContent += "\n继续分析，不应打断代码阅读。";
  await updateContent(streamContent);
  assert.equal(await pre.evaluate((node) => node.scrollLeft), 200, "streaming must preserve horizontal code reading position");

  for (const [width, height, theme] of [
    [1440, 960, "mono-light"], [1280, 800, "mono-dark"],
    [390, 844, "mono-dark"], [375, 812, "mono-light"], [320, 568, "mono-light"],
  ]) {
    await page.setViewportSize({ width, height });
    await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
    await pre.scrollIntoViewIfNeeded();
    const bounds = await pre.boundingBox();
    assert.ok(bounds && bounds.height <= Math.min(height / 2, 480) + 1, JSON.stringify(bounds));
    assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width, JSON.stringify(bounds));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await pre.focus();
    await pre.evaluate((node) => { node.scrollLeft = 200; node.scrollTop = 120; });
    streamContent += `\n已完成第${width}项检查。`;
    await updateContent(streamContent);
    assert.deepEqual(await pre.evaluate((node) => ({
      left: node.scrollLeft, top: node.scrollTop, focused: document.activeElement === node,
    })), { left: 200, top: 120, focused: true });
    await screenshot(`code-long-${width}-${theme}.png`);
  }
  await pre.press("Control+Home");
  await page.waitForFunction(() => document.querySelector(".message-code-block pre").scrollTop === 0);
  await pre.press("ArrowRight");
  await page.waitForFunction(() => document.querySelector(".message-code-block pre").scrollLeft > 0);

  // The copy control must keep keyboard focus too, but an unrelated composer
  // focus must never be reclaimed when the stream replaces its HTML.
  await copy.focus();
  streamContent += "\n复制入口仍可操作。";
  await updateContent(streamContent);
  assert.equal(await copy.evaluate((node) => document.activeElement === node), true);
  const composer = page.getByRole("textbox", { name: "消息", exact: true });
  await composer.focus();
  streamContent += "\n继续输出，不抢输入焦点。";
  await updateContent(streamContent);
  assert.equal(await composer.evaluate((node) => document.activeElement === node), true);

  const headings = Array.from({ length: 12 }, (_, i) => `字段_column_${i}`);
  const tableContent = [
    `| ${headings.join(" | ")} |`,
    `| ${headings.map(() => "---").join(" | ")} |`,
    `| ${headings.map((_, i) => `value_${i}`).join(" | ")} |`,
  ].join("\n");
  streamContent += `\n\n${tableContent}\n`;
  await updateContent(streamContent);
  const table = page.getByRole("region", { name: "表格", exact: true });
  await table.focus();
  await table.press("ArrowRight");
  await page.waitForFunction(() => document.querySelector(".message-table-scroll").scrollLeft > 0);
  // Let the browser's native key-scroll animation finish before setting the
  // exact reading position used by the stream regression assertion.
  await page.waitForTimeout(200);
  await table.evaluate((node) => { node.scrollLeft = 180; });
  streamContent += `| ${headings.map((_, i) => `next_${i}`).join(" | ")} |\n`;
  await updateContent(streamContent);
  assert.equal(await table.evaluate((node) => node.scrollLeft), 180);
  assert.equal(await table.evaluate((node) => document.activeElement === node), true);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await screenshot("table-streaming-mobile.png");

  // Completing a stream keeps reading position while deferred highlighting
  // upgrades the code. A genuine content replacement starts a fresh context.
  await pre.focus();
  await pre.evaluate((node) => { node.scrollLeft = 200; node.scrollTop = 120; });
  await updateContent(streamContent, false);
  await code.locator(".hljs-keyword").first().waitFor();
  assert.equal(await pre.evaluate((node) => node.scrollLeft), 200);
  assert.equal(await pre.evaluate((node) => node.scrollTop), 120);
  await updateContent(`\`\`\`js\n${longCode}\n// replacement\n\`\`\``, false);
  assert.equal(await pre.evaluate((node) => node.scrollLeft), 0);
  assert.equal(await pre.evaluate((node) => node.scrollTop), 0);
  streamContent = `\`\`\`js\n${longCode}`;
  await updateContent(streamContent);
  await pre.focus();
  await pre.evaluate((node) => { node.scrollLeft = 200; node.scrollTop = 120; });
  streamContent += "\nconst streamedLastLine = 101;";
  await updateContent(streamContent);
  assert.equal(await pre.evaluate((node) => node.scrollLeft), 200);
  assert.equal(await pre.evaluate((node) => node.scrollTop), 120);
  await updateContent(`${streamContent}\n\`\`\``, false);
  await code.locator(".hljs-keyword").first().waitFor();
  assert.equal(await pre.evaluate((node) => node.scrollLeft), 200);
  assert.equal(await pre.evaluate((node) => document.activeElement === node), true);
  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log("message code block browser checks passed: highlighting, redacted copy, bounded long code, keyboard scrolling, stream scroll/focus preservation, wide tables and replacement reset");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1400) });
  throw error;
} finally {
  await browser.close();
}
