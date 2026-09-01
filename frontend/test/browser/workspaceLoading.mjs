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
  if (process.env.AGENTLENS_EMPTY_DESKTOP_SCREENSHOT_PATH) {
    await page.screenshot({ path: process.env.AGENTLENS_EMPTY_DESKTOP_SCREENSHOT_PATH, fullPage: true });
  }
  if (process.env.AGENTLENS_EMPTY_MOBILE_SCREENSHOT_PATH) {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: process.env.AGENTLENS_EMPTY_MOBILE_SCREENSHOT_PATH, fullPage: true });
    await page.setViewportSize({ width: 1280, height: 800 });
  }
  await welcomeActions.getByRole("button", { name: "检查当前改动", exact: true }).click();
  assert.equal(
    await composer.inputValue(),
    "请检查当前工作区的未提交改动，指出可能的缺陷、风险和遗漏；发现明确问题时直接修复，并运行相关验证。",
  );
  assert.equal(await composer.evaluate((node) => node === document.activeElement), true);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-composer-reset")));
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-page-change", {
    detail: { page: "workspace" },
  })));
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
  console.log("workspace browser checks passed: loading states, in-app preview, reduced motion, mobile bounds");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1200) });
  throw error;
} finally {
  await browser.close();
}
