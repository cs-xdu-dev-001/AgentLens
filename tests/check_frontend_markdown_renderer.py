import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    for stylesheet in (
        ROOT / "frontend" / "styles.css",
        ROOT / "frontend" / "react" / "src" / "styles.css",
    ):
        styles = stylesheet.read_text(encoding="utf-8")
        for selector in (
            ".message-table-scroll",
            ".message.assistant table",
            ".message.assistant th",
            ".message.assistant td",
        ):
            if selector not in styles:
                raise AssertionError(f"missing table style in {stylesheet}: {selector}")

    chat_messages = (
        ROOT / "frontend" / "react" / "src" / "components" / "ChatMessages.jsx"
    ).read_text(encoding="utf-8")
    if "redactEmailAddresses(rawContent)" not in chat_messages:
        raise AssertionError("assistant display must mask email addresses before rendering")
    if 'import("../controller/codeHighlighting.js")' not in chat_messages:
        raise AssertionError("syntax highlighting must stay out of the initial chat bundle")
    if 'streaming || !root?.querySelector("[data-message-code-block]")' not in chat_messages:
        raise AssertionError("streaming and plain messages must skip lazy highlighting")
    for needle, label in (
        ('data-message-code-copy', "code block copy delegation"),
        ("copyTextToClipboard", "clipboard fallback"),
        ("redactCopyText", "code copy redaction"),
    ):
        if needle not in chat_messages:
            raise AssertionError(f"missing {label} in ChatMessages.jsx")

    package = (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    if '"highlight.js": "11.12.0"' not in package:
        raise AssertionError("highlight.js must stay pinned for deterministic code rendering")

    for stylesheet in (
        ROOT / "frontend" / "refinement.css",
        ROOT / "frontend" / "react" / "src" / "refinement.css",
    ):
        styles = stylesheet.read_text(encoding="utf-8")
        for selector in (
            ".message-code-block",
            ".message-code-header",
            ".message-code-language",
            ".hljs-keyword",
        ):
            if selector not in styles:
                raise AssertionError(f"missing code block style in {stylesheet}: {selector}")

    script = r'''
import { highlightCode } from "./frontend/react/src/controller/codeHighlighting.js";
import { redactEmailAddresses, renderMarkdown } from "./frontend/react/src/controller/markdown.js";

function assertContains(html, needle, label) {
  if (!html.includes(needle)) throw new Error(`${label}: missing ${needle} in ${html}`);
}
function assertNotContains(html, needle, label) {
  if (html.includes(needle)) throw new Error(`${label}: unexpected ${needle} in ${html}`);
}

const unsafe = renderMarkdown("hello <script>alert(1)</script> [x](javascript:alert(1))");
assertContains(unsafe, "&lt;script&gt;alert(1)&lt;/script&gt;", "escapes html tags");
assertNotContains(unsafe, "href=\"javascript:", "blocks unsafe link protocols");

const inline = renderMarkdown("Use `a **b** *c* <tag>` then **bold** and *em*.");
assertContains(inline, "<code>a **b** *c* &lt;tag&gt;</code>", "keeps inline code literal");
assertContains(inline, "<strong>bold</strong>", "renders bold outside code");
assertContains(inline, "<em>em</em>", "renders emphasis outside code");
assertNotContains(inline, "<code>a <strong>", "does not parse bold inside inline code");
assertNotContains(inline, "<code>a **b** <em>", "does not parse emphasis inside inline code");

const table = renderMarkdown("| Name | Status |\n| --- | --- |\n| **Notion** | Connected |");
assertContains(table, "<table>", "renders a table");
assertContains(table, "<th scope=\"col\">Name</th>", "renders table headers");
assertContains(table, "<td><strong>Notion</strong></td>", "renders inline markdown in cells");
assertNotContains(table, "| --- | --- |", "does not show the table delimiter");

const redacted = redactEmailAddresses("User: mentor42@campus.example, owner@example.com");
assertContains(redacted, "m***@campus.example", "masks the first email");
assertContains(redacted, "o***@example.com", "masks every email");
assertNotContains(redacted, "mentor42@campus.example", "does not expose the first email");
assertNotContains(redacted, "owner@example.com", "does not expose later emails");

const fenced = renderMarkdown("```js\nconst x = '<tag>';\n");
assertContains(fenced, "class=\"message-code-block\"", "wraps reviewable fenced code");
assertContains(fenced, "data-code-language=\"JavaScript\"", "labels the fenced language");
assertContains(fenced, "data-code-language-key=\"javascript\"", "exposes a safe language key for lazy highlighting");
assertContains(fenced, "data-message-code-copy=\"true\"", "renders a code copy control");
assertContains(fenced, "class=\"hljs language-javascript\"", "uses the maintained syntax highlighter");
assertNotContains(fenced, "hljs-keyword", "keeps the initial renderer free of highlighter work");
assertContains(fenced, "'&lt;tag&gt;'", "escapes unterminated fenced code content");
assertContains(fenced, "</code></pre></div>", "closes unterminated fenced code safely");
assertNotContains(fenced, "<tag>", "does not expose fenced HTML");

const highlighted = highlightCode("const x = '<tag>';", "javascript");
assertContains(highlighted, "class=\"hljs-keyword\">const</span>", "highlights known language tokens");
assertContains(highlighted, "&lt;tag&gt;", "keeps highlighted code escaped");
if (highlightCode("plain", "unknown-language") !== null) {
  throw new Error("unknown languages must remain escaped plaintext");
}

const rich = renderMarkdown("> quoted context\n\n- parent\n  - child\n\nhttps://example.com");
assertContains(rich, "<blockquote>", "renders blockquotes");
assertContains(rich, "<ul>\n<li>parent\n<ul>", "renders nested lists");
assertContains(rich, "<a href=\"https://example.com\" target=\"_blank\" rel=\"noreferrer\">", "linkifies safe URLs");

const image = renderMarkdown("![diagram](https://example.com/diagram.png)");
assertContains(image, "loading=\"lazy\"", "lazy-loads assistant images");
assertContains(image, "referrerpolicy=\"no-referrer\"", "protects image referrers");

console.log("markdown renderer escapes untrusted content and preserves code literals");
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    print(result.stdout.strip())


if __name__ == "__main__":
    main()
