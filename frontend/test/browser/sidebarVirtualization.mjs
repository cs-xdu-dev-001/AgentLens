// Run against local Vite with Playwright installed (or supplied via NODE_PATH).
// The session endpoint is fixture-backed so this test never mutates the server.
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
const now = Date.now();
const sessions = Array.from({ length: 1_000 }, (_, index) => {
  const number = index + 1;
  const updatedAt = new Date(now - index * 60_000).toISOString().replace("T", " ").slice(0, 19);
  return {
    id: `session-${number}`,
    title: `任务 ${number}`,
    is_pinned: index === 0,
    updated_at: updatedAt,
    created_at: updatedAt,
    latest_run: {
      status: "completed",
      progress: { completed: 1, total: 1 },
      durationMs: 700 + number,
    },
  };
});

async function screenshot(name) {
  if (!screenshotDir) return;
  await mkdir(screenshotDir, { recursive: true });
  await page.screenshot({ path: resolve(screenshotDir, name), fullPage: false });
}

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
    "/api/auth/me": { authenticated: true, user: { id: 816, username: "sidebar-large", display_name: "侧栏测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/sessions": sessions,
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/skills": [],
  };
  await route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});

try {
  await page.goto(baseUrl);
  const sessionList = page.locator("#session-list");
  await sessionList.waitFor({ state: "visible" });
  await page.waitForFunction(() => (
    document.querySelector("#session-list")?.getAttribute("data-session-count") === "1000"
  ));
  await page.waitForTimeout(180);

  assert.equal(await sessionList.getAttribute("data-virtualized"), "true");
  assert.equal(await sessionList.getAttribute("data-session-count"), "1000");
  const mountedRows = await sessionList.locator('button[data-session-item="true"]').count();
  console.log(JSON.stringify({ logicalSessions: 1_000, mountedRows }));
  assert.ok(
    mountedRows < 120,
    "large session history should keep a bounded DOM",
  );
  await page.getByRole("button", { name: "任务 1，已完成", exact: true }).waitFor();

  const firstSession = sessionList.locator('button[data-session-item="true"]').first();
  await firstSession.focus();
  await firstSession.press("End");
  await page.waitForFunction(() => document.activeElement?.getAttribute("data-session-index") === "999");
  assert.match(await page.evaluate(() => document.activeElement?.textContent || ""), /任务 1000/);

  const lastSession = sessionList.locator('button[data-session-item="true"]').filter({ hasText: "任务 1000" });
  await lastSession.press("Home");
  await page.waitForFunction(() => document.activeElement?.getAttribute("data-session-index") === "0");

  const search = page.locator("#sidebar-session-search");
  await search.fill("任务 777");
  await page.waitForFunction(() => document.querySelector("#session-list")?.getAttribute("data-session-count") === "1");
  await page.waitForTimeout(220);
  assert.equal(await sessionList.locator('button[data-session-item="true"]').count(), 1);
  await page.getByRole("button", { name: "任务 777，已完成", exact: true }).waitFor();
  await search.fill("");
  await page.waitForFunction(() => document.querySelector("#session-list")?.getAttribute("data-session-count") === "1000");
  assert.equal(await sessionList.getAttribute("data-virtualized"), "true");
  await sessionList.locator('button[data-session-item="true"]').first().waitFor({ state: "visible" });
  assert.ok(await sessionList.locator('button[data-session-item="true"]').count() > 0);
  await screenshot("sidebar-desktop.png");

  await page.setViewportSize({ width: 375, height: 812 });
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-sidebar-open")));
  const mobileHistory = page.locator(".chat-history-shell.mobile-history-open");
  await mobileHistory.waitFor({ state: "visible" });
  const mobileList = mobileHistory.locator("#session-list");
  await mobileList.waitFor({ state: "visible" });
  const mobileBounds = await mobileHistory.boundingBox();
  const mobileListBounds = await mobileList.boundingBox();
  assert.ok(mobileBounds && mobileBounds.x >= 0 && mobileBounds.x + mobileBounds.width <= 375);
  assert.ok(mobileListBounds && mobileListBounds.height > 320);
  await mobileList.locator('button[data-session-item="true"]').first().waitFor({ state: "visible" });
  const mobileMountedRows = await mobileList.locator('button[data-session-item="true"]').count();
  assert.ok(mobileMountedRows > 0 && mobileMountedRows < 120);
  assert.equal(await mobileList.evaluate((node) => node.scrollWidth > node.clientWidth + 1), false);
  assert.equal(await mobileHistory.evaluate((node) => node.scrollWidth > node.clientWidth + 1), false);
  const mobileMenuTrigger = mobileHistory.locator(".session-menu-button").first();
  await mobileMenuTrigger.click();
  const mobileMenu = page.getByRole("menu");
  await mobileMenu.waitFor({ state: "visible" });
  assert.equal(await mobileMenuTrigger.getAttribute("aria-expanded"), "true");
  assert.equal(await mobileMenuTrigger.getAttribute("aria-controls"), "session-action-menu");
  assert.equal(await mobileMenu.getAttribute("id"), "session-action-menu");
  assert.equal(
    await mobileHistory.evaluate((history) => history.contains(document.querySelector('[role="menu"]'))),
    true,
  );
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("role")), "menuitem");
  await page.keyboard.press("Escape");
  await mobileMenu.waitFor({ state: "detached" });
  await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label")?.startsWith("会话操作："));
  assert.equal(await mobileMenuTrigger.getAttribute("aria-expanded"), "false");
  assert.match(
    await page.evaluate(() => document.activeElement?.getAttribute("aria-label") || ""),
    /^会话操作：/,
  );
  await mobileHistory.waitFor({ state: "visible" });
  await screenshot("sidebar-mobile.png");

  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log("sidebar browser checks passed: bounded history DOM, logical keyboard navigation, search reset, mobile focus trap and 375px overlay");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 2400) });
  throw error;
} finally {
  await browser.close();
}
