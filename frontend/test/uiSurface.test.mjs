import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const sourceRoot = new URL("../react/src/", import.meta.url);
const cssRoot = new URL("../", import.meta.url);

async function readSource(path) {
  return readFile(new URL(path, sourceRoot), "utf8");
}

async function readCss(path) {
  return readFile(new URL(path, cssRoot), "utf8");
}

test("empty chat surface exposes task-first onboarding affordances", async () => {
  const source = await readSource("components/ChatMessages.jsx");
  assert.match(source, /function WelcomeSurface/);
  assert.match(source, /data-welcome-surface/);
  assert.match(source, /welcome-action-icon/);
  assert.match(source, /welcome-shortcuts/);
  assert.match(source, /from "lucide-react"/);
  assert.doesNotMatch(source, /welcome-kicker/);
});

test("virtualized transcript tolerates a transient missing item", async () => {
  const source = await readSource("components/ChatMessages.jsx");
  assert.match(source, /if \(!message \|\| typeof message !== "object"\) return null;/);
  assert.match(source, /return message\?\.id \|\| `message-placeholder-\$\{_index\}`;/);
});

test("knowledge empty state keeps the rail secondary to the workspace action", async () => {
  const [rail, documents] = await Promise.all([
    readSource("components/KnowledgeRail.jsx"),
    readSource("components/KnowledgeDocuments.jsx"),
  ]);
  const emptyStart = rail.indexOf('className={keyword ? "kb-empty is-search-empty" : "kb-empty is-unconfigured"}');
  const emptyEnd = rail.indexOf("</div>", emptyStart);
  assert.ok(emptyStart >= 0 && emptyEnd > emptyStart);
  const railEmpty = rail.slice(emptyStart, emptyEnd);
  assert.match(railEmpty, /role=\{"status"\}/);
  assert.doesNotMatch(railEmpty, /<button/);
  assert.match(documents, /"document-empty unconfigured"/);
  assert.match(documents, /onClick=\{selectedKnowledgeBaseId \? handleOpenUploadModal : onCreateKnowledgeBase\}/);
});

test("AgentLens branding keeps a compatibility logo export", async () => {
  const source = await readSource("components/KnowFlowLogo.jsx");
  assert.match(source, /export function AgentLensLogo/);
  assert.match(source, /export const KnowFlowLogo = AgentLensLogo/);
  assert.match(source, /agentlens-logo/);
});

test("distributed Lucide license matches the installed icon package", async () => {
  const [upstream, distributed] = await Promise.all([
    readFile(new URL("node_modules/lucide-react/LICENSE", cssRoot), "utf8"),
    readFile(new URL("react/public/licenses/lucide-react.txt", cssRoot), "utf8"),
  ]);
  assert.equal(distributed.replace(/\r\n/g, "\n"), upstream.replace(/\r\n/g, "\n"));
});

test("distributed Radix and Floating UI licenses match their installed packages", async () => {
  for (const [dependency, license] of [
    ["@radix-ui/react-tooltip", "radix-ui"],
    ["@radix-ui/react-dropdown-menu", "radix-ui"],
    ["@floating-ui/react-dom", "floating-ui"],
  ]) {
    const [upstream, distributed] = await Promise.all([
      readFile(new URL(`node_modules/${dependency}/LICENSE`, cssRoot), "utf8"),
      readFile(new URL(`react/public/licenses/${license}.txt`, cssRoot), "utf8"),
    ]);
    assert.equal(distributed.replace(/\r\n/g, "\n"), upstream.replace(/\r\n/g, "\n"));
  }
});

test("chat chrome shares workspace state and ignores superseded responses", async () => {
  const source = await readSource("components/ChatTopbar.jsx");
  assert.match(source, /"新任务"/);
  assert.match(source, /onWorkspaceStateChange/);
  assert.match(source, /request === latestRequest/);
  const page = await readSource("components/ChatPage.jsx");
  assert.match(page, /workspaceState=\{workspaceState\}/);
});

