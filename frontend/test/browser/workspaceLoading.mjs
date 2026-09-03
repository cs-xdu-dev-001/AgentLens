// Run against the local Vite server with Playwright installed (or on NODE_PATH).
// API calls are fixture-backed; the browser context is disposable.
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({
  headless: true,
  ...(process.env.AGENTLENS_CHROMIUM_PATH
    ? { executablePath: process.env.AGENTLENS_CHROMIUM_PATH }
    : {}),
});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
let workspaceStatusCalls = 0;
let listingCalls = 0;
let previewCalls = 0;
let statusMode = "ready";
let statusGate = null;
page.on("pageerror", (error) => errors.push(error.message));

await page.route("**/api/**", async (route) => {
  const request = route.request();
  const requestUrl = new URL(request.url());
  const path = requestUrl.pathname;
  if (!path.startsWith("/api/")) return route.continue();
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 903, username: "workspace-loading-test", display_name: "工作区测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: true, isolation: "user", itemCount: 2, sandboxReady: true, protectedPatterns: [".env"], git: { repository: true, branch: "main", dirty: false } },
    "/api/memory/settings": { enabled: false },
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/workspace/files": { path: "", entries: [
      { path: "docs", kind: "directory" },
      { path: "README.md", kind: "file", size: 33 },
    ] },
    "/api/workspace/files/README.md": {
      path: "README.md",
      name: "README.md",
      size: 33,
      mimeType: "text/markdown",
      previewable: true,
      truncated: false,
      content: "# AgentLens\n\nWorkspace preview.",
    },
  };
  if (path === "/api/workspace") {
    workspaceStatusCalls += 1;
    if (statusMode === "error") return route.fulfill({ status: 503, json: { message: "Workspace unavailable" } });
    if (statusGate) {
      const gate = statusGate;
      statusGate = null;
      gate(route);
      return;
    }
    if (statusMode === "disabled") fixtures[path] = { enabled: false };
    if (workspaceStatusCalls <= 2) await new Promise((resolve) => setTimeout(resolve, 280));
  }
  if (path === "/api/workspace/files") {
    listingCalls += 1;
    await new Promise((resolve) => setTimeout(resolve, listingCalls === 1 ? 420 : 320));
  }
  if (path === "/api/workspace/files/README.md" && requestUrl.searchParams.get("preview") === "true") {
    previewCalls += 1;
  }
  return route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});

