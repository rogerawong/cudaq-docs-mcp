"""Clean CUDA-Q's published markdown mirrors for agent consumption.

The .md files linked from CUDA-Q's llms.txt are pandoc conversions of the
fully rendered HTML pages. They carry the whole Read the Docs theme as
pandoc fenced divs: nav sidebar, breadcrumbs, footer, and copyright. Code
blocks appear as 4-space-indented text inside `highlight` divs, and every
heading carries a permalink whose fragment is the section's real anchor.

This module slices out the article body, rebuilds fenced code blocks with
their language, records heading anchors, and strips pandoc attribute
syntax from prose while leaving code untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin

_ARTICLE_START = 'itemprop="articleBody"'
_FOOTER_MARKS = ("rst-footer-buttons", '{role="contentinfo"}')

_DIV_RE = re.compile(r"^(:{3,})\s*(.*?)\s*$")
_HEADING_RE = re.compile(
    r'^(#{1,6})\s+(.*?)\s*\[¶\]\(#([^)"\s]+)[^)]*\)\s*(?:\{[^}]*\})?\s*$'
)
_HL_CLASS_RE = re.compile(r"\.highlight-([A-Za-z0-9_+-]+)")
_LANG_MAP = {
    "default": "python",
    "python": "python",
    "cpp": "cpp",
    "c++": "cpp",
    "console": "console",
    "bash": "bash",
    "shell": "bash",
    "yaml": "yaml",
    "json": "json",
    "text": "",
    "none": "",
}

# Pandoc attribute blocks: {.class}, {#id}, {key="value" ...}. May wrap lines.
_ATTR_RE = re.compile(r"\{(?:[.#][^{}]*|[\w-]+=[^{}]*|)\}", re.S)
# [text] not followed by ( is a pandoc span left over after attr removal.
_SPAN_RE = re.compile(r"\[([^\[\]\n]*)\](?!\()")
# Relative links become absolute against the canonical page URL.
_REL_LINK_RE = re.compile(r"(\]\()(?!https?://|#|mailto:)([^)\s]+)")


@dataclass
class Heading:
    level: int
    title: str
    anchor: str
    line: int  # index into the cleaned text's lines


@dataclass
class CleanDoc:
    title: str
    text: str
    headings: list[Heading]


def _slice_article(lines: list[str]) -> list[str]:
    start = None
    for i, line in enumerate(lines):
        if _ARTICLE_START in line:
            start = i + 1
            break
    if start is None:
        for i, line in enumerate(lines):
            if _HEADING_RE.match(line):
                start = i
                break
    if start is None:
        return lines
    end = len(lines)
    for i in range(start, len(lines)):
        if any(mark in lines[i] for mark in _FOOTER_MARKS):
            end = i
            break
    return lines[start:end]


def _rebuild_blocks(lines: list[str]) -> list[str]:
    """Drop div fences; convert indented highlight blocks to fenced code."""
    out: list[str] = []
    pending_lang = ""
    in_code = False
    code: list[str] = []
    for line in lines:
        m = _DIV_RE.match(line)
        if m:
            inner = m.group(2)
            if in_code:
                out.append("```" + pending_lang)
                out.extend(code)
                out.append("```")
                out.append("")
                in_code = False
                code = []
                pending_lang = ""
                continue
            hl = _HL_CLASS_RE.search(inner)
            if hl:
                lang = hl.group(1).lower()
                pending_lang = _LANG_MAP.get(lang, lang)
                continue
            if inner == "highlight":
                in_code = True
                code = []
                continue
            continue  # any other div fence is chrome
        if in_code:
            code.append(line[4:] if line.startswith("    ") else line)
        else:
            out.append(line)
    if in_code and code:
        out.append("```" + pending_lang)
        out.extend(code)
        out.append("```")
    return out


def _clean_inline(s: str) -> str:
    s = _ATTR_RE.sub("", s)
    for _ in range(3):  # nested spans unwrap in passes
        s = _SPAN_RE.sub(r"\1", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _clean_prose(text: str) -> str:
    """Strip pandoc syntax outside fenced code blocks."""
    parts = re.split(r"(^```.*?$)", text, flags=re.M)
    # re.split with a capturing group keeps the fence lines; track state.
    out: list[str] = []
    in_fence = False
    for part in parts:
        if part.startswith("```"):
            in_fence = not in_fence
            out.append(part)
            continue
        if in_fence:
            out.append(part)
            continue
        part = _ATTR_RE.sub("", part)
        for _ in range(3):
            part = _SPAN_RE.sub(r"\1", part)
        out.append(part)
    cleaned = "".join(out)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def clean_page(md_text: str, page_url: str | None = None) -> CleanDoc:
    """Extract the article body of a mirror page as clean markdown."""
    lines = _slice_article(md_text.splitlines())
    lines = _rebuild_blocks(lines)

    # Rewrite headings and record anchors before prose cleanup.
    staged: list[str] = []
    raw_headings: list[tuple[int, str, str]] = []  # (staged line idx, ...)
    for line in lines:
        m = _HEADING_RE.match(line)
        if m:
            hashes, title, anchor = m.group(1), _clean_inline(m.group(2)), m.group(3)
            raw_headings.append((len(staged), hashes, title, anchor))  # type: ignore[arg-type]
            staged.append(f"{hashes} {title}")
        else:
            staged.append(line)

    text = _clean_prose("\n".join(staged))
    if page_url:
        text = _REL_LINK_RE.sub(lambda m: m.group(1) + urljoin(page_url, m.group(2)), text)

    # Re-locate headings in the final text (prose cleanup preserves heading lines).
    headings: list[Heading] = []
    final_lines = text.splitlines()
    seen = 0
    wanted = [(h[1] + " " + h[2], h[1], h[2], h[3]) for h in raw_headings]  # type: ignore[misc]
    for i, line in enumerate(final_lines):
        if seen >= len(wanted):
            break
        expect, hashes, title, anchor = wanted[seen]
        if line.strip() == expect.strip():
            headings.append(Heading(len(hashes), title, anchor, i))
            seen += 1

    title = headings[0].title if headings and headings[0].level == 1 else ""
    return CleanDoc(title=title, text=text, headings=headings)


@dataclass
class Chunk:
    breadcrumb: str
    anchor: str
    content: str


def chunk_doc(doc: CleanDoc, max_chars: int = 4000) -> list[Chunk]:
    """Split a cleaned page into heading-scoped chunks for indexing."""
    lines = doc.text.splitlines()
    marks = [h for h in doc.headings if h.level <= 3]
    if not marks:
        body = doc.text.strip()
        return [Chunk(doc.title or "", "", body)] if body else []

    chunks: list[Chunk] = []
    crumb: dict[int, str] = {1: doc.title or ""}

    bounds = [(h, h.line) for h in marks]
    for idx, (h, start) in enumerate(bounds):
        end = bounds[idx + 1][1] if idx + 1 < len(bounds) else len(lines)
        crumb[h.level] = h.title
        for deeper in list(crumb):
            if deeper > h.level:
                del crumb[deeper]
        breadcrumb = " › ".join(crumb[k] for k in sorted(crumb) if crumb[k])
        body = "\n".join(lines[start + 1 : end]).strip()
        if not body and h.level == 1:
            continue
        text = (h.title + "\n\n" + body).strip() if body else h.title
        for part_no, piece in enumerate(_split_long(text, max_chars)):
            chunks.append(Chunk(breadcrumb, h.anchor, piece))
            if part_no == 0 and len(text) <= max_chars:
                break
    return [c for c in chunks if c.content.strip()]


def _split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    current: list[str] = []
    size = 0
    for para in text.split("\n\n"):
        if size + len(para) > max_chars and current:
            pieces.append("\n\n".join(current))
            current, size = [], 0
        current.append(para)
        size += len(para) + 2
    if current:
        pieces.append("\n\n".join(current))
    return pieces