test("chat page owns its empty-state class across navigation", async () => {
  const [page, messages] = await Promise.all([
    readSource("components/ChatPage.jsx"),
    readSource("components/ChatMessages.jsx"),
  ]);
  assert.match(page, /empty \? "chat-empty"/);
  assert.match(page, /onEmptyStateChange=\{setEmpty\}/);
  assert.match(messages, /onEmptyStateChange\?\.\(showWelcome\)/);
  assert.doesNotMatch(messages, /classList\.(toggle|remove)\("chat-empty"/);
});

test("interrupted runs resume once after connectivity or foreground recovery", async () => {
  const source = await readSource("components/ChatComposerForm.jsx");
  assert.match(source, /window\.addEventListener\("online", requestResume\)/);
  assert.match(source, /document\.addEventListener\("visibilitychange", handleVisibilityChange\)/);
  assert.match(source, /autoResumeKeyRef\.current === recoveryKey/);
  assert.match(source, /action: "resume"/);
});

test("responsive workbench respects short mobile viewports and reduced motion", async () => {
  const css = await readCss("refinement.css");
  assert.match(css, /min-height:\s*min\(360px,\s*calc\(100dvh\s*-\s*48px\)\)/);
  assert.match(css, /@media\s*\(prefers-reduced-motion:\s*reduce\)/);
  assert.match(css, /welcome-action-arrow/);
});

test("thinking orb follows the mono theme instead of pinning light ink", async () => {
  const source = await readSource("components/AgentThinkingOrb.jsx");
  const css = await readCss("styles.css");
  assert.match(source, /resolveOrbTheme/);
  assert.match(source, /MutationObserver/);
  assert.match(source, /theme=\{orbTheme\}/);
  assert.doesNotMatch(source, /theme=\{"light"\}/);
  assert.match(css, /\.agent-thinking-orb[\s\S]*color:\s*var\(--text-soft/);
});

test("mobile run details expose a dismissible backdrop without changing desktop structure", async () => {
  const [page, css] = await Promise.all([
    readSource("components/ChatPage.jsx"),
    readCss("refinement.css"),
  ]);
  assert.match(page, /chat-mobile-drawer-backdrop/);
  assert.match(page, /关闭运行详情/);
  assert.match(css, /\.chat-mobile-drawer-backdrop[\s\S]*z-index:\s*39/);
  assert.match(css, /@media\s*\(max-width:\s*760px\)[\s\S]*chat-mobile-drawer-backdrop/);
});

test("tablet run details stay below the chat rail and expose a backdrop", async () => {
  const css = await readCss("refinement.css");
  assert.match(css, /@media\s*\(min-width:\s*761px\)\s*and\s*\(max-width:\s*1180px\)[\s\S]*chat-mobile-drawer-backdrop/);
  assert.match(css, /@media\s*\(min-width:\s*761px\)\s*and\s*\(max-width:\s*1180px\)[\s\S]*top:\s*68px\s*!important/);
  assert.match(css, /@media\s*\(min-width:\s*761px\)\s*and\s*\(max-width:\s*1180px\)[\s\S]*background:\s*color-mix/);
});

test("mobile navigation uses the maintained Radix menu and exposes current semantics", async () => {
  const source = await readSource("components/Sidebar.jsx");
  assert.match(source, /@radix-ui\/react-dropdown-menu/);
  assert.match(source, /function MobileNavigationMenu/);
  assert.match(source, /mobile-navigation-trigger/);
  assert.match(source, /aria-label=\{`打开功能菜单，当前：\$\{currentLabel\}`\}/);
  assert.match(source, /aria-current={activePage === tool\.page \? "page" : undefined}/);
});

test("page entry motion stays opacity-only and honors reduced motion", async () => {
  const css = await readCss("refinement.css");
  assert.match(css, /\.main-stage > \.page\.active:not\(\.deferred-page-loading\)/);
  assert.match(css, /@keyframes agentlens-page-enter[\s\S]*opacity:\s*0\.72[\s\S]*opacity:\s*1/);
  assert.doesNotMatch(css, /agentlens-page-enter[\s\S]*transform:/);
  assert.match(css, /prefers-reduced-motion:\s*reduce[\s\S]*agentlens-page-enter/);
});

test("web navigation preserves deep links and browser history", async () => {
  const [source, bridge] = await Promise.all([
    readSource("App.jsx"),
    readSource("controller/bridgeBindings.js"),
  ]);
  assert.match(source, /syncPageLocation/);
  assert.match(source, /mode === "push" \? "pushState" : "replaceState"/);
  assert.match(source, /window\.history\[method\]/);
  assert.match(source, /addEventListener\("popstate"/);
  assert.match(source, /document\.title = pageTitles/);
  assert.match(bridge, /source: "page-change-bridge"/);
  assert.match(source, /mirroredPageChange/);
});
