// Exercise deep links and browser history against the local Vite app.
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  ...(process.env.AGENTLENS_CHROMIUM_PATH
    ? { executablePath: process.env.AGENTLENS_CHROMIUM_PATH }
    : {}),
});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const errors = [];
const writes = [];
page.on("pageerror", (error) => errors.push(error.message));

await page.route("**/api/**", async (route) => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (!path.startsWith("/api/")) return route.continue();
  if (request.method() !== "GET") writes.push(path);
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 947, username: "navigation-test" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/skills": [],
    "/api/sessions": [],
  };
  await route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});

const waitForPage = (pageKey) => page.locator(`#page-${pageKey}.active`).waitFor({ state: "attached" });
const waitForUrlPage = (pageKey) => page.waitForFunction(
  (expected) => new URL(window.location.href).searchParams.get("page") === expected,
  pageKey === "chat" ? null : pageKey,
);

try {
  await page.goto(baseUrl);
  await waitForPage("chat");
  assert.equal(await page.title(), "AgentLens");
  const rootHistoryLength = await page.evaluate(() => history.length);

  const skillsButton = page.locator('#sidebar-bottom-tools [data-page="skills"]');
  await skillsButton.click();
  await waitForPage("skills");
  await waitForUrlPage("skills");
  assert.equal(await page.title(), "Skills · AgentLens");
  assert.equal(await skillsButton.getAttribute("aria-current"), "page");
  const skillsHistoryLength = await page.evaluate(() => history.length);
  assert.equal(skillsHistoryLength, rootHistoryLength + 1);

  const toolsButton = page.locator('#sidebar-bottom-tools [data-page="tools"]');
  await toolsButton.click();
  await waitForPage("tools");
  await waitForUrlPage("tools");
  assert.equal(await page.title(), "工具与MCP · AgentLens");
  const toolsHistoryLength = await page.evaluate(() => history.length);
  assert.equal(toolsHistoryLength, skillsHistoryLength + 1);

  await page.goBack();
  await waitForPage("skills");
  await waitForUrlPage("skills");
  await page.goBack();
  await waitForPage("chat");
  await waitForUrlPage("chat");
  await page.goForward();
  await waitForPage("skills");
  await waitForUrlPage("skills");
  await page.goForward();
  await waitForPage("tools");
  await waitForUrlPage("tools");

  await page.goto(`${baseUrl}/?page=skills`);
  await waitForPage("skills");
  await waitForUrlPage("skills");
  assert.equal(await page.title(), "Skills · AgentLens");

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileNavigationTrigger = page.getByRole("button", { name: /打开功能菜单/ });
  await mobileNavigationTrigger.click();
  const mobileNavigation = page.locator('.mobile-navigation-content[role="menu"]');
  await mobileNavigation.waitFor({ state: "visible" });
  assert.equal(await mobileNavigation.getByRole("menuitem", { name: /命令面板/ }).count(), 1);
  assert.equal(await mobileNavigation.getByRole("menuitem", { name: "待处理审批", exact: true }).count(), 1);
  await mobileNavigation.getByRole("menuitem", { name: "工作区", exact: true }).click();
  await waitForPage("workspace");
  await waitForUrlPage("workspace");
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.match(await mobileNavigationTrigger.getAttribute("aria-label"), /当前：工作区/);
  await mobileNavigationTrigger.click();
  const activeWorkspace = page.locator('.mobile-navigation-content[role="menu"]').getByRole("menuitem", { name: "工作区", exact: true });
  assert.equal(await activeWorkspace.getAttribute("aria-current"), "page");
  const visibleBounds = await activeWorkspace.evaluate((node) => {
    const target = node.getBoundingClientRect();
    return target.left >= 0 && target.right <= window.innerWidth;
  });
  assert.equal(visibleBounds, true);
  await page.keyboard.press("Escape");
  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log("page navigation browser checks passed: deep link, title, pushState, popstate, chat root, mobile active-item alignment");
} catch (error) {
  console.error({ errors, writes, url: page.url(), body: (await page.locator("body").innerText()).slice(0, 1800) });
  throw error;
} finally {
  await browser.close();
}
