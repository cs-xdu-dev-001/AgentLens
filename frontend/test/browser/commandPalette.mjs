// Run against the local Vite server with Playwright installed (or on NODE_PATH).
// All API calls are fixture-backed: this never changes a real user's data.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const { chromium } = createRequire(import.meta.url)("playwright");
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const artifacts = resolve(process.env.AGENTLENS_TEST_ARTIFACTS || "tmp/command-palette");
await mkdir(artifacts, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
const writes = [];
page.on("pageerror", error => errors.push(error.message));
await page.route("**/api/**", async route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (!path.startsWith("/api/")) {
    await route.continue();
    return;
  }
  if (request.method() !== "GET") writes.push(request.url());
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 999, username: "palette-test", display_name: "交互测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/sessions": [
      {
        id: "session-42",
        title: "部署AgentLens",
        updated_at: "2026-08-31 20:00:00",
        latest_run: { goalSummary: "检查发布状态", status: "completed" },
        chat_model_config_id: 1,
      },
    ],
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
  };
  await route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});
const palette = page.locator("#command-palette");
const search = page.getByRole("combobox", { name: "搜索命令", exact: true });
const draft = page.getByRole("textbox", { name: "消息", exact: true });
const focused = locator => locator.evaluate(node => node === document.activeElement);
const open = async () => {
  await page.keyboard.press("Control+k");
  await palette.waitFor({ state: "visible" });
  assert.equal(await focused(search), true);
};
const run = async query => {
  await open();
  await search.fill(query);
  await search.press("Enter");
  await palette.waitFor({ state: "detached" });
};

