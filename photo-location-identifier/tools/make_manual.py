"""Make the manual's HTML (opened with F1) and plain text from docs/MANUAL.md, with the standard library only.

    python tools/make_manual.py           write docs/manual.html and docs/manual.txt
    python tools/make_manual.py --check   exit 1 if they are out of date (the build checks this)

The Markdown used is small: "#" headings with {#anchor}, paragraphs, "-" and "1." lists (nested by indenting),
**bold**, *italic*, `code`, and indented code blocks. Each heading's anchor is what F1 opens in each window.
"""

import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(os.path.dirname(HERE), "docs")
SOURCE = os.path.join(DOCS, "MANUAL.md")

STYLE = """body{font-family:Segoe UI,Arial,sans-serif;max-width:46em;margin:1em auto;padding:0 1em;line-height:1.5;
color:#111;background:#fff}code,pre{font-family:Consolas,monospace;background:#f2f2f2}pre{padding:.5em;overflow:auto}
h1,h2{color:#003366}@media (prefers-color-scheme:dark){body{background:#111;color:#eee}code,pre{background:#222}
h1,h2{color:#9cf}}"""


def inline(text):
    """Bold, italic and code in a line of text (HTML)."""
    out, parts = [], re.split(r"(`[^`]+`)", text)
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
        else:
            t = html.escape(part, quote=False)
            t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
            t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)
            t = t.replace("\\\\", "\\")
            out.append(t)
    return "".join(out)


def blocks(lines):
    """[(kind, data)] of the Markdown: ("h", (level, text, anchor)), ("p", text), ("list", items), ("pre", text).
    A list item is (ordered, indent, text)."""
    out, para, items, pre = [], [], [], []

    def flush():
        """Close the paragraph and the list being collected (each becomes a block)."""
        if para:
            out.append(("p", " ".join(para)))
            para.clear()
        if items:
            out.append(("list", list(items)))
            items.clear()
        if pre:
            out.append(("pre", "\n".join(pre)))
            pre.clear()
    lines = [raw.rstrip("\n") for raw in lines]
    for i, line in enumerate(lines):
        m = re.match(r"^(#{1,6})\s+(.*?)(?:\s*\{#([\w-]+)\})?\s*$", line)
        item = re.match(r"^(\s*)(-|\d+\.)\s+(.*)$", line)
        if m:
            flush()
            out.append(("h", (len(m.group(1)), m.group(2), m.group(3) or "")))
        elif not line.strip():
            if pre:
                pre.append("")
                continue
            following = next((x for x in lines[i + 1:] if x.strip()), "")
            if items and (following.startswith(" ") or re.match(r"^(-|\d+\.)\s", following)):
                ordered, indent, text = items[-1]
                if following.startswith("  ") and not re.match(r"^\s*(-|\d+\.)\s", following):
                    items[-1] = (ordered, indent, text + "\n\n")
                continue                    # the list goes on
            flush()
        elif line.startswith("    ") and not items and not para:
            pre.append(line[4:])
        elif item:
            if para or pre:
                flush()
            items.append((item.group(2) != "-", len(item.group(1)), item.group(3)))
        elif items and line.startswith(" "):
            ordered, indent, text = items[-1]
            sep = "" if text.endswith("\n\n") else " "
            items[-1] = (ordered, indent, text + sep + line.strip())
        else:
            if pre or items:
                flush()
            para.append(line.strip())
    flush()
    while out and out[-1][0] == "pre" and not out[-1][1].strip():
        out.pop()
    return out


def list_html(items):
    """Nested <ul>/<ol> for list items."""
    out, stack = [], []
    for ordered, indent, text in items:
        tag = "ol" if ordered else "ul"
        while stack and stack[-1][0] > indent:
            out.append(f"</li></{stack.pop()[1]}>")
        if not stack or stack[-1][0] < indent:
            out.append(f"<{tag}><li>")
            stack.append((indent, tag))
        else:
            out.append("</li><li>")
        out.append(inline(text).replace("\n\n", "<br><br>"))
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return "".join(out)


def to_html(md):
    """The whole HTML page."""
    body, title = [], "Manual"
    for kind, data in blocks(md.splitlines()):
        if kind == "h":
            level, text, anchor = data
            if level == 1:
                title = text
            body.append(f'<h{level}{f" id={chr(34)}{anchor}{chr(34)}" if anchor else ""}>{inline(text)}</h{level}>')
        elif kind == "p":
            body.append(f"<p>{inline(data)}</p>")
        elif kind == "list":
            body.append(list_html(data))
        elif kind == "pre":
            body.append(f"<pre><code>{html.escape(data)}</code></pre>")
    return (f'<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>{html.escape(title)}</title>\n'
            f"<style>{STYLE}</style>\n</head>\n<body>\n<main>\n" + "\n".join(body) + "\n</main>\n</body>\n</html>\n")


def to_text(md):
    """The plain-text manual: no Markdown marks, headings underlined."""
    out = []
    for kind, data in blocks(md.splitlines()):
        if kind == "h":
            level, text, _ = data
            out += ["", text, ("=" if level == 1 else "-") * len(text), ""]
        elif kind == "p":
            out += [plain(data), ""]
        elif kind == "list":
            n = 0
            for ordered, indent, text in data:
                n = n + 1 if ordered else 0
                lead = " " * indent + (f"{n}. " if ordered else "- ")
                out.append(lead + plain(text).replace("\n\n", "\n\n" + " " * len(lead)))
            out.append("")
        elif kind == "pre":
            out += ["    " + line for line in data.splitlines()] + [""]
    return "\n".join(out).strip() + "\n"


def plain(text):
    """Text without Markdown marks."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)
    return text.replace("`", "").replace("\\\\", "\\")


def outputs():
    """{path: text} of the generated files."""
    with open(SOURCE, encoding="utf-8") as f:
        md = f.read()
    return {os.path.join(DOCS, "manual.html"): to_html(md), os.path.join(DOCS, "manual.txt"): to_text(md)}


def main(argv=None):
    """Write the files, or with --check say whether they are up to date."""
    argv = sys.argv[1:] if argv is None else argv
    stale = []
    for path, text in outputs().items():
        try:
            with open(path, encoding="utf-8") as f:
                same = f.read() == text
        except OSError:
            same = False
        if not same:
            stale.append(path)
            if "--check" not in argv:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(text)
    if "--check" in argv and stale:
        print("Out of date (run python tools/make_manual.py): " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
