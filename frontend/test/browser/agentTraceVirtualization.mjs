// Run against local Vite with Playwright installed (or supplied via NODE_PATH).
// The fixture exercises the long-running trace surface without network writes.
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
const writes = [];

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
    "/api/auth/me": {
      authenticated: true,
      user: { id: 817, username: "trace-virtualization", display_name: "轨迹测试" },
    },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/sessions": [],
    "/api/model-configs": [
      { id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true },
    ],
    "/api/skills": [],
  };
  await route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});

const traceRows = (count) => Array.from({ length: count }, (_, index) => {
  const number = index + 1;
  return {
    stepId: `trace-${number}`,
    parentId: number > 1 && number % 4 === 0 ? `trace-${number - 1}` : "",
    kind: number % 5 === 0 ? "sandbox" : "tool",
    name: number % 5 === 0 ? "run_sandbox_command" : "read_workspace_file",
    status: number % 17 === 0 ? "failed" : number % 9 === 0 ? "running" : "success",
    durationMs: 20 + number,
    inputSummary: JSON.stringify({ path: `src/file-${number}.js`, command: `echo ${number}` }),
    outputSummary: JSON.stringify({ exit_code: 0, stdout: `trace-output-${number}` }),
  };
});

try {
  await page.goto(baseUrl);
  await page.getByRole("textbox", { name: "消息", exact: true }).waitFor({ state: "visible" });
  await page.evaluate((trace) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-trace-open", {
      detail: {
        messageId: "message-trace-virtual",
        trace,
        approvals: [],
        run: { id: "run-trace-virtual", status: "completed" },
        toolCalls: [],
        activeTab: "trace",
      },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-open", {
      detail: { focus: false },
    }));
  }, traceRows(1_000));

  const tracePanel = page.locator("#agent-trace-panel");
  const traceList = page.locator(".agent-trace-virtual-list");
  await tracePanel.waitFor({ state: "visible" });
  await page.getByText("过程 1000", { exact: true }).waitFor();
  await traceList.waitFor({ state: "visible" });
  await page.waitForFunction(() => (
    document.querySelectorAll(".agent-trace-virtual-list [data-trace-step-id]").length > 0
  ));

  const mountedRows = await traceList.locator("[data-trace-step-id]").count();
  assert.equal(await traceList.getAttribute("data-trace-count"), "1000");
  assert.ok(mountedRows < 140, `expected bounded trace DOM, mounted ${mountedRows} rows`);

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("knowflow:react-trace-focus", {
      detail: { scope: "workbench" },
    }));
  });
  await page.waitForFunction(() => document.activeElement?.getAttribute("data-trace-step-id") === "trace-986");
  await page.locator('[data-trace-step-id="trace-986"]').press("Home");
  await page.waitForFunction(() => document.activeElement?.getAttribute("data-trace-step-id") === "trace-1");
  await page.locator('[data-trace-step-id="trace-1"]').press("End");
  await page.waitForFunction(() => document.activeElement?.getAttribute("data-trace-step-id") === "trace-1000");
  assert.equal(await traceList.locator('[data-trace-step-id][tabindex="0"]').count(), 1);

  await page.evaluate((trace) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-trace-updated", {
      detail: {
        messageId: "message-trace-virtual",
        trace,
      },
    }));
  }, traceRows(1_250));
  await page.getByText("过程 1250", { exact: true }).waitFor();
  await page.waitForFunction(() => (
    document.querySelectorAll(".agent-trace-virtual-list [data-trace-step-id]").length < 140
  ));
  assert.equal(await traceList.getAttribute("data-trace-count"), "1250");
  assert.ok(await traceList.locator('[data-trace-step-id]').count() < 140);
  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log("agent trace browser checks passed: bounded DOM, offscreen focus, Home/End navigation, live updates");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 2400) });
  throw error;
} finally {
  await browser.close();
}
