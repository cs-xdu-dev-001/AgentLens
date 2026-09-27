// Run against Vite with Playwright installed (or on NODE_PATH).
// Only this disposable browser context uses API fixtures.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

const { chromium } = createRequire(import.meta.url)("playwright");
const browser = await chromium.launch({
  headless: true,
  ...(process.env.AGENTLENS_CHROMIUM_PATH
    ? { executablePath: process.env.AGENTLENS_CHROMIUM_PATH }
    : {}),
});
const page = await browser.newPage();
const errors = [];
page.on("pageerror", error => errors.push(error.message));
await page.route("**/api/**", route => {
  if (!["fetch", "xhr"].includes(route.request().resourceType())) return route.continue();
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 718, username: "layout-test" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: true, sandboxReady: true, git: { repository: true, branch: "main" } },
    "/api/memory/settings": { enabled: false },
    "/api/model-configs": [{ id: 1, name: "对话模型", modelName: "chat-model", modelType: "chat", enabled: true, isDefault: true }],
  };
  return route.fulfill({ json: { code: 0, data: fixtures[new URL(route.request().url()).pathname] || [] } });
});

const output = process.env.AGENTLENS_LAYOUT_SCREENSHOT_DIR;
const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
const shot = async label => {
  if (output) await page.screenshot({ path: resolve(output, `${label}.png`) });
};
const geometry = () => page.evaluate(() => {
  const rect = selector => {
    const { x, y, width, height, bottom } = document.querySelector(selector).getBoundingClientRect();
    return { x, y, width, height, bottom };
  };
  return {
    width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth,
    panel: rect(".chat-panel"), topbar: rect(".chat-topbar"), welcome: rect(".welcome-card"),
    messages: rect("#chat-messages"), form: rect("#chat-form"), send: rect("#chat-submit-btn"),
    launcherScrolls: document.querySelector("#chat-messages").scrollHeight > document.querySelector("#chat-messages").clientHeight,
  };
});
const checkViewport = layout => {
  const evidence = JSON.stringify(layout);
  assert.ok(layout.scrollWidth <= layout.width, evidence);
  assert.ok(layout.form.x >= 0 && layout.form.x + layout.form.width <= layout.width, evidence);
  assert.ok(layout.form.bottom <= layout.height && layout.send.bottom <= layout.height, evidence);
  assert.ok(Math.abs(layout.topbar.y - layout.panel.y) < 1, "task header stays pinned: " + evidence);
};

try {
  if (output) await mkdir(output, { recursive: true });
  await page.goto(process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173");
  const input = page.getByRole("textbox", { name: "消息", exact: true });
  await input.waitFor();
  await page.locator('.welcome-context[data-workspace-state="ready"]').waitFor();
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const viewport of [
    { width: 1440, height: 960 }, { width: 1280, height: 800 },
    { width: 390, height: 844 }, { width: 375, height: 812 },
    { width: 375, height: 460 }, { width: 320, height: 568 },
  ]) {
    await page.setViewportSize(viewport);
    await settle();
    for (const theme of ["light", "dark"]) {
      if (theme === "dark") await page.getByRole("button", { name: "切换到夜间模式", exact: true }).click();
      await settle();
      const layout = await geometry();
      checkViewport(layout);
      if (viewport.width <= 760) {
        assert.ok(layout.welcome.bottom <= layout.messages.bottom, JSON.stringify(layout));
        assert.ok(layout.messages.bottom <= layout.form.y + 1, "launcher viewport must end above composer: " + JSON.stringify(layout));
        const gap = layout.form.y - layout.welcome.bottom;
        if (!layout.launcherScrolls) {
          assert.ok(gap >= 16 && gap <= 32, `task launcher and composer stay together: ${gap}; ${JSON.stringify(layout)}`);
        }
        assert.ok(layout.welcome.y >= layout.messages.y, JSON.stringify(layout));
        assert.ok(viewport.height - layout.form.bottom <= 16, "composer stays at the bottom");
      }
      await shot(`${viewport.width}-${viewport.height}-${theme}`);
      if (theme === "dark") await page.getByRole("button", { name: "切换到日间模式", exact: true }).click();
    }
  }

  // A growing draft plus a long filename must reflow the launcher instead of
  // covering it. In a short viewport, every action remains scroll-reachable.
  await page.setViewportSize({ width: 375, height: 460 });
  await input.fill(Array.from({ length: 12 }, (_, index) => `第${index + 1}行：检查长草稿和附件布局`).join("\n"));
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-attachments-replace", {
    detail: { attachments: [{ attachmentId: "layout-test", filename: "AgentLens-一个非常长的工作区文件名称-用于布局回归测试.md", fileType: "text", mimeType: "text/markdown", content: "notes" }] },
  })));
  await page.locator(".attachment-pill").waitFor();
  await settle();
  const expanded = await geometry();
  checkViewport(expanded);
  assert.ok(expanded.form.height > 200, JSON.stringify(expanded));
  assert.ok(expanded.messages.height > 0 && expanded.messages.bottom <= expanded.form.y + 1, JSON.stringify(expanded));
  for (const action of await page.locator(".welcome-action").all()) {
    await action.focus();
    await action.scrollIntoViewIfNeeded();
    assert.ok(await action.evaluate(node => {
      const bounds = node.getBoundingClientRect();
      return node.contains(document.elementFromPoint(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2));
    }), "each launcher action remains reachable above the expanded composer");
  }
  await shot("short-viewport-expanded-composer");

  await input.fill("");
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-attachments-replace", { detail: { attachments: [] } })));
  await page.getByRole("button", { name: "继续最近的工作", exact: true }).click();
  assert.match(await input.inputValue(), /最近的Git提交/);
  assert.equal(await input.evaluate(node => node === document.activeElement), true);

  // Returning from a transcript uses the same React-owned empty layout.
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-message-append", {
    detail: { role: "user", rawContent: "开始检查" },
  })));
  await page.locator("#page-chat:not(.chat-empty)").waitFor();
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-messages-reset", {
    detail: { showWelcome: true },
  })));
  await page.locator("#page-chat.chat-empty").waitFor();
  await settle();
  checkViewport(await geometry());
  assert.deepEqual(errors, []);
  console.log("chat empty layout checks passed: 6 viewports, both themes, long draft/filename, scroll reachability, task seeding, transcript reset");
} finally {
  await browser.close();
}
