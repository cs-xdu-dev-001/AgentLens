// Run against Vite with Playwright installed (or supplied via NODE_PATH).
// Every API route is fixture-backed inside a disposable browser context.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || undefined,
});
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const screenshotDir = process.env.AGENTLENS_SCREENSHOT_DIR;
const errors = [];
const writes = [];
const cursors = [];
let resumeAttempt = 0;
let releaseResume;
let run = {
  id: "run-browser-recovery",
  sessionId: "session-browser-recovery",
  assistantMessageId: 12,
  goalSummary: "检查工作区并完成回归测试",
  status: "interrupted",
  steps: [],
  trace: [{ stepId: "workspace", title: "读取工作区结构", kind: "tool", status: "success" }],
  lastSequence: 3,
  failure: { code: "service_restart_interrupted", retryable: true },
  recoveryActions: [],
};
let answer = "已读取工作区结构，等待继续完成验证。";
const session = { id: run.sessionId, title: run.goalSummary, chat_model_config_id: 1, message_count: 2 };
page.on("pageerror", error => errors.push(error.message));
await page.route("**/api/**", async route => {
  const request = route.request();
  const url = new URL(request.url());
  const path = url.pathname;
  if (!path.startsWith("/api/")) return route.continue();
  if (request.method() !== "GET") writes.push(path);
  if (path.endsWith("/resume")) {
    resumeAttempt += 1;
    if (resumeAttempt === 1) {
      await new Promise(resolve => { releaseResume = resolve; });
      return route.fulfill({ status: 503, json: { detail: "Executor temporarily unavailable." } });
    }
    run = { ...run, status: "running", failure: null };
    return route.fulfill({ json: { code: 0, data: run } });
  }
  if (path.endsWith("/restart")) {
    run = { ...run, id: "run-browser-restarted", status: "running", failure: null, lastSequence: 0 };
    return route.fulfill({ json: { code: 0, data: { run, replacesRunId: "run-browser-recovery" } } });
  }
  if (path.endsWith("/events")) {
    const after = Number(url.searchParams.get("afterSequence") || 0);
    cursors.push({ runId: path.split("/").at(-2), after });
    answer = "已恢复任务并完成回归验证。";
    const events = [
      { type: "error", sequence: 3, runId: run.id, code: "service_restart_interrupted", message: "旧尝试中断" },
      { type: "run_started", sequence: 4, runId: run.id, run: { ...run, status: "running" } },
      { type: "answer", sequence: 5, runId: run.id, content: answer, final: true },
      { type: "done", sequence: 6, runId: run.id, run: { ...run, status: "completed" } },
    ].filter(event => event.sequence > after && (run.id !== "run-browser-restarted" || event.type !== "error"));
    run = { ...run, status: "completed", failure: null, lastSequence: 6, recoveryActions: [] };
    return route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join(""),
    });
  }
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 903, username: "recovery-test", display_name: "恢复测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/skills": [],
    "/api/sessions": [session],
    [`/api/sessions/${session.id}/messages`]: [
      { id: 11, role: "user", content: run.goalSummary },
      { id: 12, role: "assistant", content: answer, run, trace: run.trace },
    ],
    [`/api/agent/runs/${run.id}`]: run,
  };
  return route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});
await page.addInitScript(() => {
  localStorage.setItem("agentlens.activeSessionId.v1:903", "session-browser-recovery");
  window.recoveryTestActions = [];
  window.addEventListener("knowflow:react-agent-run-action", event => window.recoveryTestActions.push(event.detail));
});

const panel = page.locator(".agent-recovery-panel:not(.compact)");
const continueButton = () => panel.getByRole("button", { name: "从失败步骤继续", exact: true });

async function screenshot(name) {
  if (!screenshotDir) return;
  await mkdir(screenshotDir, { recursive: true });
  await page.mouse.move(0, 0);
  await page.screenshot({ path: resolve(screenshotDir, name), fullPage: false });
}

try {
  await page.goto(baseUrl);
  await panel.getByText("任务被服务重启中断", { exact: true }).waitFor();
  await continueButton().waitFor({ state: "visible" });
  assert.deepEqual(writes, []);
  await page.reload();
  await continueButton().waitFor({ state: "visible" });
  await screenshot("recovery-desktop.png");

  await continueButton().click();
  await panel.getByRole("button", { name: "正在从失败位置继续…", exact: true }).waitFor();
  assert.equal(await panel.getAttribute("aria-busy"), "true");
  assert.equal(await panel.getByRole("button", { name: "重新运行本轮", exact: true }).isDisabled(), true);
  await page.evaluate(() => {
    const previous = window.recoveryTestActions[0];
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-run-action", { detail: previous }));
    window.dispatchEvent(new CustomEvent("knowflow:react-agent-run-action", { detail: { ...previous, action: "restart" } }));
  });
  await page.waitForFunction(() => window.recoveryTestActions.length === 3);
  assert.deepEqual(writes, ["/api/agent/runs/run-browser-recovery/resume"]);
  assert.equal(typeof releaseResume, "function");
  releaseResume();
  await panel.getByRole("alert").waitFor();
  assert.equal(await continueButton().isEnabled(), true);
  assert.ok((await page.locator("body").innerText()).includes(answer));

  await page.setViewportSize({ width: 375, height: 812 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const bounds = await panel.boundingBox();
  assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 375);
  for (const button of await panel.locator("button").all()) {
    const box = await button.boundingBox();
    assert.ok(box && box.x >= 0 && box.x + box.width <= 375);
  }
  await screenshot("recovery-mobile.png");
  await continueButton().click();
  await page.getByText("已恢复任务并完成回归验证。", { exact: true }).first().waitFor();
  assert.deepEqual(cursors, [{ runId: "run-browser-recovery", after: 3 }]);
  assert.equal(await page.locator(".agent-recovery-panel").count(), 0);
  await page.reload();
  await page.getByText("已恢复任务并完成回归验证。", { exact: true }).first().waitFor();
  assert.equal(await page.locator(".agent-recovery-panel").count(), 0);
  assert.deepEqual(writes, [
    "/api/agent/runs/run-browser-recovery/resume",
    "/api/agent/runs/run-browser-recovery/resume",
  ]);

  run = { ...run, status: "cancelled", failure: { code: "agent_run_cancelled", retryable: true } };
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.reload();
  await page.locator(".agent-turn-run-block").first().waitFor();
  const stoppedPanel = panel;
  await stoppedPanel.getByText("任务已停止", { exact: true }).waitFor();
  assert.equal(await page.getByRole("button", { name: "从失败步骤继续", exact: true }).count(), 0);
  await stoppedPanel.getByRole("button", { name: "重新运行本轮", exact: true }).click();
  await page.getByText("已恢复任务并完成回归验证。", { exact: true }).first().waitFor();
  await page.waitForFunction(() => !document.querySelector(".agent-recovery-panel"));
  assert.equal(writes.at(-1), "/api/agent/runs/run-browser-recovery/restart");
  assert.deepEqual(cursors.at(-1), { runId: "run-browser-restarted", after: 0 });
  assert.deepEqual(errors, []);
  console.log("Agent recovery browser checks passed: refresh, no-plan checkpoint, pending copy, duplicate guard, failure retry, cursor replay, completion reload, restart identity, 375px bounds, reduced motion");
} catch (error) {
  console.error({ errors, writes, cursors, page: (await page.locator("body").innerText()).slice(0, 4000) });
  throw error;
} finally {
  releaseResume?.();
  await browser.close();
}
