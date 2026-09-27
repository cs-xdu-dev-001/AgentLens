// Disposable API fixtures exercise the real pickers without changing user data.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";
const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({ headless: true, ...(process.env.AGENTLENS_CHROMIUM_PATH ? { executablePath: process.env.AGENTLENS_CHROMIUM_PATH } : {}) });
const page = await browser.newPage();
const errors = [], writes = [];
const output = process.env.AGENTLENS_POPOVER_SCREENSHOT_DIR;
page.on("pageerror", error => errors.push(error.message));
await page.route("**/api/**", route => {
  if (!["fetch", "xhr"].includes(route.request().resourceType())) return route.continue();
  const path = new URL(route.request().url()).pathname;
  if (route.request().method() !== "GET") writes.push(path);
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 719, username: "popover-test" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/model-configs": Array.from({ length: 18 }, (_, index) => ({ id: index + 1, name: `模型${index + 1}`, provider: "very-long-provider-name-for-layout-check", modelName: `chat-${index + 1}`, modelType: "chat", enabled: true, isDefault: !index })),
  };
  return route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});
const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const inViewport = async selector => {
  // Radix measures a newly mounted surface off-screen before positioning its
  // wrapper. DOM visibility/two frames alone do not guarantee that has finished.
  await page.waitForFunction(target => {
    const wrapper = document.querySelector(target)?.closest("[data-radix-popper-content-wrapper]");
    return wrapper && !wrapper.style.transform.includes("-200%");
  }, selector);
  await settle();
  const bounds = await page.locator(selector).boundingBox();
  const viewport = page.viewportSize();
  assert.ok(bounds && bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= viewport.width + 1 && bounds.y + bounds.height <= viewport.height + 1,
    `${selector} must fit: ${JSON.stringify({ viewport, bounds })}`);
};
const shot = async name => { if (output) await page.screenshot({ path: resolve(output, `${name}.png`) }); };
try {
  if (output) await mkdir(output, { recursive: true });
  await page.goto(process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173");
  const draft = page.getByRole("textbox", { name: "消息", exact: true });
  await draft.waitFor();
  await draft.fill("保留这份草稿，不要在编辑工具规则时发送");
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-context-status-updated", {
    detail: { status: { maxTokens: 128000, usedTokens: 48000, remainingTokens: 80000, usagePercent: 37.5 } },
  })));
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const viewport of [{width:1440,height:960}, {width:1280,height:800}, {width:390,height:844}, {width:375,height:812}, {width:375,height:460}, {width:1024,height:500}]) {
    await page.setViewportSize(viewport);
    await settle();
    for (const theme of ["light", "dark"]) {
      if (theme === "dark") await page.getByRole("button", { name: "切换到夜间模式", exact: true }).click();
      await page.locator(".composer-model-trigger:not(.composer-permission-trigger)").click();
      await page.getByRole("combobox", { name: "搜索聊天模型" }).waitFor();
      await settle();
      await inViewport(".composer-model-popover");
      await shot(`${viewport.width}-${viewport.height}-${theme}-models`);
      await page.getByRole("button", { name: "管理模型", exact: true }).scrollIntoViewIfNeeded();
      assert.ok(await page.getByRole("button", { name: "管理模型", exact: true }).evaluate(node => {
        const r = node.getBoundingClientRect();
        return node.contains(document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2));
      }));
      await page.keyboard.press("Escape");
      assert.equal(await page.locator(".composer-model-trigger:not(.composer-permission-trigger)").evaluate(node => node === document.activeElement), true);
      await page.locator(".composer-permission-trigger").click();
      await page.getByRole("listbox", { name: "选择权限模式" }).waitFor();
      await settle();
      await inViewport(".composer-permission-popover");
      await page.getByRole("option", { name: /工具规则/ }).click();
      await settle();
      await inViewport(".composer-permission-popover");
      await shot(`${viewport.width}-${viewport.height}-${theme}-rules`);
      await page.keyboard.press("Escape");
      await page.getByRole("listbox", { name: "选择权限模式" }).waitFor();
      await page.keyboard.press("Escape");
      if (theme === "dark") await page.getByRole("button", { name: "切换到日间模式", exact: true }).click();
    }
  }
  await page.setViewportSize({ width: 375, height: 460 });
  await page.keyboard.press("Alt+p");
  const search = page.getByRole("combobox", { name: "搜索聊天模型" });
  await search.waitFor();
  await search.fill("模型18");
  await settle();
  assert.equal(await search.getAttribute("aria-activedescendant"), "composer-model-option-0",
    "search must activate its best result, not the previously selected fuzzy match");
  assert.match(await page.locator("#composer-model-option-0").innerText(), /^模型18/);
  await page.keyboard.press("Enter");
  await page.getByRole("button", { name: "切换模型，当前为模型18", exact: true }).waitFor();
  assert.equal(await draft.evaluate(node => node === document.activeElement), true);
  await page.keyboard.press("Alt+p");
  await search.waitFor();
  await search.fill("zzzz-no-such-model-xxxx");
  await page.getByRole("status").filter({ hasText: "没有匹配" }).waitFor();
  assert.equal(await search.getAttribute("aria-activedescendant"), null);
  await search.fill("");
  await settle();
  assert.equal(await page.locator("#composer-model-option-0").getAttribute("aria-selected"), "true");
  await page.keyboard.press("Escape");
  await page.keyboard.press("Alt+r");
  await page.getByRole("radio", { name: "自动", exact: true }).waitFor();
  await page.keyboard.press("End");
  assert.equal(await page.getByRole("radio", { name: "最高", exact: true }).getAttribute("aria-checked"), "true");
  await page.keyboard.press("Escape");
  await page.locator(".composer-permission-trigger").click();
  await page.getByRole("option", { name: /工具规则/ }).click();
  const rule = page.getByRole("textbox", { name: "添加allow工具规则" });
  await rule.fill("workspace.read_file");
  await rule.press("Enter");
  await page.getByRole("button", { name: "删除workspace.read_file规则" }).waitFor();
  assert.equal(await draft.inputValue(), "保留这份草稿，不要在编辑工具规则时发送");
  assert.deepEqual(writes, [], "rule editing must not submit the enclosing chat form");
  // Short screens can place the floating surface over the draft. Click the
  // exposed viewport corner, then separately verify dismissal on outside focus.
  await page.mouse.click(4, 4);
  await page.locator(".composer-permission-popover").waitFor({ state: "detached" });
  await page.locator(".composer-permission-trigger").click();
  await page.getByRole("listbox", { name: "选择权限模式" }).waitFor();
  await draft.focus();
  await page.locator(".composer-permission-popover").waitFor({ state: "detached" });
  await page.keyboard.press("Alt+p");
  await search.waitFor();
  await inViewport("#composer-model-popover");
  await page.mouse.click(4, 4);
  await page.locator("#composer-model-popover").waitFor({ state: "detached" });
  assert.deepEqual(errors, []);
  console.log("composer popover checks passed: 6 viewports, both themes, model search/reasoning, permission rules, Escape/outside focus, no accidental submission");
} finally { await browser.close(); }
