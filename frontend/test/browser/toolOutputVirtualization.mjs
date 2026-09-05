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

async function assertCompactConsole() {
  const dimensions = await page.locator(".agent-tool-console").evaluate((node) => {
    const scroll = node.querySelector(".agent-tool-console-scroll");
    const footer = node.querySelector(".agent-tool-console-footer");
    return {
      height: node.getBoundingClientRect().height,
      footerHeight: footer.getBoundingClientRect().height,
      outputFontSize: parseFloat(getComputedStyle(scroll.querySelector("pre")).fontSize),
      labelFontSize: parseFloat(getComputedStyle(scroll.querySelector("span")).fontSize),
    };
  });
  assert.ok(dimensions.height < 230, `two-line output should stay compact: ${JSON.stringify(dimensions)}`);
  assert.ok(dimensions.footerHeight < 48, `metadata must not occupy a flexible content row: ${JSON.stringify(dimensions)}`);
  assert.ok(dimensions.outputFontSize >= 14, JSON.stringify(dimensions));
  assert.ok(dimensions.labelFontSize >= 12, JSON.stringify(dimensions));
  const closeIcon = await page.locator("#inspector-close svg").boundingBox();
  assert.ok(closeIcon && closeIcon.width <= 20 && closeIcon.height <= 20, JSON.stringify(closeIcon));
}

