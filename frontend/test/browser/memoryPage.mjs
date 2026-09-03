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
let settingsMode = "ready";
let enabled = true;
let memories = [
  {
    id: "memory-1",
    memory: "偏好键盘操作，常用Ctrl+K打开命令面板。",
    updated_at: "2026-09-03T10:20:00+08:00",
  },
  {
    id: "memory-2",
    memory: "AgentLens项目默认使用PowerShell 7运行本地命令。",
    updated_at: "2026-09-02T18:06:00+08:00",
  },
];

page.on("pageerror", (error) => errors.push(error.message));

await page.route("**/api/**", async (route) => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (!path.startsWith("/api/")) return route.continue();
  if (path === "/api/auth/me") {
    return route.fulfill({ json: { code: 0, data: { authenticated: true, user: { id: 904, username: "memory-audit" } } } });
  }
  if (path === "/api/runtime") {
    return route.fulfill({ json: { code: 0, data: { version: "test" } } });
  }
  if (path === "/api/memory/settings") {
    if (settingsMode === "error") {
      return route.fulfill({ status: 503, json: { message: "记忆服务暂时不可用" } });
    }
    if (request.method() === "PUT") {
      enabled = Boolean(request.postDataJSON()?.enabled);
    }
    return route.fulfill({
      json: {
        code: 0,
        data: {
          configured: settingsMode !== "unconfigured",
          enabled,
          version: "2.0.14",
        },
      },
    });
  }
  if (path === "/api/memories" && request.method() === "DELETE") {
    memories = [];
    return route.fulfill({ json: { code: 0, data: { deleted: true } } });
  }
  if (path === "/api/memories") {
    return route.fulfill({ json: { code: 0, data: memories } });
  }
  if (path.startsWith("/api/memories/") && request.method() === "PUT") {
    const memoryId = path.split("/").pop();
    const content = request.postDataJSON()?.content || "";
    memories = memories.map((memory) => (
      memory.id === memoryId ? { ...memory, memory: content } : memory
    ));
    return route.fulfill({
      json: { code: 0, data: memories.find((memory) => memory.id === memoryId) },
    });
  }
  return route.fulfill({ json: { code: 0, data: [] } });
});

try {
  await page.goto(baseUrl);
  await page.getByRole("button", { name: "切换到夜间模式", exact: true }).click();
  await page.locator('body[data-theme="mono-dark"]').waitFor();
  await page.getByRole("button", { name: "切换到日间模式", exact: true }).click();
  await page.locator('body[data-theme="mono-light"]').waitFor();
  await page.goto(`${baseUrl}/?page=memory`);
  const memoryPage = page.locator("#page-memory.active");
  await memoryPage.waitFor({ state: "visible" });
  await memoryPage.getByText("2条长期记忆", { exact: true }).waitFor();
  assert.equal(await page.title(), "记忆 · AgentLens");
  assert.equal(await memoryPage.getByRole("switch").getAttribute("aria-checked"), "true");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);

  if (process.env.AGENTLENS_MEMORY_DESKTOP_SCREENSHOT_PATH) {
    await page.screenshot({ path: process.env.AGENTLENS_MEMORY_DESKTOP_SCREENSHOT_PATH, fullPage: true });
  }
  await page.goto(baseUrl);
  await page.getByRole("button", { name: "切换到夜间模式", exact: true }).click();
  await page.locator('body[data-theme="mono-dark"]').waitFor();
  await page.goto(`${baseUrl}/?page=memory`);
  await page.locator("#page-memory.active").getByText("2条长期记忆", { exact: true }).waitFor();
  if (process.env.AGENTLENS_MEMORY_DARK_SCREENSHOT_PATH) {
    await page.screenshot({ path: process.env.AGENTLENS_MEMORY_DARK_SCREENSHOT_PATH, fullPage: true });
  }
  await page.evaluate(() => {
    localStorage.setItem("knowflow-theme", "mono-light");
    document.documentElement.dataset.theme = "mono-light";
    document.body.dataset.theme = "mono-light";
  });

  const search = memoryPage.getByRole("searchbox", { name: "搜索长期记忆" });
  await search.fill("键盘");
  await memoryPage.getByText("1/2条长期记忆", { exact: true }).waitFor();
  assert.equal(await memoryPage.locator(".memory-item").count(), 1);
  await search.fill("不存在的内容");
  await memoryPage.getByText("没有匹配的记忆", { exact: true }).waitFor();
  await memoryPage.getByRole("button", { name: "清除搜索", exact: true }).click();
  assert.equal(await memoryPage.locator(".memory-item").count(), 2);

  await memoryPage.getByRole("button", { name: "编辑", exact: true }).first().click();
  const editor = memoryPage.getByRole("textbox", { name: "编辑记忆内容" });
  await editor.fill("偏好键盘操作，并希望所有核心入口都支持快捷键。");
  await memoryPage.getByRole("button", { name: "保存", exact: true }).click();
  await memoryPage.getByText("偏好键盘操作，并希望所有核心入口都支持快捷键。", { exact: true }).waitFor();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  assert.equal(await memoryPage.getByRole("searchbox", { name: "搜索长期记忆" }).isVisible(), true);
  const mobileMenuTrigger = page.getByRole("button", { name: /打开功能菜单，当前：记忆/ });
  assert.equal(await mobileMenuTrigger.isVisible(), true);
  if (process.env.AGENTLENS_MEMORY_MOBILE_SCREENSHOT_PATH) {
    await page.screenshot({ path: process.env.AGENTLENS_MEMORY_MOBILE_SCREENSHOT_PATH, fullPage: true });
  }

  await page.setViewportSize({ width: 1280, height: 800 });
  settingsMode = "unconfigured";
  await page.reload();
  await page.locator("#page-memory.active").getByText("长期记忆尚不可用", { exact: true }).waitFor();
  assert.equal(await page.locator("#page-memory .memory-toolbar").count(), 0);
  assert.equal(await page.locator("#page-memory").getByRole("switch").getAttribute("aria-checked"), "false");
  if (process.env.AGENTLENS_MEMORY_UNAVAILABLE_SCREENSHOT_PATH) {
    await page.screenshot({ path: process.env.AGENTLENS_MEMORY_UNAVAILABLE_SCREENSHOT_PATH, fullPage: true });
  }

  settingsMode = "error";
  await page.reload();
  await page.locator("#page-memory.active").getByText("无法读取长期记忆", { exact: true }).waitFor();
  assert.equal(await page.locator("#page-memory").getByRole("button", { name: "重试", exact: true }).isVisible(), true);
  assert.deepEqual(errors, []);
  console.log("memory browser checks passed: searchable list, inline edit, desktop/mobile bounds, unavailable and error recovery states");
} catch (error) {
  console.error({ errors, body: (await page.locator("body").innerText()).slice(0, 1600) });
  throw error;
} finally {
  await browser.close();
}
