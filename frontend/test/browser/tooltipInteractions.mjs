// Exercise real Radix interactions against Vite or the built preview. API data is disposable.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.AGENTLENS_CHROMIUM_PATH || undefined,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.setDefaultTimeout(10000);
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const artifacts = resolve(process.env.AGENTLENS_TEST_ARTIFACTS || "tmp/tooltips");
await mkdir(artifacts, { recursive: true });
const errors = [];
const writes = [];
page.on("pageerror", error => errors.push(error.message));
const mockApi = async route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (!path.startsWith("/api/")) {
    await route.continue();
    return;
  }
  if (request.method() !== "GET") writes.push(request.url());
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 999, username: "tooltip-test" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
  };
  await route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
};
await page.route("**/api/**", mockApi);
const tooltip = page.locator(".agentlens-tooltip");
const draft = page.getByRole("textbox", { name: "消息", exact: true });
const plus = page.locator("#composer-plus-btn");
const focused = locator => locator.evaluate(node => document.activeElement === node);

try {
  await page.goto(baseUrl);
  await draft.waitFor({ state: "visible" });
  await draft.fill("保留草稿，不要发送");
  await plus.hover();
  await tooltip.waitFor({ state: "visible" });
  assert.match(await page.getByRole("tooltip").innerText(), /添加文件或工具/);
  assert.equal(await plus.getAttribute("title"), null, "do not show two competing tooltips");
  assert.equal(await plus.getAttribute("aria-describedby"), await page.getByRole("tooltip").getAttribute("id"));
  assert.equal(await plus.evaluate(node => node.parentElement.classList.contains("composer-shell")), true);
  assert.equal(await page.locator("#chat-submit-btn").evaluate(node => node.parentElement.classList.contains("composer-shell")), true);
  await tooltip.hover();
  assert.equal(await tooltip.isVisible(), true, "the pointer can move into the hint without dismissing it");
  await page.screenshot({ path: resolve(artifacts, "desktop-hover.png"), animations: "disabled" });
  await page.keyboard.press("Escape");
  await tooltip.waitFor({ state: "detached" });

  await page.mouse.move(900, 400);
  await plus.focus();
  await tooltip.waitFor({ state: "visible" });
  await page.keyboard.press("Escape");
  await tooltip.waitFor({ state: "detached" });
  assert.equal(await focused(plus), true, "Escape must leave focus on the trigger");
  await plus.press("Enter");
  await page.locator("#composer-menu.open").waitFor({ state: "visible" });
  assert.equal(await tooltip.count(), 0, "the open menu replaces its trigger hint");
  await page.keyboard.press("Escape");
  await page.locator("#composer-menu.open").waitFor({ state: "detached" });
  assert.equal(await focused(plus), true);
  await plus.press("Enter");
  await page.locator("#composer-menu.open").waitFor({ state: "visible" });
  await page.keyboard.press("Tab");
  await page.keyboard.press("Escape");
  await page.locator("#composer-menu.open").waitFor({ state: "detached" });
  assert.equal(await focused(plus), true, "Escape from menu contents restores its trigger");
  assert.equal(await draft.inputValue(), "保留草稿，不要发送");

  const command = page.getByRole("button", { name: "打开命令面板", exact: true });
  await command.focus();
  await tooltip.waitFor({ state: "visible" });
  assert.equal(await tooltip.locator("kbd").first().innerText(), "Ctrl/⌘+K");
  await page.keyboard.press("Control+k");
  const palette = page.locator("#command-palette");
  await palette.waitFor({ state: "visible" });
  await tooltip.waitFor({ state: "detached" });
  await page.keyboard.press("Escape");
  await palette.waitFor({ state: "detached" });
  assert.equal(await focused(command), true);

  await page.locator("#sidebar-toggle").click();
  await page.locator("#sidebar.collapsed").waitFor();
  await page.mouse.move(1000, 150);
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const skills = page.locator('#sidebar-bottom-tools [data-page="skills"]');
  await skills.focus();
  await tooltip.waitFor({ state: "visible" });
  assert.match(await page.getByRole("tooltip").innerText(), /Skills/);
  await skills.press("Enter");
  await page.locator("#page-skills.active").waitFor();
  await tooltip.waitFor({ state: "detached" });
  await page.locator("#new-chat-btn").click();
  await draft.waitFor({ state: "visible" });
  assert.equal(await page.locator("#page-chat").evaluate(node => node.classList.contains("chat-empty")), true, "returning to a new conversation retains the empty-chat layout");

  await page.getByRole("button", { name: "切换到夜间模式", exact: true }).click();
  const theme = page.getByRole("button", { name: "切换到日间模式", exact: true });
  assert.equal(await focused(theme), true, "activation retains button focus but dismisses its tooltip");
  assert.equal(await tooltip.count(), 0);
  await page.mouse.move(800, 400);
  await draft.focus();
  await theme.focus();
  await tooltip.waitFor({ state: "visible" });
  const bounds = await tooltip.boundingBox();
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 1440 && bounds.y >= 0);
  assert.match(await page.getByRole("tooltip").innerText(), /切换到日间模式/);
  await page.screenshot({ path: resolve(artifacts, "desktop-dark.png"), animations: "disabled" });
  await page.emulateMedia({ reducedMotion: "reduce" });
  assert.equal(await tooltip.evaluate(node => getComputedStyle(node).animationName), "none");
  await page.keyboard.press("Escape");

  await page.setViewportSize({ width: 375, height: 812 });
  // The resizable workbench settles through ResizeObserver before focus can scroll it.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.mouse.move(180, 300);
  await page.locator("#chat-submit-btn").focus();
  await tooltip.waitFor({ state: "visible" });
  await page.waitForFunction(() => {
    const hint = document.querySelector(".agentlens-tooltip");
    return hint && hint.getBoundingClientRect().y >= 0;
  });
  const mobileBounds = await tooltip.boundingBox();
  assert.ok(mobileBounds.x >= 0 && mobileBounds.x + mobileBounds.width <= 375, JSON.stringify(mobileBounds));
  assert.ok(mobileBounds.y >= 0 && mobileBounds.y + mobileBounds.height <= 812, JSON.stringify(mobileBounds));
  await page.screenshot({ path: resolve(artifacts, "mobile-keyboard.png"), animations: "disabled" });
  await page.keyboard.press("Escape");
  await page.emulateMedia({ reducedMotion: "no-preference" });

  const touchPage = await browser.newPage({ viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
  touchPage.setDefaultTimeout(10000);
  touchPage.on("pageerror", error => errors.push(error.message));
  await touchPage.route("**/api/**", mockApi);
  await touchPage.addInitScript(() => {
    Object.defineProperty(window, "Notification", { configurable: true, value: undefined });
  });
  await touchPage.goto(baseUrl);
  const touchPlus = touchPage.locator("#composer-plus-btn");
  const touchMenu = touchPage.locator("#composer-menu.open");
  await touchPlus.tap();
  await touchMenu.waitFor({ state: "visible" });
  assert.equal(await touchPage.locator(".agentlens-tooltip").count(), 0, "a touch tap opens the action, not a hint");
  await touchPlus.tap();
  await touchMenu.waitFor({ state: "detached" });
  assert.equal(await touchPage.locator(".agentlens-tooltip").count(), 0);

  const unsupported = touchPage.getByRole("button", { name: "当前浏览器不支持桌面提醒", exact: true });
  assert.equal(await unsupported.getAttribute("aria-disabled"), "true");
  await unsupported.focus();
  await touchPage.locator(".agentlens-tooltip").waitFor({ state: "visible" });
  assert.match(await touchPage.getByRole("tooltip").innerText(), /不支持桌面提醒/);
  await unsupported.press("Enter");
  assert.equal(await unsupported.getAttribute("aria-pressed"), "false", "disabled actions remain inert while focusable for explanation");
  await touchPage.close();
  assert.deepEqual(writes, [], "tooltip interactions and navigation cannot write API data");
  assert.deepEqual(errors, []);
  console.log("tooltip browser checks passed: hover, keyboard, Escape, portal bounds, direct-child DOM, menu/palette coexistence, collapsed sidebar, themes, reduced motion, touch, disabled reason");
} catch (error) {
  console.error("Tooltip fixture failed", {
    errors,
    browser: browser.version(),
    layout: await page.evaluate(() => ({
      viewport: [innerWidth, innerHeight],
      page: document.getElementById("page-chat")?.className,
      send: document.getElementById("chat-submit-btn")?.getBoundingClientRect().toJSON(),
      tooltip: document.querySelector(".agentlens-tooltip")?.getBoundingClientRect().toJSON(),
    })),
    body: (await page.locator("body").innerText()).slice(0, 2000),
  });
  throw error;
} finally {
  await browser.close();
}