async function updateToolOutput(call) {
  await page.evaluate((toolCall) => {
    window.dispatchEvent(new CustomEvent("knowflow:react-tool-timeline-updated", {
      detail: { messageId: "message-tool-output", toolCalls: toolCall ? [toolCall] : [] },
    }));
  }, call);
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
    await assertCompactConsole();
    await screenshot("tool-output-desktop.png");

    await page.setViewportSize({ width: 375, height: 812 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const locator of [outputPanel, toolList, page.locator(".agent-tool-console")]) {
      const bounds = await locator.boundingBox();
      assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 375);
      assert.equal(await locator.evaluate((node) => node.scrollWidth > node.clientWidth + 1), false);
    }
    assert.ok(await toolList.locator('[data-workbench-item="tool"]').count() < 120);
    await assertCompactConsole();
    await screenshot("tool-output-mobile.png");

    for (const [width, height, theme] of [
      [1440, 960, "mono-light"],
      [1280, 800, "mono-dark"],
      [390, 844, "mono-dark"],
      [375, 812, "mono-light"],
    ]) {
      await page.setViewportSize({ width, height });
      await page.evaluate((value) => { document.documentElement.dataset.theme = value; }, theme);
      // Panel layout reacts to the breakpoint on the next render.
      await page.waitForFunction(() => {
        const console = document.querySelector(".agent-tool-console");
        return console && console.getBoundingClientRect().height < 230;
      }, undefined, { timeout: 2_000 });
      await assertCompactConsole();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await screenshot(`tool-output-${width}-${theme}.png`);
    }

    const longTool = {
      toolCallId: "call-1000",
      toolName: "读取用于检查国际化布局的超长工具名称".repeat(4),
      status: "running",
      arguments: { command: `node scripts/check-workspace.mjs --path=${"workspace/".repeat(14)}`, token: "SECRET_FIXTURE_VALUE" },
      stdout: Array.from({ length: 400 }, (_, index) => `line-${index + 1}: 正在检查工作区文件与测试结果`).join("\n"),
    };
    await updateToolOutput(longTool);
    await waitForConsoleText("line-400:");
    const scroll = page.locator(".agent-tool-console-scroll");
    await page.waitForFunction(() => {
      const node = document.querySelector(".agent-tool-console-scroll");
      return node.scrollHeight > node.clientHeight + 100
        && node.scrollHeight - node.scrollTop - node.clientHeight < 24;
    });
    assert.equal(await page.locator(".agent-tool-console").evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
    assert.equal(await page.locator(".agent-tool-console-footer").evaluate((node) => node.getBoundingClientRect().height < 48), true);
    await scroll.focus();
    await scroll.press("Control+Home");
    const followButton = page.locator(".agent-tool-console-actions").getByRole("button", { name: "跟随", exact: true });
    await page.waitForFunction(() => (
      document.querySelector(".agent-tool-console-actions button")?.getAttribute("aria-pressed") === "false"
    ));
    await page.waitForFunction(() => document.querySelector(".agent-tool-console-scroll").scrollTop < 1);
    const readPosition = await scroll.evaluate((node) => node.scrollTop);
    longTool.stdout += "\nline-401: 新增输出，不打断上文阅读";
    await updateToolOutput(longTool);
    await waitForConsoleText("line-401:");
    assert.ok(Math.abs(await scroll.evaluate((node) => node.scrollTop) - readPosition) < 2);
    await followButton.click();
    await page.waitForFunction(() => {
      const node = document.querySelector(".agent-tool-console-scroll");
      return node.scrollHeight - node.scrollTop - node.clientHeight < 24;
    });
    await screenshot("tool-output-mobile-long.png");

    await page.context().grantPermissions(["clipboard-read", "clipboard-write"], { origin: baseUrl });
    await page.locator(".agent-tool-console-actions").getByRole("button", { name: "复制", exact: true }).click();
    await page.getByRole("button", { name: "已复制", exact: true }).waitFor();
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    assert.match(copied, /line-401:/);
    assert.match(copied, /\$ node scripts\/check-workspace.mjs/);
    assert.doesNotMatch(copied, /SECRET_FIXTURE_VALUE/);

    await updateToolOutput({ toolCallId: "waiting", toolName: "run_sandbox_command", status: "running" });
    await page.getByText("等待输出", { exact: true }).waitFor();
    assert.equal(await page.locator(".agent-tool-console-actions").getByRole("button", { name: "复制", exact: true }).isDisabled(), true);
    await screenshot("tool-output-mobile-waiting.png");
    await updateToolOutput({ toolCallId: "waiting", toolName: "run_sandbox_command", status: "completed", exitCode: 0 });
    await page.getByText("没有可显示的输出", { exact: true }).waitFor();
    await page.getByText("退出码 0", { exact: true }).waitFor();
    assert.equal(await page.locator(".agent-tool-console-actions button").last().isDisabled(), true);

    await updateToolOutput({
      toolCallId: "failed",
      toolName: "run_sandbox_command",
      status: "failed",
      stderr: "无法读取工作区文件，请检查路径是否存在。",
      errorMessage: "工作区路径不可用",
      exitCode: 1,
    });
    await page.getByText("工作区路径不可用", { exact: true }).waitFor();
    await page.getByText("退出码 1", { exact: true }).waitFor();
    assert.equal(await page.locator(".agent-tool-console-actions").getByRole("button", { name: "复制", exact: true }).isEnabled(), true);
    await screenshot("tool-output-mobile-error.png");

    await page.evaluate(() => {
      navigator.clipboard.writeText = () => new Promise((resolve) => { window.finishToolCopy = resolve; });
    });
    await page.locator(".agent-tool-console-actions").getByRole("button", { name: "复制", exact: true }).click();
    await page.waitForFunction(() => typeof window.finishToolCopy === "function");
    await updateToolOutput({ toolCallId: "next", toolName: "read_workspace_file", status: "completed", output: "切换后的工具结果" });
    await waitForConsoleText("切换后的工具结果");
    await page.evaluate(() => window.finishToolCopy());
    assert.equal(await page.locator(".agent-tool-console-actions").getByRole("button", { name: "复制", exact: true }).count(), 1);
    await updateToolOutput(null);
    await page.getByText("还没有工具输出", { exact: true }).waitFor();
  }

  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log(measureOnly
    ? "tool output performance measured"
    : "tool output browser checks passed: bounded DOM, keyboard navigation, compact adaptive layout, themes, long-output follow, copy, waiting and error states");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 2400) });
  throw error;
} finally {
  await browser.close();
}
