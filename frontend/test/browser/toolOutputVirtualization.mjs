// Run against local Vite with Playwright installed (or supplied via NODE_PATH).
// APIs are fixture-backed and the browser context is disposable.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const measureOnly = process.env.AGENTLENS_MEASURE_ONLY === "1";
const screenshotDir = process.env.AGENTLENS_SCREENSHOT_DIR;
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
    "/api/auth/me": { authenticated: true, user: { id: 815, username: "tool-output", display_name: "工具输出测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/sessions": [],
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/skills": [],
  };
  await route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});

async function screenshot(name) {
  if (!screenshotDir) return;
  await mkdir(screenshotDir, { recursive: true });
  await page.screenshot({ path: resolve(screenshotDir, name), fullPage: false });
}

async function waitForConsoleText(text) {
  await page.waitForFunction((expected) => (
    document.querySelector(".agent-tool-console-section pre")?.textContent.includes(expected)
  ), text);
}

try {
  await page.goto(baseUrl);
  await page.getByRole("textbox", { name: "消息", exact: true }).waitFor({ state: "visible" });
  const injectionDurationMs = await page.evaluate(() => {
    const toolCalls = Array.from({ length: 1_000 }, (_, index) => {
      const number = index + 1;
      return {
        toolCallId: `call-${number}`,
        toolName: number % 2 ? "read_workspace_file" : "run_sandbox_command",
        status: number % 11 ? "completed" : "failed",
        durationMs: 20 + number,
        output: `tool-output-${number}\n第${number}条工具执行记录`,
      };
    });
    const startedAt = performance.now();
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-trace-open", {
      detail: {
        messageId: "message-tool-output",
        trace: [],
        approvals: [],
        run: { id: "run-tool-output", status: "completed" },
        toolCalls,
        activeTab: "output",
      },
    }));
    return performance.now() - startedAt;
  });
  await page.waitForTimeout(120);
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("knowflow:react-drawer-open", {
      detail: { focus: false },
    }));
  });
  await page.waitForFunction(() => (
    !document.body.classList.contains("drawer-collapsed")
    && getComputedStyle(document.querySelector("#evidence-drawer")).visibility === "visible"
  ));
  await page.waitForTimeout(250);

  const outputPanel = page.locator("#agent-output-panel");
  const toolList = page.locator("#tool-timeline-mini");
  await outputPanel.waitFor({ state: "visible" });
  await page.getByText("输出 1000", { exact: true }).waitFor();
  await page.waitForTimeout(120);
  const mountedRows = await toolList.locator('[data-workbench-item="tool"]').count();
  console.log(JSON.stringify({ injectionDurationMs: Math.round(injectionDurationMs), mountedRows }));

  if (!measureOnly) {
    assert.equal(await toolList.getAttribute("data-tool-count"), "1000");
    assert.ok(mountedRows < 120, `expected a bounded tool timeline DOM, mounted ${mountedRows} rows`);
    await waitForConsoleText("tool-output-1000");

    const activeTool = () => toolList.locator('[data-workbench-item="tool"][aria-pressed="true"]');
    await page.waitForFunction(() => (
      document.querySelectorAll('#tool-timeline-mini [data-workbench-item="tool"][aria-pressed="true"]').length === 1
    ));
    assert.equal(await activeTool().getAttribute("data-workbench-item-id"), "call-1000");
    assert.equal(await activeTool().getAttribute("tabindex"), "0");

    await activeTool().focus();
    await activeTool().press("Home");
    await page.waitForFunction(() => (
      document.activeElement?.getAttribute("data-workbench-item-id") === "call-1"
    ));
    assert.equal(await activeTool().getAttribute("data-workbench-item-id"), "call-1");
    await waitForConsoleText("tool-output-1");

    await activeTool().press("ArrowDown");
    await page.waitForFunction(() => (
      document.activeElement?.getAttribute("data-workbench-item-id") === "call-2"
    ));
    assert.equal(await activeTool().getAttribute("data-workbench-item-id"), "call-2");
    await waitForConsoleText("tool-output-2");

    await activeTool().press("End");
    await page.waitForFunction(() => (
      document.activeElement?.getAttribute("data-workbench-item-id") === "call-1000"
    ));
    assert.equal(await activeTool().getAttribute("data-workbench-item-id"), "call-1000");
    assert.equal(await toolList.locator('[data-workbench-item="tool"][tabindex="0"]').count(), 1);

    for (const [name, locator] of [
      ["panel", outputPanel],
      ["timeline", toolList],
      ["console", page.locator(".agent-tool-console")],
    ]) {
      const dimensions = await locator.evaluate((node) => ({
        clientWidth: node.clientWidth,
        scrollWidth: node.scrollWidth,
      }));
      assert.equal(
        dimensions.scrollWidth > dimensions.clientWidth + 1,
        false,
        `${name} should not overflow horizontally`,
      );
    }
    await screenshot("tool-output-desktop.png");

    await page.setViewportSize({ width: 375, height: 812 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const locator of [outputPanel, toolList, page.locator(".agent-tool-console")]) {
      const bounds = await locator.boundingBox();
      assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 375);
      assert.equal(await locator.evaluate((node) => node.scrollWidth > node.clientWidth + 1), false);
    }
    assert.ok(await toolList.locator('[data-workbench-item="tool"]').count() < 120);
    await screenshot("tool-output-mobile.png");
  }

  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log(measureOnly
    ? "tool output performance measured"
    : "tool output browser checks passed: bounded DOM, logical keyboard navigation and 375px layout");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 2400) });
  throw error;
} finally {
  await browser.close();
}
