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
  await page.evaluate((rawContent) => {
    const detail = { role: "assistant", rawContent, thinking: false, streaming: false };
    window.dispatchEvent(new CustomEvent("knowflow:react-message-append", { detail }));
    if (!detail.handled || !detail.messageId) throw new Error("assistant code message was not accepted");
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
  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log("message code block browser checks passed: language label, highlight.js tokens, redacted copy state, mobile bounds and touch target");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1400) });
  throw error;
} finally {
  await browser.close();
}
