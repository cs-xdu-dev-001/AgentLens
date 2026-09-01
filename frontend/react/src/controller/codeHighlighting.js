import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";
import c from "highlight.js/lib/languages/c";
import cpp from "highlight.js/lib/languages/cpp";
import css from "highlight.js/lib/languages/css";
import csharp from "highlight.js/lib/languages/csharp";
import diff from "highlight.js/lib/languages/diff";
import dockerfile from "highlight.js/lib/languages/dockerfile";
import go from "highlight.js/lib/languages/go";
import java from "highlight.js/lib/languages/java";
import javascript from "highlight.js/lib/languages/javascript";
import json from "highlight.js/lib/languages/json";
import kotlin from "highlight.js/lib/languages/kotlin";
import markdownLanguage from "highlight.js/lib/languages/markdown";
import php from "highlight.js/lib/languages/php";
import powershell from "highlight.js/lib/languages/powershell";
import python from "highlight.js/lib/languages/python";
import ruby from "highlight.js/lib/languages/ruby";
import rust from "highlight.js/lib/languages/rust";
import sql from "highlight.js/lib/languages/sql";
import typescript from "highlight.js/lib/languages/typescript";
import xml from "highlight.js/lib/languages/xml";
import yaml from "highlight.js/lib/languages/yaml";

const HIGHLIGHT_LANGUAGES = {
  bash,
  c,
  cpp,
  css,
  csharp,
  diff,
  dockerfile,
  go,
  java,
  javascript,
  json,
  kotlin,
  markdown: markdownLanguage,
  php,
  powershell,
  python,
  ruby,
  rust,
  sql,
  typescript,
  xml,
  yaml,
};

for (const [name, language] of Object.entries(HIGHLIGHT_LANGUAGES)) {
  hljs.registerLanguage(name, language);
}

export function highlightCode(code, language) {
  const source = String(code ?? "");
  const normalizedLanguage = String(language || "").trim().toLowerCase();
  if (!normalizedLanguage || normalizedLanguage === "plaintext") return null;
  if (!hljs.getLanguage(normalizedLanguage)) return null;
  try {
    return hljs.highlight(source, {
      language: normalizedLanguage,
      ignoreIllegals: true,
    }).value;
  } catch {
    return null;
  }
}

export function highlightMessageCodeBlocks(root) {
  if (!root?.querySelectorAll) return 0;
  let highlightedCount = 0;
  for (const block of root.querySelectorAll("[data-message-code-block]")) {
    const code = block.querySelector("code");
    if (!code || code.dataset.highlighted === "true") continue;
    const highlighted = highlightCode(
      code.textContent,
      block.dataset.codeLanguageKey,
    );
    code.dataset.highlighted = "true";
    if (highlighted === null) continue;
    code.innerHTML = highlighted;
    highlightedCount += 1;
  }
  return highlightedCount;
}
