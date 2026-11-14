/* SENTI minimal safe Markdown renderer.
 * Every character of input is HTML-escaped first; only a fixed set of tags produced by this
 * file ever reaches innerHTML. Links are limited to http(s) and open in a new window.
 */
(function () {
  "use strict";

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // Inline formatting on an already-escaped string.
  function inline(escaped) {
    const slots = [];
    const keep = (html) => "\u0000" + (slots.push(html) - 1) + "\u0000";
    let s = escaped.replace(/`([^`\n]+)`/g, (_, code) => keep("<code>" + code + "</code>"));
    s = s.replace(/\[([^\]\n]{1,300})\]\((https?:\/\/[^\s)]{1,2000})\)/g, (_, text, url) =>
      keep('<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + text + "</a>"));
    s = s.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
         .replace(/__([^_\n]+)__/g, "<strong>$1</strong>")
         .replace(/(^|[^*\w])\*([^*\n]+)\*(?!\w)/g, "$1<em>$2</em>")
         .replace(/(^|[^_\w])_([^_\n]+)_(?!\w)/g, "$1<em>$2</em>")
         .replace(/~~([^~\n]+)~~/g, "<del>$1</del>");
    return s.replace(/\u0000(\d+)\u0000/g, (_, i) => slots[Number(i)]);
  }

  function isTableSep(line) { return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(line); }
  function cells(line) {
    return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
  }

  function render(source) {
    const lines = String(source == null ? "" : source).replace(/\r\n?/g, "\n").split("\n");
    const out = [];
    let i = 0;
    let para = [];
    const flush = () => {
      if (para.length) { out.push("<p>" + para.map((l) => inline(escapeHtml(l))).join("<br>") + "</p>"); para = []; }
    };
    while (i < lines.length) {
      const line = lines[i];
      const fence = line.match(/^\s*(```|~~~)\s*([\w+-]{0,32})\s*$/);
      if (fence) {
        flush();
        const body = [];
        i++;
        while (i < lines.length && !lines[i].trim().startsWith(fence[1])) { body.push(lines[i]); i++; }
        i++;
        const lang = fence[2] ? ' data-lang="' + escapeHtml(fence[2]) + '"' : "";
        out.push("<pre" + lang + "><code>" + escapeHtml(body.join("\n")) + "</code></pre>");
        continue;
      }
      if (!line.trim()) { flush(); i++; continue; }
      const heading = line.match(/^(#{1,4})\s+(.+?)\s*#*\s*$/);
      if (heading) {
        flush();
        const level = heading[1].length;
        out.push("<h" + level + ">" + inline(escapeHtml(heading[2])) + "</h" + level + ">");
        i++; continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push("<hr>"); i++; continue; }
      if (/^\s*>/.test(line)) {
        flush();
        const quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) { quote.push(lines[i].replace(/^\s*>\s?/, "")); i++; }
        out.push("<blockquote>" + render(quote.join("\n")) + "</blockquote>");
        continue;
      }
      if (line.includes("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
        flush();
        const head = cells(line);
        i += 2;
        const rows = [];
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) { rows.push(cells(lines[i])); i++; }
        const th = head.map((c) => "<th>" + inline(escapeHtml(c)) + "</th>").join("");
        const tb = rows.map((r) => "<tr>" + r.map((c) => "<td>" + inline(escapeHtml(c)) + "</td>").join("") + "</tr>").join("");
        out.push("<table><thead><tr>" + th + "</tr></thead><tbody>" + tb + "</tbody></table>");
        continue;
      }
      const listMatch = line.match(/^\s*([-*+]|\d{1,3}[.)])\s+/);
      if (listMatch) {
        flush();
        const ordered = /\d/.test(listMatch[1]);
        const re = ordered ? /^\s*\d{1,3}[.)]\s+(.*)$/ : /^\s*[-*+]\s+(.*)$/;
        const items = [];
        while (i < lines.length) {
          const m = lines[i].match(re);
          if (m) { items.push(m[1]); i++; continue; }
          if (items.length && /^\s{2,}\S/.test(lines[i])) { items[items.length - 1] += " " + lines[i].trim(); i++; continue; }
          break;
        }
        const tag = ordered ? "ol" : "ul";
        out.push("<" + tag + ">" + items.map((t) => "<li>" + inline(escapeHtml(t)) + "</li>").join("") + "</" + tag + ">");
        continue;
      }
      para.push(line);
      i++;
    }
    flush();
    return out.join("");
  }

  window.SentiMarkdown = { render: render, escapeHtml: escapeHtml };
})();
