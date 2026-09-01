import MarkdownIt from "markdown-it";

const LANGUAGE_ALIASES = {
  bat: "bash",
  "c++": "cpp",
  cxx: "cpp",
  cjs: "javascript",
  cs: "csharp",
  docker: "dockerfile",
  html: "xml",
  js: "javascript",
  jsx: "javascript",
  md: "markdown",
  mjs: "javascript",
  pem: "plaintext",
  py: "python",
  ps1: "powershell",
  rb: "ruby",
  sh: "bash",
  shell: "bash",
  svg: "xml",
  ts: "typescript",
  tsx: "typescript",
  yml: "yaml",
  zsh: "bash",
};

const LANGUAGE_LABELS = {
  bash: "Shell",
  c: "C",
  cpp: "C++",
  css: "CSS",
  csharp: "C#",
  diff: "Diff",
  dockerfile: "Dockerfile",
  go: "Go",
  java: "Java",
  javascript: "JavaScript",
  json: "JSON",
  kotlin: "Kotlin",
  markdown: "Markdown",
  php: "PHP",
  plaintext: "纯文本",
  powershell: "PowerShell",
  python: "Python",
  ruby: "Ruby",
  rust: "Rust",
  sql: "SQL",
  typescript: "TypeScript",
  xml: "HTML/XML",
  yaml: "YAML",
};

const SAFE_LINK_PROTOCOL = /^(?:https?:|mailto:)/i;

/**
 * Keep this small helper exported for callers that need to display a literal
 * value outside the Markdown renderer.
 */
export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export function redactEmailAddresses(value) {
  return String(value ?? "").replace(
    /\b([a-z0-9._%+-])[a-z0-9._%+-]*@([a-z0-9.-]+\.[a-z]{2,})\b/gi,
    "$1***@$2",
  );
}

function isSafeLink(value) {
  return SAFE_LINK_PROTOCOL.test(String(value ?? "").trim());
}

function normalizeCodeLanguage(value) {
  const source = String(value || "")
    .trim()
    .split(/\s+/u)[0]
    .toLowerCase()
    .replace(/^language-/u, "");
  if (!source || ["text", "txt", "plain", "plaintext"].includes(source)) {
    return "plaintext";
  }
  return LANGUAGE_ALIASES[source] || source;
}

function codeLanguageLabel(language, source) {
  if (LANGUAGE_LABELS[language]) return LANGUAGE_LABELS[language];
  const raw = String(source || "").trim().split(/\s+/u)[0];
  return raw || "纯文本";
}

function renderCodeFence(tokens, index) {
  const token = tokens[index];
  const source = String(token.content || "").replace(/\n$/u, "");
  const info = String(token.info || "").trim();
  const language = normalizeCodeLanguage(info);
  const label = codeLanguageLabel(language, info);
  const languageClass = language === "plaintext" ? "" : ` language-${escapeHtml(language)}`;
  const buttonLabel = source ? "复制代码" : "复制空代码块";
  return [
    `<div class="message-code-block" data-message-code-block="true" data-code-language="${escapeHtml(label)}" data-code-language-key="${escapeHtml(language)}">`,
    '<div class="message-code-header">',
    `<span class="message-code-language">${escapeHtml(label)}</span>`,
    `<button type="button" data-message-code-copy="true" aria-label="${buttonLabel}" title="${buttonLabel}">复制</button>`,
    "</div>",
    `<pre><code class="hljs${languageClass}">${escapeHtml(source)}</code></pre>`,
    "</div>",
  ].join("");
}

const markdownRenderer = new MarkdownIt({
  // Assistant output is untrusted. Raw HTML stays escaped while CommonMark
  // structures, tables, nested lists, blockquotes, and autolinks are handled
  // by the maintained parser instead of a local partial implementation.
  html: false,
  breaks: true,
  linkify: true,
  typographer: false,
});

// markdown-it's default validator also permits protocol-relative, ftp, and
// data:image URLs. The chat surface only needs navigable web and mail links.
markdownRenderer.validateLink = isSafeLink;

const defaultLinkOpen = markdownRenderer.renderer.rules.link_open;
markdownRenderer.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index];
  token.attrSet("target", "_blank");
  token.attrSet("rel", "noreferrer");
  return defaultLinkOpen
    ? defaultLinkOpen(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options);
};

const defaultImage = markdownRenderer.renderer.rules.image;
markdownRenderer.renderer.rules.image = (tokens, index, options, env, self) => {
  const token = tokens[index];
  token.attrSet("loading", "lazy");
  token.attrSet("decoding", "async");
  token.attrSet("referrerpolicy", "no-referrer");
  return defaultImage
    ? defaultImage(tokens, index, options, env, self)
    : self.renderToken(tokens, index, options);
};

// Keep the existing chat type scale: top-level Markdown headings are mapped
// into the compact h3-h5 range used by the message stylesheet.
function compactHeadingLevel(token) {
  const sourceLevel = Number(String(token.tag || "").slice(1)) || 1;
  return Math.min(Math.max(sourceLevel, 3), 5);
}

markdownRenderer.renderer.rules.heading_open = (tokens, index) => {
  return `<h${compactHeadingLevel(tokens[index])}>`;
};
markdownRenderer.renderer.rules.heading_close = (tokens, index) => {
  return `</h${compactHeadingLevel(tokens[index])}>`;
};

// The renderer owns the table scroll wrapper so wide assistant tables remain
// usable on narrow viewports without post-processing generated HTML.
markdownRenderer.renderer.rules.table_open = () => (
  '<div class="message-table-scroll"><table>'
);
markdownRenderer.renderer.rules.table_close = () => "</table></div>";
markdownRenderer.renderer.rules.th_open = () => '<th scope="col">';
markdownRenderer.renderer.rules.fence = renderCodeFence;

export function renderInlineMarkdown(value) {
  return markdownRenderer.renderInline(String(value ?? ""));
}

export function renderMarkdown(markdown) {
  // Keep the container free of a renderer-only trailing text node. This also
  // makes streamed message text stable for selection and screen readers.
  return markdownRenderer.render(String(markdown || "")).replace(/\n+$/, "");
}
