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

export function renderInlineMarkdown(value) {
  const tokens = [];
  const stash = (html) => {
    const token = `\u0000${tokens.length}\u0000`;
    tokens.push(html);
    return token;
  };

  let html = escapeHtml(value);
  html = html.replace(/`([^`]+)`/g, (_match, code) => stash(`<code>${code}</code>`));
  html = html.replace(/\[([^\]]+)]\((https?:\/\/[^\s)]+|mailto:[^\s)]+)\)/g, (_match, label, href) => stash(`<a href="${href}" target="_blank" rel="noreferrer">${label}</a>`));
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  return html.replace(/\u0000(\d+)\u0000/g, (_match, index) => tokens[Number(index)] || "");
}

function splitTableRow(value) {
  const line = String(value ?? "").trim();
  if (!line.includes("|")) return null;

  const source = line.replace(/^\|/, "").replace(/\|$/, "");
  const cells = [];
  let cell = "";
  let inCode = false;

  for (let index = 0; index < source.length; index += 1) {
    const char = source[index];
    if (char === "\\" && source[index + 1] === "|") {
      cell += "|";
      index += 1;
      continue;
    }
    if (char === "`") {
      inCode = !inCode;
      cell += char;
      continue;
    }
    if (char === "|" && !inCode) {
      cells.push(cell.trim());
      cell = "";
      continue;
    }
    cell += char;
  }
  cells.push(cell.trim());
  return cells.length > 1 ? cells : null;
}

function isTableDelimiter(cells) {
  return Array.isArray(cells)
    && cells.length > 1
    && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

export function renderMarkdown(markdown) {
  const lines = String(markdown || "").replace(/\r\n/g, "\n").split("\n");
  const html = [];
  let listType = null;
  let paragraph = [];
  let inCode = false;
  let codeLines = [];
  let codeLang = "";

  const flushParagraph = () => {
    if (!paragraph.length) return;
    html.push(`<p>${paragraph.map(renderInlineMarkdown).join("<br>")}</p>`);
    paragraph = [];
  };
  const closeList = () => {
    if (!listType) return;
    html.push(`</${listType}>`);
    listType = null;
  };
  const openList = (type) => {
    if (listType === type) return;
    closeList();
    html.push(`<${type}>`);
    listType = type;
  };

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.replace(/\s+$/g, "");
    const codeFence = line.match(/^```([\w-]*)\s*$/);
    if (codeFence) {
      if (inCode) {
        html.push(`<pre><code${codeLang ? ` class="language-${escapeHtml(codeLang)}"` : ""}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        inCode = false;
        codeLines = [];
        codeLang = "";
      } else {
        flushParagraph();
        closeList();
        inCode = true;
        codeLang = codeFence[1] || "";
      }
      continue;
    }
    if (inCode) {
      codeLines.push(rawLine);
      continue;
    }
    if (!line.trim()) {
      flushParagraph();
      closeList();
      continue;
    }

    const tableHeaders = splitTableRow(line);
    const tableDelimiter = splitTableRow(lines[index + 1]);
    if (
      tableHeaders
      && isTableDelimiter(tableDelimiter)
      && tableHeaders.length === tableDelimiter.length
    ) {
      flushParagraph();
      closeList();
      const rows = [];
      index += 2;
      while (index < lines.length) {
        const cells = splitTableRow(lines[index]);
        if (!cells) break;
        rows.push(tableHeaders.map((_header, cellIndex) => cells[cellIndex] || ""));
        index += 1;
      }
      index -= 1;
      html.push(
        '<div class="message-table-scroll"><table><thead><tr>',
        ...tableHeaders.map((cell) => `<th scope="col">${renderInlineMarkdown(cell)}</th>`),
        "</tr></thead>",
        rows.length
          ? `<tbody>${rows.map((cells) => `<tr>${cells.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join("")}</tr>`).join("")}</tbody>`
          : "",
        "</table></div>",
      );
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      closeList();
      const level = Math.min(Math.max(heading[1].length, 3), 5);
      html.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      openList("ul");
      html.push(`<li>${renderInlineMarkdown(bullet[1])}</li>`);
      continue;
    }

    const numbered = line.match(/^\s*\d+\.\s+(.+)$/);
    if (numbered) {
      flushParagraph();
      openList("ol");
      html.push(`<li>${renderInlineMarkdown(numbered[1])}</li>`);
      continue;
    }

    paragraph.push(line);
  }

  if (inCode) {
    html.push(`<pre><code${codeLang ? ` class="language-${escapeHtml(codeLang)}"` : ""}>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
  }
  flushParagraph();
  closeList();
  return html.join("");
}