try {
  await page.goto(baseUrl);
  await draft.waitFor({ state: "visible" });
  await draft.fill("保留这份草稿，不要发送");
  await draft.evaluate(node => node.setSelectionRange(2, 5));
  await open();
  await page.screenshot({ path: resolve(artifacts, "desktop-light.png") });
  assert.equal(await page.locator("#palette-command-stop").count(), 0);
  await search.press("ArrowDown");
  assert.equal(await search.getAttribute("aria-activedescendant"), "palette-command-new");
  await search.press("Tab");
  assert.equal(await focused(page.getByRole("button", { name: "关闭命令面板", exact: true })), true);
  await page.keyboard.press("Shift+Tab");
  assert.equal(await focused(search), true);
  await search.fill("zzzz-not-a-command");
  await search.press("Enter");
  assert.equal(await palette.isVisible(), true);
  assert.match(await page.locator(".command-palette-footer").innerText(), /没有匹配命令/);
  await search.press("Escape");
  assert.equal(await focused(draft), true);
  assert.equal(await draft.inputValue(), "保留这份草稿，不要发送");
  assert.deepEqual(await draft.evaluate(node => [node.selectionStart, node.selectionEnd]), [2, 5]);
  await open();
  await search.press("Escape");
  await open();
  await page.waitForFunction(() => document.activeElement?.getAttribute("aria-label") === "搜索命令");
  assert.equal(await focused(search), true, "a stale close frame must not steal focus from a reopened palette");
  await search.press("Escape");
  await page.keyboard.press("Meta+k");
  await palette.waitFor({ state: "visible" });
  await search.press("Escape");
  await page.keyboard.press("Control+Shift+k");
  assert.equal(await palette.count(), 0);

  // The same commands work when the chat page is hidden.
  await run("/settings");
  await page.locator("#page-settings.active").waitFor();
  await page.waitForFunction(() => document.activeElement?.id === "main-stage");
  assert.equal(await draft.isVisible(), false);
  await open();
  await search.fill("/model");
  await search.press("Enter");
  await page.locator(".composer-model-picker.open").waitFor();
  assert.equal(await draft.isVisible(), true);
  assert.equal(await draft.inputValue(), "保留这份草稿，不要发送");
  await page.keyboard.press("Escape");

  // An unrelated modal owns shortcuts; IME confirmation is never execution.
  await page.evaluate(() => {
    const dialog = document.createElement("dialog");
    dialog.id = "other-modal";
    dialog.innerHTML = '<button type="button">Other modal</button>';
    document.body.append(dialog);
    dialog.showModal();
  });
  await page.keyboard.press("Control+k");
  assert.equal(await palette.count(), 0);
  await page.evaluate(() => document.getElementById("other-modal").remove());
  await open();
  await search.fill("/new");
  await search.dispatchEvent("keydown", { key: "Enter", isComposing: true, bubbles: true });
  assert.equal(await palette.isVisible(), true);
  assert.equal(await draft.inputValue(), "保留这份草稿，不要发送");
  await page.keyboard.press("Control+k");
  await palette.waitFor({ state: "detached" });

  // Runtime state updates gate the palette exactly like the slash picker.
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-sending-updated", { detail: { sending: true } })));
  await open();
  await search.fill("stop");
  await page.locator("#palette-command-stop").waitFor({ state: "visible" });
  assert.equal(await page.locator("#palette-command-stop").count(), 1);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-sending-updated", { detail: { sending: false } })));
  await page.locator("#palette-command-stop").waitFor({ state: "detached" });
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-session-switch-state", { detail: { status: "loading" } })));
  await page.waitForFunction(() => document.querySelectorAll(".command-palette-option").length === 0);
  assert.match(await page.locator(".command-palette-footer").innerText(), /正在打开任务/);
  await search.press("Escape");
  const disabledShortcut = await page.evaluate(() => {
    const event = new KeyboardEvent("keydown", {
      bubbles: true,
      cancelable: true,
      ctrlKey: true,
      key: "k",
    });
    document.dispatchEvent(event);
    return {
      defaultPrevented: event.defaultPrevented,
      paletteMounted: Boolean(document.getElementById("command-palette")),
    };
  });
  assert.deepEqual(disabledShortcut, { defaultPrevented: false, paletteMounted: false });
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-session-switch-state", { detail: { status: "success" } })));

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => { document.documentElement.dataset.theme = "mono-dark"; });
  await page.getByRole("button", { name: "打开命令面板", exact: true }).click();
  await palette.waitFor({ state: "visible" });
  await page.screenshot({ path: resolve(artifacts, "mobile-dark.png") });
  const bounds = await palette.boundingBox();
  assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= 390);
  const optionBounds = await page.locator(".command-palette-option").first().boundingBox();
  assert.ok(optionBounds.height >= 44);
  await page.emulateMedia({ reducedMotion: "reduce" });
  assert.equal(await palette.evaluate(node => getComputedStyle(node).animationName), "none");
  await search.fill("resume");
  await search.press("Enter");
  await page.locator("#session-history[aria-modal=true]").waitFor({ state: "visible" });
  await page.waitForFunction(() => document.activeElement?.id === "sidebar-session-search");
  await page.keyboard.press("Escape");
  // Session rows from the existing sidebar index are searchable from the same palette.
  await page.evaluate(() => {
    window.__paletteSessionSelection = "";
    window.__paletteSessionSwitchEvents = [];
    window.addEventListener("knowflow:react-session-continue", event => {
      window.__paletteSessionSelection = String(event.detail?.sessionId || "");
    }, { once: true });
    window.addEventListener("knowflow:react-session-switch-state", event => {
      window.__paletteSessionSwitchEvents.push({ ...event.detail });
    });
  });
  await open();
  await search.fill("部署AgentLens");
  await page.locator("#palette-session-session-42").waitFor({ state: "visible" });
  await search.press("Enter");
  await palette.waitFor({ state: "detached" });
  assert.equal(await page.evaluate(() => window.__paletteSessionSelection), "session-42");
  await page.waitForFunction(
    () => window.__paletteSessionSwitchEvents?.some(
      event => event.status === "success" && event.sessionId === "session-42",
    ),
  );
  assert.equal(await page.locator("#page-chat .session-switch-state").count(), 0);
  await page.locator("#page-chat.active").waitFor();
  await open();
  await page.setViewportSize({ width: 390, height: 400 });
  await page.waitForFunction(() => window.innerHeight === 400 && document.getElementById("command-palette").getBoundingClientRect().bottom <= 400);
  const shortBounds = await palette.boundingBox();
  assert.ok(shortBounds.y + shortBounds.height <= 400, JSON.stringify(shortBounds));
  await search.press("Escape");
  const streamResult = await page.evaluate(async () => {
    const append = { role: "assistant", rawContent: "", streaming: true, thinking: false };
    window.dispatchEvent(new CustomEvent("knowflow:react-message-append", { detail: append }));
    const messageId = append.messageId;
    const bubble = () => document.querySelector(`[data-react-message-id="${messageId}"] .message-markdown`);
    let mutations = 0;
    const target = bubble();
    const observer = new MutationObserver(() => { mutations += 1; });
    observer.observe(target, { childList: true, subtree: true, characterData: true });
    for (let index = 1; index <= 100; index += 1) {
      window.dispatchEvent(new CustomEvent("knowflow:react-message-content", {
        detail: { messageId, rawContent: `token-${index}`, streaming: true },
      }));
    }
    const immediate = bubble()?.textContent || "";
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    observer.disconnect();
    if (immediate !== "") throw new Error(`stream content painted before the frame: ${immediate}`);
    return { immediate, final: bubble()?.textContent || "", mutations };
  });
  assert.equal(streamResult.final, "token-100");
  assert.ok(streamResult.mutations <= 4, JSON.stringify(streamResult));
  await open();
  await page.mouse.click(4, 395);
  await palette.waitFor({ state: "detached" });
  assert.deepEqual(writes, [], "navigation and palette input must not create API writes");
  assert.deepEqual(errors, []);
  console.log("command palette browser checks passed: keyboard, focus, drafts, routing, modal/IME guards, runtime gates, mobile, reduced motion");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1200) });
  throw error;
} finally {
  await browser.close();
}
