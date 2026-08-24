# Design: annotation-driven cleaner

**Status:** proposed, not scheduled. The three bugs this addresses (#1, #3, #5) are already fixed incrementally and shipped in 0.1.2 through 0.1.4. This document scopes the structural redesign that would make that class of bug impossible rather than patched.

**Seam:** the rewrite is confined to `src/cudaq_docs_mcp/clean.py`. The public surface (`clean_page`, `chunk_doc`, and the `Heading` / `CleanDoc` / `Chunk` dataclasses) does not change, so `ingest.py`, `server.py`, `inventory.py`, and `assets.py` get zero edits. `db.py` changes only `SCHEMA_VERSION`.

---

## 1. Motivation: three bugs, one cause

The cleaner turns NVIDIA's published Markdown mirrors (pandoc conversions of the rendered HTML docs) into clean Markdown for AI agents. The three bugs we fixed one at a time were not three mistakes; they were one architectural mistake paid for three times.

- **#1** rewrote a C++ lambda `[](float theta)` into a URL, because the link-absolutization pass ran over code and a lambda is valid link syntax.
- **#3** left nested Doxygen code unfenced and left C++ signatures escaped (`std::vector\<double\>`), because the code-block detector was anchored to column zero and the escape-reversal ran heuristically.
- **#5** mangled `**\[1\]**` (numbered specification clauses) into `**\1**`, because a leftover-span regex treated an escaped `[` as a span opener and the math protector treated every `\[..\]` as display math.

Each bug is the same failure: **a text transform fired in a region it should not have touched.** The cleaner ingests pandoc's flattened Markdown, where code, math, prose, links, and escaped literals have all been mashed into the same ambiguous text, and then spends a cascade of regexes trying to reconstruct the structure that pandoc's HTML reader had already resolved one stage earlier and discarded.

The tell: the current cleaner contains **four independent, disagreeing classifiers** for "is this prose?"

- `_rebuild_blocks` div/indent state machine
- `_map_prose` fence and inline-code tokenizer
- `_absolutize` path-shape guard
- `_unescape_prose` math-signal gate

Every bug we fixed was two of those four disagreeing.

## 2. The key insight

The `.md` mirror is not structure-free. Pandoc **retains** the structural annotations, and the current cleaner strips them and then guesses them back:

- inline math as `[\(..\)]{.math .notranslate}`
- code as nested divs `::: {.highlight-LANG} > ::: highlight > indented code`
- chrome as `itemprop` / `role` / `.wy-*` divs
- headings as `# Title[¶](#anchor){.headerlink}`

If we read those annotations instead of discarding them, the classification of every region becomes a structural fact, not a heuristic. Transforms then run only on prose regions, and the bug class disappears by construction.

We rejected the alternative of consuming the HTML or pandoc AST directly. It is cleaner in theory but requires either a build-time pandoc binary (breaks the pure-stdlib, hermetic-test constraint and relocates the same escape-artifact bug into our own toolchain) or a hand-written HTML-to-Markdown emitter for the gnarliest pages (a wash-to-more code). The `.md` retains enough structure to fix all three bug classes with no new dependency.

## 3. Architecture

Two layers replace the "slice by substring, rebuild by marker, then run global prose regexes" pipeline.

### 3.1 Tokenizer (depth-aware div stack)

Replaces `_slice_article`, `_DIV_RE`, and `_rebuild_blocks`. It runs a stack of open frames over `md_text.splitlines()` and emits an ordered list of typed `Region` records.

`Region` fields: `kind`, `lines` (raw, still-escaped source), `lang` (code only), `marker_indent` (for dedent), `base_indent` (enclosing deflist/list content column, for indented-code detection).

Region kinds: `heading`, `prose`, `code`, `math_display`, `table`, `image`, `admonition`, `tab_label`, `drop`.

Fence matching uses a new `_FENCE` regex: optional leading whitespace, an **optional pandoc deflist prefix** (a colon followed by one or more spaces), a run of three or more colons, then optional attribute text. The deflist prefix is load-bearing: it catches the seven openers written `:   ::: {.breathe-sectiondef ...}` on `cpp_api`. Verified: with the prefix the fence stream on the 15,762-line `cpp_api.md` balances exactly (opens 133, closes 133, min-depth 0); without it the stack under-counts openers by seven and truncates the body.

A fence with non-empty attribute text opens a frame (parse its `{.class #id key="v"}` attributes, keep quoted values intact); empty attribute text closes it (pop). A bareword fence (`highlight`) is the code boundary.

**Body extraction is structural, not a string scan.** When a frame's attributes contain `itemprop="articleBody"`, record its depth and emit Regions only from lines strictly inside it. This drops the nav sidebar, breadcrumbs, search, prev/next buttons, horizontal rules, copyright, and Sphinx footer for free, because all are ancestors or siblings of the body frame, never descendants. `itemprop="articleBody"` appears exactly once on every real mirror.

**Fallback ladder** when `articleBody` is absent (all structural): (1) the `role="main"` frame; (2) the first `{#slug .section}` frame; (3) the first heading line; (4) an **empty** doc, so a GitHub 404 page never becomes content. This fixes today's `_slice_article` fallback, which returns the whole input.

### 3.2 Renderer (transform only prose)

Walks the Regions in order and emits Markdown. Code, math, and table regions are emitted verbatim. Prose regions run the inline pipeline in section 4.2. Heading output-line indices are recorded during emission (so `Heading.line` stays exact for `chunk_doc`), with single blank lines between regions so no post-hoc newline collapse is ever needed.

## 4. Rules

### 4.1 Annotation taxonomy (pandoc annotation to region kind)

- **CODE (verbatim, no transforms).** A frame whose class is the bareword `highlight`. Language is the `.highlight-LANG` class on the nearest enclosing frame, found by scanning the stack downward (works for `{.highlight-python}`, `{.input_area .highlight-ipython3}`, and the indented `{.highlight-cpp}` inside `.breathe-sectiondef`). No `.highlight-LANG` on the stack means language `''` (the nbsphinx `.output_area` case), never the previous block's language. Dedent each body line by `marker_indent + 4`. Also code: a blank-line-preceded run inside a deflist body, indented at least `content_column + 4` (the bare-indented Doxygen shape; keeps `test_indented_code_outside_fences_survives` green with no shape-guard).
- **MATH_DISPLAY (verbatim inner, math unescape).** A `:::` frame carrying `.math`, at any indent. Capture the inner lines; drop the fences.
- **MATH_INLINE (inline node).** A bracket span carrying `.math`. The `.math` class is the sole classifier; content is never inspected. `.notranslate` / `.nohighlight` are not math markers and are ignored.
- **DROP (frame and body discarded).** `.prompt` in any form (the nbsphinx `[N]:` counters), and the raw-HTML backtick fence whose info string is `=html` (873 on `cpp_api`, body is only `<!-- -->`).
- **ADMONITION (reconstruct).** `.admonition` (with `.note` / `.warning`). Drop the fence, promote the lead word to a GFM alert or bold, recurse the body.
- **TRANSPARENT (fence dropped, children recurse).** `.tab-set`, `.tab-content`, `.breathe-sectiondef`, `.toctree-wrapper`, `.section`, `.document`, and any wrapper carrying `role` / `itemprop` / `itemscope`. Tab labels (`Python`, `C++`) are promoted to bold so the reader can tell which code is which.
- **TABLE (verbatim, line-level).** A maximal run of consecutive border-or-`|` lines terminated by a blank or non-table line (see the correction in section 5). Never attr-strip or unescape a table: pandoc's hard-wrap interleaves attribute blocks and inline math across the `|` gutters.
- **IMAGE.** `![alt](src){attrs}`, sometimes wrapped `[![]()]()`: keep the token, strip attrs, absolutize the src. Raw-HTML `<figure>` blocks reduce to `![alt](src)` or drop.
- **HEADING.** One-to-six hashes then a space. Parse the title through the full inline pipeline; split off the trailing headerlink and record its `#anchor` fragment verbatim (never slug from the title).
- **PROSE (default).** Paragraphs, lists, blockquotes, deflist terms and bodies, field labels. No footnotes or citations exist in the corpus, so no reconstructor is needed.
- **CHROME.** Anything not a descendant of the body frame, excluded structurally.

### 4.2 Transforms per region kind

- **code:** none. Verbatim. This is the structural death of #1 and #3.
- **table:** none. Verbatim.
- **math_display and math_inline:** one **math-specific** unescape pass over the LaTeX (see section 5, correction 1). Never span-strip, absolutize, or collapse whitespace.
- **image:** attr-strip and link-absolutize on src and any wrapping link.
- **prose:** the six-step inline pipeline, in this order (the order is what makes the bugs impossible):
  0. **coalesce** pandoc soft-wrapped physical lines within one block into one logical string (inline constructs span two to four lines). Never across blank lines or into fences.
  1. **parse while still escaped** into a small inline node tree (Str, Code, Math, Span, Link, Image, Headerlink) by one left-to-right scanner. Parsing precedes unescaping because pandoc leaves every structural bracket unescaped and every literal bracket escaped, so the parse is unambiguous only while escapes are intact. Backtick runs shield brackets inside code.
  2. **heading anchor:** take the `#fragment` from the Headerlink node and drop the node. Drop every headerlink glyph.
  3. **attr-strip and span-unwrap:** drop `{.class}` and `key="v"` records; unwrap Span nodes (`.pre`, `.xref`, and the Pygments signature classes `.k .n .p .kt .w .sig-name .descname .sig-param .sig-paren`) to a fixed point. Doxygen signatures reduce to plain text.
  4. **link-absolutize:** rewrite a relative Link/Image target with `urljoin(page_url, target)` on the raw target. Split the optional quoted title off the destination first (see section 5, correction 4). No shape-guard is needed, because a lambda never reaches here (it is code).
  5. **unescape last, on Str leaves and Math inner text only**, exactly once, removing one leading backslash before any character in the punctuation set. Never on inline-code content, fenced code, or link targets.

### 4.3 Deletions

- `_ARTICLE_START`, `_FOOTER_MARKS`, `_slice_article` -> structural articleBody extraction plus fallback ladder.
- `_DIV_RE`, `_rebuild_blocks` -> the div-stack tokenizer.
- `_ATTR_RE` -> structural attribute records (step 3).
- `_SPAN_RE` -> Span-node unwrap (step 3).
- `_REL_LINK_RE`, `_absolutize` -> Link-node absolutize (step 4), no path-shape guard.
- `_MATH_SPAN_RE`, `_MATH_SIGNAL_RE`, `_unescape_prose` -> math is a node by the `.math` class; the content heuristic is gone.
- `_clean_inline` -> headings use the full inline pipeline.
- `_INLINE_CODE_RE`, `_map_prose` -> code protection is structural.
- `_clean_prose` and the heading re-location loop -> the renderer records indices during emission.

Kept, repurposed: `_HL_CLASS_RE` (applied to the stack), `_LANG_MAP` (add `ipython3 -> python`, change `default -> ''`), and the prose punctuation class for the step-5 leaf unescaper.

## 5. Required corrections before implementing

Adversarial review found five ways the plan as first drafted would ship corruption. Each is verified and must be in the implementation, or the rewrite is worse than what it replaces.

1. **Math needs its own unescape set.** The prose punctuation class has no `^`, so `a^\dagger` (the creation operator, 139 occurrences across six sampled pages) would render as `a\^\dagger`. Math nodes and `.math`-div content need a distinct unescaper including `^` (and likely `&`, `%`, `$`). Verify against `api/default_ops.md` that `a_1\^\dagger` becomes `a_1^\dagger`.
2. **A backtick-fence handler, matched before the `:::` fence test.** The `{=html}` blocks (873 on `cpp_api`, holding only `<!-- -->`) are backtick fences, invisible to a `:::`-only tokenizer; unhandled, roughly 2,600 junk lines leak into prose. Recognize `` ```{=html} `` indentation-tolerantly, drop the block, and run this check first each line so a stray `:::`-looking line inside a raw block cannot desync the stack.
3. **Grid table is a maximal consecutive run, not first-border-to-last-border.** `simulators.md` has 13 border lines forming four distinct tables separated by prose and headings. First-to-last would swallow all four plus the text between them into one blob and corrupt `chunk_doc`'s heading indices. Define the region as a maximal run of consecutive border-or-`|` lines terminated by a blank or non-table line.
4. **Explicit target/title split on links.** `](url "title")` must split the destination at the first unescaped space before `urljoin`, or the title lands inside the href (2,601 links on `cpp_api`). The shipped `_REL_LINK_RE` already does this with `[^)\s]+`; the rewrite must not lose it.
5. **Re-verify every file:line citation before coding.** The survey cited `dynamics.md` paths that 404 (the real page is `using/dynamics`). Structural facts reproduced; scattered line references did not and must be re-fetched.

## 6. Implementation phases

1. **Golden snapshot.** Run the shipping `clean_page` over roughly nine inputs (six heavy mirrors plus three non-mirror or 404 inputs), save each `doc.text`. This is the before-side of the acceptance gate.
2. `Region` dataclass, the deflist-tolerant `_FENCE`, and `_parse_attrs`. Unit-test fence balance on `cpp_api` (opens == closes, min-depth 0).
3. Tokenizer core: the stack, articleBody extraction, fallback ladder. Test that the 404 inputs yield an empty doc.
4. Frame classification (code, math, drop, admonition, transparent) **and the backtick-`{=html}` handler**. Test the output-cell language-empty case.
5. Line-level detectors: **maximal-run grid table**, `<figure>` block, and the bare-indented deflist-body code rule.
6. Inline scanner (`_parse_inline`). **Iterative, not recursive**: `cpp_api` signature lines run to 2,664 characters with roughly 100 nested bracket groups. Handles the three-level `[[code]{.pre}](url){.reference}` shape, **link title split**, empty `[]{#id}` anchors, and backtick-shielded brackets.
7. Node serialization (steps 2 through 5) with the **separate math unescaper**. Test escaped signatures, escaped literals (`[float]`, `[[nodiscard]]`, `**[1]**`), and that code and link targets are never unescaped.
8. Renderer: emit in order, single blank lines between regions, record heading output indices during emission.
9. Reassemble `clean_page`; get the existing tests green.
10. Add region-model tests: grid table stays four regions; output cell language empty; `{=html}` dropped; indented `.math` div; 404 to empty doc; deflist-prefix does not truncate; tab labels promoted.
11. **Corpus-diff gate** (the real acceptance test): new versus golden over all inputs; hand-inspect every delta as improvement or provably neutral. Kept as a `scripts/` tool, network-free once cached, not in the offline pytest suite.
12. Schema bump, version bump, full reindex, MCP spot-checks; then let the refreshed assets publish.

## 7. Test migration

Two existing math tests use bare `\(..\)` and `\[..\]` **without** the `.math` annotation (synthetic fixtures). The corpus proves real math always carries `.math` (192 inline spans, 25 divs, zero bare mid-paragraph). Migrate those fixtures to the corpus-true shape (`[\(..\)]{.math}` and `::: {.math}` divs), and add a same-page assertion that a non-`.math` escaped bracket still unescapes to a literal. This is a faithfulness fix, not a loosening.

## 8. Rollout

The cleaned Markdown is stored in `pages.markdown` and `chunks.content`, so changing `clean.py` changes stored bytes. Bump `db.py` `SCHEMA_VERSION` (4 to 5). This is self-migrating: `index_path()` embeds `s{N}` in the filename, so old `s4` indexes are ignored and a fresh index is built; cached-index users rebuild locally on next run. Bump the package version. Sequence: land the code and schema bump, run a full build, then let `refresh-index.yml` publish the `s5` assets, gated on the corpus-diff review and a real reindex spot-check (both API pages readable, no `<figure>` or comment leakage, tables intact, anchors resolve).

## 9. Effort, risk, recommendation

**Effort:** roughly `+245` lines of code (315 to about 560) and two to three focused days. Most of the cost and nearly all the risk is in the inline scanner and the deflist/indent bookkeeping. The corpus-diff gate is where time balloons: diffing old versus new over `cpp_api` surfaces dozens of per-signature deltas (titles, permalinks, span spacing), each a judgment call.

**This is not a "less code" win.** It trades a pile of fragile, mutually-interfering regexes for a small correct parser that is larger but no longer guesses. The value is eliminating the regression class: in the current approach every new pandoc shape (grid tables, notebook cells, `{=html}` noise, indented math) spawns another guard and another cross-interaction; the rewrite decides region kind by annotation and depth, so those shapes are handled once.

**Recommendation:** do it as a deliberate standalone project, not urgently. The three bugs are fixed and the tool works. The strongest reasons to execute are continued investment in the tool and the expectation of more pandoc shapes over time. The residual quality gap the rewrite does **not** close is the backend reference tables: pandoc's lossy hard-wrap means "verbatim" keeps them legible-but-noisy, and truly fixing them is a separate, column-safe, cell-by-cell effort.

---

*Derived from a five-dimension corpus survey and an adversarial stress pass over the real mirrors. Every structural claim (fence balance, single `articleBody`, math always `.math`, 29/29 lambdas in highlight divs, the `{=html}` and grid-table counts) was verified against fetched pages.*
