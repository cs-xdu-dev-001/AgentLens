// Run against the local Vite server with Playwright installed (or on NODE_PATH).
// API calls are fixture-backed; the browser context is disposable.
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const { chromium } = createRequire(import.meta.url)("playwright");
const baseUrl = process.env.AGENTLENS_TEST_URL || "http://127.0.0.1:5173";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
const errors = [];
const writes = [];
page.on("pageerror", error => errors.push(error.message));
await page.route("**/api/**", route => {
  const request = route.request();
  const path = new URL(request.url()).pathname;
  if (!path.startsWith("/api/")) return route.continue();
  if (request.method() !== "GET") writes.push(request.url());
  const fixtures = {
    "/api/auth/me": { authenticated: true, user: { id: 901, username: "draft-test", display_name: "草稿测试" } },
    "/api/runtime": { version: "test" },
    "/api/workspace": { enabled: false },
    "/api/memory/settings": { enabled: false },
    "/api/model-configs": [{ id: 1, name: "测试模型", modelName: "test-model", modelType: "chat", enabled: true, isDefault: true }],
    "/api/skills": [{ id: 42, name: "检查代码", slug: "check", enabled: true, available: true }],
  };
  return route.fulfill({ json: { code: 0, data: fixtures[path] || [] } });
});
await page.addInitScript(() => {
  if (sessionStorage.getItem("seed-draft-skill") !== "1") return;
  sessionStorage.removeItem("seed-draft-skill");
  const key = "agentlens.composerDraft.v1:901:new";
  const stored = JSON.parse(localStorage.getItem(key) || "null");
  if (!stored) return;
  stored.skill = { id: 42, name: "检查代码", slug: "check" };
  localStorage.setItem(key, JSON.stringify(stored));
});

const draft = page.getByRole("textbox", { name: "消息", exact: true });
const dispatchSession = sessionId => page.evaluate((nextSessionId) => {
  window.dispatchEvent(new CustomEvent("knowflow:react-session-switch-state", {
    detail: { status: "loading", sessionId: nextSessionId },
  }));
  window.dispatchEvent(new CustomEvent("knowflow:react-active-session-updated", {
    detail: { sessionId: nextSessionId, title: nextSessionId || "新任务" },
  }));
  window.dispatchEvent(new CustomEvent("knowflow:react-session-switch-state", {
    detail: { status: "success", sessionId: nextSessionId },
  }));
}, sessionId);

try {
  await page.goto(baseUrl);
  await draft.waitFor({ state: "visible" });
  const newDraft = "  刷新后仍保留\n这份未发送草稿  ";
  await draft.fill(newDraft);
  await page.waitForFunction(expected => (
    JSON.parse(localStorage.getItem("agentlens.composerDraft.v1:901:new") || "null")?.question === expected
  ), newDraft);
  await page.evaluate(() => sessionStorage.setItem("seed-draft-skill", "1"));
  await page.reload();
  await draft.waitFor({ state: "visible" });
  assert.equal(await draft.inputValue(), newDraft);
  await page.getByRole("button", { name: "移除Skill：检查代码", exact: true }).waitFor();

  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("knowflow:react-attachments-replace", {
      detail: {
        attachments: [{ attachmentId: "memory-only", filename: "notes.md", fileType: "text", mimeType: "text/markdown", content: "notes" }],
      },
    }));
  });
  await page.getByText("notes.md", { exact: true }).waitFor();

  await dispatchSession("session-a");
  await page.waitForFunction(() => document.querySelector('textarea[name="question"]')?.value === "");
  assert.equal(await page.getByText("notes.md", { exact: true }).count(), 0);
  const sessionDraft = "session-a专属草稿";
  await draft.fill(sessionDraft);
  await page.waitForFunction(expected => (
    JSON.parse(localStorage.getItem("agentlens.composerDraft.v1:901:session:session-a") || "null")?.question === expected
  ), sessionDraft);

  await dispatchSession("");
  await page.waitForFunction(expected => document.querySelector('textarea[name="question"]')?.value === expected, newDraft);
  await page.getByText("notes.md", { exact: true }).waitFor();
  await dispatchSession("session-a");
  await page.waitForFunction(expected => document.querySelector('textarea[name="question"]')?.value === expected, sessionDraft);
  assert.equal(await page.getByText("notes.md", { exact: true }).count(), 0);

  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-composer-reset", {
    detail: { question: "", skillId: null },
  })));
  await page.waitForFunction(() => !localStorage.getItem("agentlens.composerDraft.v1:901:session:session-a"));
  assert.equal(await draft.inputValue(), "");
  await dispatchSession("");
  const firstSubmitDraft = "首次发送后不能重新出现";
  await draft.fill(firstSubmitDraft);
  await page.waitForFunction(expected => (
    JSON.parse(localStorage.getItem("agentlens.composerDraft.v1:901:new") || "null")?.question === expected
  ), firstSubmitDraft);
  await page.evaluate(() => {
    window.dispatchEvent(new CustomEvent("knowflow:react-composer-reset", {
      detail: { question: "", skillId: null },
    }));
    window.dispatchEvent(new CustomEvent("knowflow:react-active-session-updated", {
      detail: { sessionId: "session-fast", title: "首次任务" },
    }));
  });
  await page.waitForFunction(() => document.querySelector('textarea[name="question"]')?.value === "");
  assert.equal(await page.evaluate(() => localStorage.getItem("agentlens.composerDraft.v1:901:new")), null);
  const firstOwnerDraft = "只属于用户901";
  await draft.fill(firstOwnerDraft);
  await page.waitForFunction(expected => (
    JSON.parse(localStorage.getItem("agentlens.composerDraft.v1:901:session:session-fast") || "null")?.question === expected
  ), firstOwnerDraft);
  await page.evaluate(() => window.dispatchEvent(new CustomEvent("knowflow:react-auth-state-updated", {
    detail: { authenticated: true, user: { id: 902, username: "other-user", display_name: "另一用户" } },
  })));
  await page.waitForFunction(() => document.querySelector('textarea[name="question"]')?.value === "");
  await draft.fill("只属于用户902");
  await page.waitForFunction(() => (
    JSON.parse(localStorage.getItem("agentlens.composerDraft.v1:902:new") || "null")?.question === "只属于用户902"
  ));
  assert.equal(await page.evaluate(() => (
    JSON.parse(localStorage.getItem("agentlens.composerDraft.v1:901:session:session-fast") || "null")?.question
  )), firstOwnerDraft);
  assert.deepEqual(writes, []);
  assert.deepEqual(errors, []);
  console.log("composer draft browser checks passed: reload, Skill, session/user isolation, first-session migration, transient attachments, clear-after-submit");
} catch (error) {
  console.error({ errors, page: (await page.locator("body").innerText()).slice(0, 1200) });
  throw error;
} finally {
  await browser.close();
}
