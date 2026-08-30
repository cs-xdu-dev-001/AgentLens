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
page.on("pageerror", (error) => errors.push(error.message));

await page.route("**/api/**", async (route) => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (!path.startsWith("/api/")) return route.continue();
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 903, username: "workspace-loading-test", display_name: "工作区测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: true, isolation: "user", itemCount: 2, sandboxReady: true, protectedPatterns: [".env"], git: { repository: true, branch: "main", dirty: false } },
    "/api/memory/settings": { enabled: false },
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/workspace/files": { path: "", entries: [
      { path: "docs", kind: "directory" },
      { path: "README.md", kind: "file" },
    ] },
  };
  if (path === "/api/workspace") {
    workspaceStatusCalls += 1;
    if (workspaceStatusCalls <= 2) await new Promise((resolve) => setTimeout(resolve, 280));
  }
  if (path === "/api/workspace/files") {
    listingCalls += 1;
    await new Promise((resolve) => setTimeout(resolve, listingCalls === 1 ? 420 : 320));
  }
  return route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});

try {
  await page.goto(baseUrl);
  await page.getByRole("textbox", { name: "消息", exact: true }).waitFor({ state: "visible" });
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

  await page.setViewportSize({ width: 390, height: 844 });
  const bounds = await workspace.boundingBox();
  assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 390);
  assert.deepEqual(errors, []);
  console.log("workspace loading browser checks passed: initial skeleton, retained refresh rows, reduced motion, mobile bounds");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1200) });
  throw error;
} finally {
  await browser.close();
}
