// Deterministic UI regression checks. API fixtures never touch user data.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const screenshotDir = process.env.AGENTLENS_SCREENSHOT_DIR;
const errors = [];
const writes = [];
const now = Date.now();
let historyState = "populated";
let releaseHistory;
const historyGate = new Promise(resolve => { releaseHistory = resolve; });
const sessions = [
  ["pinned", "研究知识库检索策略与跨文件长标题边界", "completed"],
  ["running", "整理AgentLens前端", "running"],
  ["failed", "补充TUI启动测试", "failed"],
  ["today", "检查部署健康状态", "completed"],
  ["recent", "实现工作区文件引用", "completed"],
].map(([id, title, status], index) => ({
  id, title, is_pinned: index === 0,
  updated_at: new Date(now - (index === 4 ? 172800000 : index * 60000)).toISOString(),
  latest_run: { status, progress: { completed: 2, total: 5 }, durationMs: 35000 },
}));

page.on("pageerror", error => errors.push(error.message));
await page.route(url => url.pathname.startsWith("/api/"), async route => {
  const path = new URL(route.request().url()).pathname;
  if (route.request().method() !== "GET") writes.push(path);
  if (path === "/api/sessions" && historyState === "loading") {
    await historyGate;
  }
  if (path === "/api/sessions" && historyState === "error") {
    await route.fulfill({ status: 503, json: { code: 503, message: "fixture unavailable" } });
    return;
  }
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 981, username: "sidebar-test", display_name: "侧栏测试", email: "sidebar@example.test" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/sessions": historyState === "empty" ? [] : sessions,
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "fixture", modelType: "chat", enabled: true, isDefault: true }],
    "/api/approvals/pending": [],
  };
  await route.fulfill({ json: { code: 0, data: fixtures[path] ?? [] } });
});

async function screenshot(name) {
  if (!screenshotDir) return;
  // Let theme transitions and the existing history enter animation settle.
  await page.waitForTimeout(400);
  await mkdir(screenshotDir, { recursive: true });
  await page.screenshot({ path: resolve(screenshotDir, `${name}.png`) });
}

try {
  await page.goto(process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173");
  await page.locator(".session-title-text").first().waitFor();
  for (const [width, height] of [[1440, 960], [1280, 800]]) {
    await page.setViewportSize({ width, height });
    const metrics = await page.evaluate(() => {
      const style = selector => getComputedStyle(document.querySelector(selector));
      const bounds = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
      return {
        font: style(".session-title").fontSize,
        weight: style(".session-title").fontWeight,
        toolsDisplay: style(".sidebar-bottom-tools").display,
        toolsDirection: style(".sidebar-bottom-tools").flexDirection,
        newChatBackground: style(".new-chat-button").backgroundColor,
        sidebar: bounds("#sidebar"),
        history: bounds("#session-list"),
        tools: bounds(".sidebar-bottom-tools"),
        archive: bounds('.session-scope-tabs button:last-child'),
        task: bounds('.session-scope-tabs button:first-child'),
        pageOverflow: document.documentElement.scrollWidth > innerWidth,
      };
    });
    assert.equal(metrics.font, "14px");
    assert.ok(Number(metrics.weight) <= 500);
    assert.equal(metrics.toolsDisplay, "flex");
    assert.equal(metrics.toolsDirection, "column");
    assert.equal(metrics.newChatBackground, "rgb(31, 31, 28)");
    assert.equal(metrics.sidebar.width, 272);
    assert.ok(metrics.archive.right <= metrics.sidebar.right && metrics.archive.left >= metrics.task.right);
    assert.ok(metrics.history.height > 170);
    assert.ok(metrics.history.bottom <= metrics.tools.top + 1);
    assert.equal(metrics.pageOverflow, false);
    console.log({ viewport: `${width}x${height}`, historyHeight: metrics.history.height });
    for (const theme of ["mono-light", "mono-dark"]) {
      await page.evaluate(value => document.documentElement.setAttribute("data-theme", value), theme);
      await screenshot(`${width}-${theme}`);
    }
  }
  assert.equal(await page.locator(".session-row.completed .session-run-summary").count(), 0);
  assert.equal(await page.locator(".session-row.running .session-run-summary").count(), 1);
  assert.equal(await page.locator(".session-row.failed .session-run-summary").count(), 1);

  const account = page.locator("#user-menu-btn");
  await account.focus();
  await account.press("ArrowDown");
  await page.getByRole("menu", { name: "账户操作" }).waitFor();
  await page.waitForFunction(() => document.activeElement?.id === "diagnostic-copy-btn");
  await page.keyboard.press("ArrowDown");
  await page.waitForFunction(() => document.activeElement?.id === "logout-btn");
  assert.equal(await page.evaluate(() => document.activeElement?.id), "logout-btn");
  await screenshot("account-menu");
  await page.keyboard.press("Escape");
  await page.waitForFunction(() => document.activeElement?.id === "user-menu-btn");

  await page.getByRole("tab", { name: "任务", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  assert.equal(await page.getByRole("tab", { name: "已归档" }).getAttribute("aria-selected"), "true");
  await page.keyboard.press("Home");
  assert.equal(await page.getByRole("tab", { name: "任务", exact: true }).getAttribute("aria-selected"), "true");

  await page.locator("#sidebar-toggle").click();
  assert.equal(await page.locator("#sidebar").evaluate(node => node.getBoundingClientRect().width), 64);
  assert.equal(await page.locator("#session-history").isVisible(), false);
  await screenshot("collapsed");
  await page.locator("#sidebar-toggle").click();

  for (const [width, height] of [[390, 844], [375, 812]]) {
    await page.setViewportSize({ width, height });
    for (const theme of ["mono-light", "mono-dark"]) {
      await page.evaluate(value => document.documentElement.setAttribute("data-theme", value), theme);
      await page.locator("#mobile-history-btn").click();
      const drawer = page.locator(".chat-history-shell.mobile-history-open");
      await drawer.waitFor();
      await page.locator(".session-title-text").first().waitFor();
      assert.equal(await drawer.evaluate(node => node.scrollWidth > node.clientWidth + 1), false);
      const box = await drawer.boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= width + 1);
      await screenshot(`${width}-${theme}-history`);
      await page.keyboard.press("Escape");
      await drawer.waitFor({ state: "detached" });
      await screenshot(`${width}-${theme}-shell`);
    }
  }
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  historyState = "empty";
  await page.reload();
  await page.locator("#session-list .empty-state").waitFor();
  await screenshot("empty-reduced-motion");
  historyState = "error";
  await page.reload();
  await page.locator(".session-list-feedback").waitFor();
  await screenshot("error");
  historyState = "populated";
  await page.locator(".session-list-feedback button").click();
  await page.locator(".session-title-text").first().waitFor();
  historyState = "loading";
  const reload = page.reload({ waitUntil: "domcontentloaded" });
  await page.locator(".session-list-skeleton").waitFor();
  await screenshot("loading");
  historyState = "populated";
  releaseHistory();
  await reload;
  await page.locator(".session-title-text").first().waitFor();
  assert.deepEqual(errors, []);
  assert.deepEqual(writes, []);
  console.log("sidebar surface passed: four viewports, two themes, account keyboard/focus, scope keys, collapsed rail, empty/error recovery");
} finally {
  await browser.close();
}
