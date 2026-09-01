// Run against local Vite with Playwright installed (or supplied via NODE_PATH).
// APIs are fixture-backed and the browser context is disposable.
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
const measureOnly = process.env.AGENTLENS_MEASURE_ONLY === "1";
const screenshotDir = process.env.AGENTLENS_SCREENSHOT_DIR;
const viewportWidth = Number(process.env.AGENTLENS_TEST_VIEWPORT_WIDTH) || 1280;
const page = await browser.newPage({ viewport: { width: viewportWidth, height: 800 } });
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
    "/api/auth/me": { authenticated: true, user: { id: 814, username: "long-chat", display_name: "长会话测试" } },
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

try {
  await page.goto(baseUrl);
  await page.getByRole("textbox", { name: "消息", exact: true }).waitFor({ state: "visible" });
  const appendDurationMs = await page.evaluate(() => {
    const startedAt = performance.now();
    for (let index = 1; index <= 1_000; index += 1) {
      const detail = {
        role: index % 2 ? "user" : "assistant",
        rawContent: `第${index}条虚拟消息 · ${index % 2 ? "用户问题" : "Agent回答"}`,
        thinking: false,
        streaming: false,
      };
      window.dispatchEvent(new CustomEvent("knowflow:react-message-append", { detail }));
      if (!detail.handled || !detail.messageId) throw new Error(`message ${index} was not accepted`);
    }
    return performance.now() - startedAt;
  });
  await page.waitForTimeout(120);
  const mountedRows = await page.locator(".message-row").count();
  console.log(JSON.stringify({ appendDurationMs: Math.round(appendDurationMs), mountedRows }));
  if (!measureOnly) {
    assert.equal(await page.locator("#chat-messages").getAttribute("data-message-count"), "1000");
    assert.ok(mountedRows < 120, `expected a bounded transcript DOM, mounted ${mountedRows} rows`);
    const horizontalOverflow = await page.locator("#chat-messages").evaluate(
      (node) => node.scrollWidth > node.clientWidth + 1,
    );
    assert.equal(horizontalOverflow, false, "virtualized transcript should keep its horizontal gutter inside the viewport");
    await page.getByText("第1000条虚拟消息 · Agent回答", { exact: true }).waitFor();

    await page.locator("#chat-messages").evaluate((node) => {
      node.scrollTop = 0;
      node.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await page.getByText("第1条虚拟消息 · 用户问题", { exact: true }).waitFor();
    await page.getByRole("button", { name: "回到对话底部", exact: true }).waitFor();

    await page.evaluate(() => {
      const detail = {
        role: "assistant",
        rawContent: "第1001条虚拟消息 · 新Agent输出",
        thinking: false,
        streaming: false,
      };
      window.dispatchEvent(new CustomEvent("knowflow:react-message-append", { detail }));
      if (!detail.handled) throw new Error("new output was not accepted");
    });
    const latest = page.getByRole("button", { name: "查看最新Agent输出", exact: true });
    await latest.waitFor();
    assert.equal(await page.getByText("第1001条虚拟消息 · 新Agent输出", { exact: true }).count(), 0);
    await latest.click();
    await page.getByText("第1001条虚拟消息 · 新Agent输出", { exact: true }).waitFor();
    await screenshot("latest.png");

    await page.keyboard.press("Control+f");
    const search = page.getByRole("search", { name: "搜索当前对话" }).getByRole("searchbox", { name: "搜索词" });
    await search.fill("第500条虚拟消息");
    const current = page.locator(".message-row.transcript-search-current");
    await current.waitFor();
    assert.match(await current.innerText(), /第500条虚拟消息/);
    assert.ok(await page.locator(".message-row").count() < 120);

    await page.keyboard.press("Escape");
    const commandHandled = await page.evaluate(() => {
      const detail = { action: "edit", handled: false };
      window.dispatchEvent(new CustomEvent("knowflow:react-message-command", { detail }));
      return detail.handled;
    });
    assert.equal(commandHandled, true, "offscreen edit command should be handled from logical state");
    await page.waitForFunction(
      () => document.querySelector('textarea[name="question"]')?.value === "第999条虚拟消息 · 用户问题",
    );
    assert.equal(
      await page.locator('textarea[name="question"]').inputValue(),
      "第999条虚拟消息 · 用户问题",
    );
  }

  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log(measureOnly
    ? "long transcript performance measured"
    : "long transcript browser checks passed: bounded DOM, reader-owned scroll, new output, jump to latest and offscreen search");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1600) });
  throw error;
} finally {
  await browser.close();
}
