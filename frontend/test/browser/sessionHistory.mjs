// Run against local Vite with Playwright installed (or supplied via NODE_PATH).
// API calls are fixture-backed so keyboard and touch checks stay disposable.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const screenshotDir = process.env.AGENTLENS_SCREENSHOT_DIR;
const errors = [];
const writes = [];
const sessions = [
  {
    id: "session-keyboard-1",
    title: "梳理Agent架构",
    updated_at: "2026-09-01 20:00:00",
    latest_run: { goalSummary: "梳理Agent架构", status: "completed" },
  },
  {
    id: "session-keyboard-2",
    title: "检查工作区改动",
    updated_at: "2026-08-31 20:00:00",
    latest_run: { goalSummary: "检查工作区改动", status: "completed" },
  },
  {
    id: "session-keyboard-3",
    title: "准备发布验证",
    updated_at: "2026-08-20 20:00:00",
    latest_run: { goalSummary: "准备发布验证", status: "completed" },
  },
];

page.on("pageerror", (error) => errors.push(error.message));
await page.route("**/api/**", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname;
  if (!path.startsWith("/api/")) {
    await route.continue();
    return;
  }
  if (request.method() !== "GET") writes.push(path);
  let data = [];
  if (path === "/api/auth/me") {
    data = { authenticated: true, user: { id: 812, username: "history-keyboard", display_name: "键盘测试" } };
  } else if (path === "/api/runtime") {
    data = { version: "test" };
  } else if (path === "/api/workspace" || path === "/api/memory/settings") {
    data = { enabled: false };
  } else if (path === "/api/model-configs") {
    data = [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }];
  } else if (path === "/api/skills") {
    data = [];
  } else if (path === "/api/sessions") {
    data = sessions;
  } else if (/^\/api\/sessions\/[^/]+\/messages$/.test(path)) {
    data = [];
  } else if (/^\/api\/sessions\/[^/]+\/context$/.test(path)) {
    data = {};
  }
  await route.fulfill({ json: { code: 0, data } });
});

const focused = (locator) => locator.evaluate((node) => node === document.activeElement);
async function screenshot(name) {
  if (!screenshotDir) return;
  await mkdir(screenshotDir, { recursive: true });
  await page.screenshot({ path: resolve(screenshotDir, name), fullPage: false });
}

try {
  await page.goto(baseUrl);
  const items = page.locator('#session-list button[data-session-item="true"]');
  await items.first().waitFor({ state: "visible" });
  assert.equal(await items.count(), sessions.length);
  assert.equal(await items.first().getAttribute("aria-label"), "梳理Agent架构，已完成");

  await items.first().focus();
  await page.keyboard.press("ArrowDown");
  assert.equal(await focused(items.nth(1)), true);
  await page.keyboard.press("ArrowDown");
  assert.equal(await focused(items.nth(2)), true);
  await page.keyboard.press("ArrowDown");
  assert.equal(await focused(items.first()), true, "down arrow wraps to the first task");
  await page.keyboard.press("End");
  assert.equal(await focused(items.nth(2)), true);
  await page.keyboard.press("Home");
  assert.equal(await focused(items.first()), true);
  await page.keyboard.press("ArrowUp");
  assert.equal(await focused(items.nth(2)), true, "up arrow wraps to the last task");
  await screenshot("desktop.png");

  await page.setViewportSize({ width: 390, height: 844 });
  const historyTrigger = page.locator("#mobile-history-btn");
  await historyTrigger.click();
  const history = page.locator('#session-history[aria-modal="true"]');
  await history.waitFor({ state: "visible" });
  const mobileItem = history.locator('button[data-session-item="true"]').first();
  const mobileMenu = history.locator(".session-menu-button").first();
  const itemBounds = await mobileItem.boundingBox();
  const menuBounds = await mobileMenu.boundingBox();
  assert.ok((itemBounds?.height || 0) >= 44, JSON.stringify(itemBounds));
  assert.ok((menuBounds?.width || 0) >= 40 && (menuBounds?.height || 0) >= 40, JSON.stringify(menuBounds));
  await screenshot("mobile.png");
  await page.keyboard.press("Escape");
  await history.waitFor({ state: "detached" });
  await page.waitForFunction(() => document.activeElement?.id === "mobile-history-btn");
  assert.equal(await focused(historyTrigger), true, "closing mobile history restores the trigger focus");
  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log("session history browser checks passed: arrow navigation, Home/End wrap, accessible labels, mobile touch targets, focus restore");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1200) });
  throw error;
} finally {
  await browser.close();
}
