// Run against the local Vite server with Playwright installed (or on NODE_PATH).
// The browser context is disposable and API calls are fixture-backed.
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
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));

await page.route("**/api/**", async (route) => {
  const requestUrl = new URL(route.request().url());
  const path = requestUrl.pathname;
  if (!path.startsWith("/api/")) return route.continue();
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 7, username: "run-test", display_name: "运行测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": {
      enabled: true,
      isolation: "user",
      itemCount: 1,
      sandboxReady: true,
      protectedPatterns: [".env"],
      git: { repository: true, branch: "main", dirty: true },
    },
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/memory/settings": { enabled: false },
    "/api/workspace/files": { path: "", entries: [{ path: "README.md", kind: "file", size: 20 }] },
    "/api/workspace/changes": { runId: "run-42", changes: [{ path: "README.md" }], patch: "@@ -1 +1 @@\n-old\n+new" },
  };
  return route.fulfill({ json: { code: 0, data: fixtures[path] ?? {} } });
});

try {
  await page.goto(baseUrl);
  await page.getByRole("textbox", { name: "消息", exact: true }).waitFor({ state: "visible" });
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-workspace-open", {
    detail: {
      messageId: "msg-42",
      run: {
        id: "run-42",
        status: "completed",
        goal: "整理README",
        artifacts: [{
          artifactType: "file",
          path: "README.md",
          operation: "edit",
          operationId: "op-1",
          diffAvailable: true,
          addedLines: 1,
          removedLines: 1,
        }],
      },
    },
  })));

  const workspace = page.locator("#page-workspace.active");
  await workspace.waitFor({ state: "visible" });
  const card = workspace.locator(".workspace-run-card");
  await card.waitFor({ state: "visible" });
  assert.equal(await card.getByText("整理README", { exact: true }).count(), 1);
  assert.equal(await card.getByText("1个产物", { exact: true }).count(), 1);

  await card.getByRole("button", { name: "详情", exact: true }).click();
  await card.getByText("@@ -1 +1 @@", { exact: false }).waitFor({ state: "visible" });
  await page.setViewportSize({ width: 390, height: 844 });
  const cardBounds = await card.boundingBox();
  assert.ok(cardBounds && cardBounds.x >= 0 && cardBounds.x + cardBounds.width <= 390);
  await page.setViewportSize({ width: 1280, height: 900 });
  await card.getByRole("button", { name: "在对话中打开", exact: true }).click();
  await page.locator("#page-chat.active").waitFor({ state: "visible" });
  await page.locator("#evidence-drawer").waitFor({ state: "visible" });
  assert.equal(await page.locator("#agent-artifacts-panel").getByText("README.md", { exact: true }).count(), 1);
  assert.deepEqual(errors, []);
  console.log("workbench run browser checks passed: event handoff, artifact diff, chat return");
} finally {
  await browser.close();
}
