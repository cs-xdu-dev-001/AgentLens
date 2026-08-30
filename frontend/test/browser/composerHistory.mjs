// Run against the local Vite server with Playwright installed (or on NODE_PATH).
// API calls are fixture-backed; the browser context is disposable.
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined;
const browser = await chromium.launch({ headless: true, executablePath });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
const writes = [];
page.on("pageerror", error => errors.push(error.message));
await page.route("**/api/**", route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (!path.startsWith("/api/")) return route.continue();
  if (request.method() !== "GET") writes.push(path);
  if (path === "/api/chat/stream") {
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: "",
    });
  }
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 901, username: "history-test", display_name: "历史测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/skills": [],
  };
  return route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});
await page.addInitScript(() => {
  localStorage.setItem("agentlens.composerHistory.v1:901", JSON.stringify({
    version: 1,
    entries: ["检查依赖版本", "重构登录流程并补测试", "解释当前工作区结构"],
  }));
  localStorage.setItem("agentlens.composerHistory.v1:902", JSON.stringify({
    version: 1,
    entries: ["只属于用户902的输入"],
  }));
});

const draft = page.getByRole("textbox", { name: "消息", exact: true });
const historySearch = page.getByRole("combobox", { name: "筛选输入历史", exact: true });

try {
  await page.goto(baseUrl);
  await draft.waitFor({ state: "visible" });

  const originalDraft = "保留这份未提交草稿";
  await draft.fill(originalDraft);
  await draft.evaluate((node) => node.setSelectionRange(2, 6));
  await draft.press("Control+r");
  await historySearch.waitFor({ state: "visible" });
  assert.equal(await historySearch.evaluate(node => document.activeElement === node), true);
  await historySearch.fill("登录流程");
  await page.getByRole("option", { name: "重构登录流程并补测试", exact: true }).waitFor();
  await historySearch.press("Escape");
  await page.waitForFunction(() => document.activeElement === document.querySelector('textarea[name="question"]'));
  assert.equal(await draft.inputValue(), originalDraft);
  assert.deepEqual(await draft.evaluate(node => ({
    focused: document.activeElement === node,
    start: node.selectionStart,
    end: node.selectionEnd,
  })), { focused: true, start: 2, end: 6 });

  await draft.press("Control+r");
  await historySearch.fill("登录流程");
  await historySearch.press("Enter");
  await page.waitForFunction(() => document.activeElement === document.querySelector('textarea[name="question"]'));
  assert.equal(await draft.inputValue(), "重构登录流程并补测试");
  assert.equal(await draft.evaluate(node => document.activeElement === node), true);
  assert.equal(await page.getByTestId("composer-history-search").count(), 0);

  await draft.press("Control+r");
  const firstActive = await historySearch.getAttribute("aria-activedescendant");
  await historySearch.press("Control+r");
  const secondActive = await historySearch.getAttribute("aria-activedescendant");
  assert.notEqual(secondActive, firstActive);
  await historySearch.press("Escape");

  await draft.fill("刚提交的真实输入");
  await draft.press("Enter");
  await page.waitForFunction(() => (
    JSON.parse(localStorage.getItem("agentlens.composerHistory.v1:901") || "null")?.entries?.at(-1)
      === "刚提交的真实输入"
  ));
  assert.deepEqual(writes, ["/api/chat/stream"]);

  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-auth-state-updated", {
    detail: { authenticated: true, user: { id: 902, username: "other-user", display_name: "另一用户" } },
  })));
  await page.waitForFunction(() => document.querySelector('textarea[name="question"]')?.value === "");
  await draft.press("Control+r");
  await page.getByRole("option", { name: "只属于用户902的输入", exact: true }).waitFor();
  assert.equal(await page.getByTestId("composer-history-search").getByText("刚提交的真实输入", { exact: true }).count(), 0);

  await page.setViewportSize({ width: 390, height: 844 });
  const bounds = await page.getByTestId("composer-history-search").boundingBox();
  assert.ok(bounds);
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390);
  assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= 844);
  await page.getByRole("button", { name: "清空输入历史", exact: true }).click();
  assert.notEqual(await page.evaluate(() => localStorage.getItem("agentlens.composerHistory.v1:902")), null);
  await page.getByRole("button", { name: "确认清空输入历史", exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('[data-testid="composer-history-search"]'));
  assert.equal(await page.evaluate(() => localStorage.getItem("agentlens.composerHistory.v1:902")), null);
  await page.waitForFunction(() => document.activeElement === document.querySelector('textarea[name="question"]'));
  await draft.press("Control+r");
  assert.equal(await page.getByTestId("composer-history-search").count(), 0);
  await page.getByText("还没有可搜索的输入历史", { exact: true }).waitFor();

  await draft.evaluate((node) => node.dispatchEvent(new KeyboardEvent("keydown", {
    key: "r",
    ctrlKey: true,
    isComposing: true,
    bubbles: true,
  })));
  assert.equal(await page.getByTestId("composer-history-search").count(), 0);
  assert.deepEqual(errors, []);
  console.log("composer history browser checks passed: search, cycle, fill, draft restore, persistence, user isolation, clear, empty state, mobile bounds, IME guard");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1600) });
  throw error;
} finally {
  await browser.close();
}
