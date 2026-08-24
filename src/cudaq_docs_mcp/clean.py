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

# Div markers may be indented when nested in a definition list (the
# Doxygen-generated C++ API page does this), so leading space is captured.
_DIV_RE = re.compile(r"^(\s*)(:{3,})\s*(.*?)\s*$")
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
# Values are always quoted, which keeps C++ like ``{}`` or ``{i=0;}`` intact.
_ATTR_RE = re.compile(r"\{(?:[.#][^{}]*|[\w-]+=\"[^{}]*)\}", re.S)
# [text] not followed by ( is a pandoc span left over after attr removal.
# The opening bracket must be unescaped: a backslash-escaped \[ is a literal
# bracket (e.g. **\[1\]** numbered clauses), not a span to strip (#5).
_SPAN_RE = re.compile(r"(?<!\\)\[([^\[\]\n]*)\](?!\()")
# Relative links become absolute against the canonical page URL.
_REL_LINK_RE = re.compile(r"(\]\()(?!https?://|#|mailto:)([^)\s]+)")
# A doc target has a letter file extension, at end or before a #fragment
# (run_kernel.html#sample, basics.md); a lambda default like x=1.5 (digit
# after the dot) does not.
_DOC_EXT_RE = re.compile(r"\.[A-Za-z]+(?:[#?]|$)")
# Pandoc escapes markdown punctuation in prose; C++ signatures live in
# prose, so std::vector\\<double\\> is stored escaped. Reversed last, after
# the passes above rely on the escapes still being present.
_UNESCAPE_RE = re.compile(r"\\([\\`*_{}\[\]()>#+.!|~<-])")
# Math spans are left alone: their delimiters and \| norm bars are real
# LaTeX, not markdown escapes, so they must survive unescaping.
_MATH_SPAN_RE = re.compile(r"\\\((?:.|\n)*?\\\)|\\\[(?:.|\n)*?\\\]")


# A \(..\) / \[..\] span is real math only if it carries a LaTeX signal: a
# backslash-command, a sub/superscript, or a norm bar. Bare bracket content
# like \[1\] (a numbered clause) or \[float\] is a literal, not math (#5).
_MATH_SIGNAL_RE = re.compile(r"\\[a-zA-Z]|[\^_]|\\\|")


def _unescape_prose(prose: str) -> str:
    out: list[str] = []
    last = 0
    for m in _MATH_SPAN_RE.finditer(prose):
        out.append(_UNESCAPE_RE.sub(r"\1", prose[last : m.start()]))
        span = m.group(0)
        # \(..\) is inline math, always kept. \[..\] is math only with a
        # LaTeX signal; otherwise it is a literal label like \[1\] (#5).
        keep = span.startswith("\\(") or bool(_MATH_SIGNAL_RE.search(span))
        out.append(span if keep else _UNESCAPE_RE.sub(r"\1", span))
        last = m.end()
    out.append(_UNESCAPE_RE.sub(r"\1", prose[last:]))
    return "".join(out)


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
    """Drop div fences; convert highlight blocks to fenced code.

    Pandoc indents a highlight block's code four spaces past its ``:::
    highlight`` marker, so nested blocks (indented markers) are dedented by
    the marker indent plus four.
    """
    out: list[str] = []
    pending_lang = ""
    in_code = False
    code_indent = 0
    code: list[str] = []
    for line in lines:
        m = _DIV_RE.match(line)
        if m:
            marker_indent, inner = len(m.group(1)), m.group(3)
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
                code_indent = marker_indent + 4
                continue
            continue  # any other div fence is chrome
        if in_code:
            pad = " " * code_indent
            code.append(line[code_indent:] if line.startswith(pad) else line.lstrip(" "))
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


_INLINE_CODE_RE = re.compile(r"(`[^`\n]+`)")


def _map_prose(text: str, transform) -> str:
    """Apply transform to prose only: never inside fenced or inline code."""
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
        pieces = _INLINE_CODE_RE.split(part)
        out.append("".join(c if c.startswith("`") else transform(c) for c in pieces))
    return "".join(out)


def _absolutize(m: re.Match, page_url: str) -> str:
    """Absolutize a relative doc link; leave code that merely looks like one.

    A relative doc link always has a path separator or a letter file
    extension (``../index.html``, ``basics/basics.html``). A C++ lambda's
    parameter list, ``[](float theta)`` or ``[](x=1.5)``, has neither: a
    numeric literal like ``1.5`` is not a doc suffix. Code outside fenced
    blocks (Doxygen examples in definition lists) reaches this path, so the
    target's shape is the final guard (#7).
    """
    target = m.group(2)
    if "/" not in target and not _DOC_EXT_RE.search(target):
        return m.group(0)
    return m.group(1) + urljoin(page_url, target)


def _clean_prose(text: str, page_url: str | None = None) -> str:
    """Strip pandoc syntax and absolutize relative links, in prose only."""

    def transform(prose: str) -> str:
        prose = _ATTR_RE.sub("", prose)
        for _ in range(3):
            prose = _SPAN_RE.sub(r"\1", prose)
        if page_url:
            prose = _REL_LINK_RE.sub(lambda m: _absolutize(m, page_url), prose)
        return _unescape_prose(prose)

    cleaned = _map_prose(text, transform)
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

    text = _clean_prose("\n".join(staged), page_url)

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