try {
  await page.goto(baseUrl);
  const composer = page.getByRole("textbox", { name: "消息", exact: true });
  await composer.waitFor({ state: "visible" });
  const welcomeActions = page.getByRole("navigation", { name: "常用起始任务" });
  await welcomeActions.waitFor({ state: "visible" });
  assert.equal(await welcomeActions.getByRole("button").count(), 4);
  const welcomeStatus = page.locator(".welcome-context");
  await page.locator('.welcome-context[data-workspace-state="ready"]').waitFor();
  assert.equal(await welcomeStatus.innerText(), "打开当前工作区");
  await page.emulateMedia({ reducedMotion: "reduce" });
  assert.equal(await page.locator(".welcome-card").evaluate((node) => getComputedStyle(node).animationName), "none");
  await welcomeActions.getByRole("button", { name: "梳理项目结构", exact: true }).focus();
  assert.notEqual(await page.locator(".welcome-action:focus-visible").evaluate((node) => getComputedStyle(node).outlineStyle), "none");
  await composer.focus();
  if (process.env.AGENTLENS_EMPTY_DESKTOP_SCREENSHOT_PATH) {
    await page.screenshot({ path: process.env.AGENTLENS_EMPTY_DESKTOP_SCREENSHOT_PATH, fullPage: true });
  }
  await page.setViewportSize({ width: 375, height: 812 });
  // Read the responsive layout after the workbench ResizeObserver has committed it.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const sendBounds = await page.locator("#chat-submit-btn").boundingBox();
  assert.ok(sendBounds && sendBounds.y >= 0 && sendBounds.y + sendBounds.height <= 812, JSON.stringify(sendBounds));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  if (process.env.AGENTLENS_EMPTY_MOBILE_SCREENSHOT_PATH) {
    await page.screenshot({ path: process.env.AGENTLENS_EMPTY_MOBILE_SCREENSHOT_PATH, fullPage: true });
  }
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByRole("button", { name: "切换到夜间模式", exact: true }).click();
  await page.locator('body[data-theme="mono-dark"]').waitFor();
  assert.equal(await page.evaluate(() => localStorage.getItem("knowflow-theme")), "mono-dark");
  const welcomeContrast = await welcomeStatus.evaluate((node) => {
    const channels = (value) => value.match(/[\d.]+/g).slice(0, 3).map(Number);
    const luminance = (color) => channels(color).map((value) => {
      const channel = value / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
    let surface = node;
    while (surface.parentElement && getComputedStyle(surface).backgroundColor === "rgba(0, 0, 0, 0)") surface = surface.parentElement;
    const foreground = luminance(getComputedStyle(node).color);
    const background = luminance(getComputedStyle(surface).backgroundColor);
    return (Math.max(foreground, background) + 0.05) / (Math.min(foreground, background) + 0.05);
  });
  assert.ok(welcomeContrast >= 4.5, `Dark workspace status contrast: ${welcomeContrast}`);
  if (process.env.AGENTLENS_EMPTY_DARK_SCREENSHOT_PATH) {
    await page.screenshot({ path: process.env.AGENTLENS_EMPTY_DARK_SCREENSHOT_PATH, fullPage: true });
  }
  await page.getByRole("button", { name: "切换到日间模式", exact: true }).click();

  statusMode = "error";
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-workspace-updated")));
  await page.locator('.welcome-context[data-workspace-state="error"]').waitFor();
  assert.match(await page.locator(".chat-workspace-toggle").getAttribute("aria-label"), /重试/);
  statusMode = "ready";
  const retryRequest = new Promise((resolve) => { statusGate = resolve; });
  await page.locator(".chat-workspace-toggle").click();
  const retryRoute = await retryRequest;
  await page.locator('.welcome-context[data-workspace-state="loading"]').waitFor();
  assert.equal(await welcomeStatus.isDisabled(), true);
  assert.equal(await welcomeStatus.innerText(), "正在连接工作区");
  await retryRoute.fulfill({ json: { code: 0, data: { enabled: true, sandboxReady: true } } });
  await page.locator('.welcome-context[data-workspace-state="ready"]').waitFor();

  // A superseded response must not overwrite a newer disabled workspace.
  const staleRequest = new Promise((resolve) => { statusGate = resolve; });
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-workspace-updated")));
  const staleRoute = await staleRequest;
  statusMode = "disabled";
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-workspace-updated")));
  await page.locator('.welcome-context[data-workspace-state="disabled"]').waitFor();
  const staleFinished = page.waitForEvent("requestfinished", (request) => request === staleRoute.request());
  await staleRoute.fulfill({ json: { code: 0, data: { enabled: true, sandboxReady: true } } });
  await staleFinished;
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await welcomeStatus.getAttribute("data-workspace-state"), "disabled");
  assert.equal(await page.locator(".chat-workspace-toggle").innerText(), "工作区关闭");
  const disabledDot = await welcomeStatus.locator(".welcome-context-dot").evaluate((node) => getComputedStyle(node).backgroundColor);
  assert.notEqual(disabledDot, "rgba(0, 0, 0, 0)");
  statusMode = "ready";
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-workspace-updated")));
  await page.locator('.welcome-context[data-workspace-state="ready"]').waitFor();
  assert.notEqual(await welcomeStatus.locator(".welcome-context-dot").evaluate((node) => getComputedStyle(node).backgroundColor), disabledDot);
  await welcomeActions.getByRole("button", { name: "检查当前改动", exact: true }).click();
  assert.equal(
    await composer.inputValue(),
    "请检查当前工作区的未提交改动，指出可能的缺陷、风险和遗漏；发现明确问题时直接修复，并运行相关验证。",
  );
  await page.waitForFunction(node => document.activeElement === node, await composer.elementHandle());
  assert.equal(await composer.evaluate((node) => node === document.activeElement), true);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-composer-reset")));
  await welcomeStatus.click();
  const workspace = page.locator("#page-workspace.active");
  await workspace.waitFor({ state: "visible" });
  const fileList = workspace.locator(".workspace-file-list");
  await fileList.locator(".workspace-loading").waitFor({ state: "visible" });
  assert.equal(await fileList.getAttribute("aria-busy"), "true");
  assert.equal(await fileList.locator(".workspace-empty").count(), 0);
  assert.equal(await fileList.locator(".workspace-loading-row").count(), 4);

  await fileList.getByText("正在读取工作区…", { exact: true }).waitFor();
  await fileList.locator(".workspace-file-open").getByText("README.md", { exact: true }).waitFor();
  assert.equal(await fileList.locator(".workspace-loading").count(), 0);
  assert.equal(await fileList.getAttribute("aria-busy"), "false");

  await workspace.getByRole("button", { name: "刷新", exact: true }).click();
  await fileList.locator(".workspace-refreshing").waitFor({ state: "visible" });
  assert.equal(await fileList.locator(".workspace-file-open").getByText("README.md", { exact: true }).count(), 1);
  assert.equal(await fileList.locator(".workspace-file-row button:disabled").count(), 3);
  await fileList.locator(".workspace-refreshing").waitFor({ state: "detached" });

  await page.emulateMedia({ reducedMotion: "reduce" });
  await workspace.getByRole("button", { name: "刷新", exact: true }).click();
  await fileList.locator(".workspace-refreshing").waitFor({ state: "visible" });
  assert.equal(await fileList.locator(".workspace-loading-dot").first().evaluate((node) => getComputedStyle(node).animationName), "none");
  await fileList.locator(".workspace-refreshing").waitFor({ state: "detached" });

  await fileList.getByRole("button", { name: /README\.md.*预览/ }).click();
  const preview = workspace.getByRole("complementary", { name: "README.md文件预览" });
  await preview.waitFor({ state: "visible" });
  await preview.getByText("Workspace preview.", { exact: false }).waitFor();
  assert.equal(previewCalls, 1);
  assert.equal(await preview.getByRole("link", { name: "下载", exact: true }).getAttribute("href"), "/api/workspace/files/README.md");
  assert.match(new URL(page.url()).pathname, /^\/?$/);
  if (process.env.AGENTLENS_SCREENSHOT_PATH) {
    await page.screenshot({ path: process.env.AGENTLENS_SCREENSHOT_PATH, fullPage: true });
  }
  await preview.getByRole("button", { name: "关闭文件预览" }).click();
  await preview.waitFor({ state: "detached" });

  await page.setViewportSize({ width: 390, height: 844 });
  await fileList.getByRole("button", { name: /README\.md.*预览/ }).click();
  await preview.waitFor({ state: "visible" });
  const previewBounds = await preview.boundingBox();
  assert.ok(previewBounds && previewBounds.x >= 0 && previewBounds.x + previewBounds.width <= 390);
  const bounds = await workspace.boundingBox();
  assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 390);
  assert.deepEqual(errors, []);
  console.log("workspace browser checks passed: welcome actions, retry/loading/disabled states, stale response guard, keyboard focus, real theme toggle/contrast, in-app preview, reduced motion, mobile composer bounds");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1200) });
  throw error;
} finally {
  await browser.close();
}
