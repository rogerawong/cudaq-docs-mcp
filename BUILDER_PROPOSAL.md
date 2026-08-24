# Proposal: generate CUDA-Q's agent Markdown from the Sphinx doctree

**Status:** proposal, upstream-facing. This is the source-side counterpart to `DESIGN.md`. `DESIGN.md` is the downstream fix ("since this tool consumes NVIDIA's Markdown mirrors, clean them robustly"). This document is the upstream fix ("if the mirrors were generated from the semantic doctree instead of from rendered HTML, the defects would not exist to clean").

**Audience:** the CUDA-Q docs team, and anyone building agent tooling on the CUDA-Q docs.

**Verified:** `NVIDIA/sphinx-llm` exists (Apache-2.0). The base library `liran-funaro/sphinx-markdown-builder` (MIT) has open issues [#21](https://github.com/liran-funaro/sphinx-markdown-builder/issues/21) (does not parse breathe directives) and [#42](https://github.com/liran-funaro/sphinx-markdown-builder/issues/42) (asterisk omitted in overloaded signatures). The Sphinx builder/writer API facts below were checked against the Sphinx source and the official builder API reference.

---

## 1. The problem, restated at the source

CUDA-Q's `build_docs.sh` runs `sphinx-build -b html`, then `pandoc <html> -f html -t markdown` to produce the `.md` mirrors that `llms.txt` points at. That is `RST/Doxygen/notebooks -> HTML -> Markdown`, and the middle hop is lossy on purpose: HTML is a presentation target. So the mirrors carry presentation scaffolding (nav chrome, CSS classes, permalink glyphs, backslash escaping) and lose semantic types (a code block's language, a math node's TeX, a C++ signature's structure). Every defect a downstream cleaner fights was introduced by deriving a machine artifact from a rendering.

The principle: **generate agent-facing artifacts from the earliest semantic stage of the pipeline, never from a presentation target.**

## 2. Where the semantic stage is

Sphinx hands each builder a fully resolved doctree at `write_doc(docname, doctree)`. Immediately before that call, `Builder._write_serial` runs `env.get_and_resolve_doctree(docname, self)`, which applies the post-transforms (including `ReferencesResolver`) and expands toctrees. At write time, therefore:

- Every `pending_xref` has already become a `nodes.reference` carrying a `refuri` or `refid`, computed through `sphinx.util.nodes.make_refnode` against the active builder's `get_target_uri`.
- Toctrees are already expanded into bullet lists.
- Code, math, and signatures are still typed nodes, not HTML.
- Nav, CSS, and permalink-glyph nodes do not exist. Chrome is a theme concern, injected only during HTML rendering.

This is the stage the mirror should be generated from.

## 3. Architecture (high level)

A standard Sphinx builder/writer/translator triad, modeled on the roughly 80-line `sphinx/builders/text.py`, or better, built on `NVIDIA/sphinx-llm`, which already implements this pattern and already emits `llms.txt` / `llms-full.txt`.

- **Builder** subclasses `sphinx.builders.Builder`: set `name`, `format`, `out_suffix='.md'`, `default_translator_class`, and implement `get_outdated_docs`, `write_doc`, and the two URI methods below. Register with `app.add_builder` in a small `setup(app)`, selected by `sphinx-build -b <name>`.
- **Translator** subclasses the docutils `NodeVisitor` (the `visit_<node>` / `depart_<node>` pattern) and emits Markdown.

Node to Markdown mapping (the parts that matter):

- **Code:** `literal_block['language']` gives a fenced block with the correct language; inline `literal` gives backticks. The node text is the verbatim source. No Pygments, no HTML.
- **Math:** the math nodes hold raw single-backslash LaTeX (MathJax stores TeX, not rendered markup), emitted as `$...$` / `$$...$$`. This is exactly the case the HTML round-trip corrupts (for example a creation operator rendered as `a\^\dagger`).
- **Links:** read `refuri` (external and resolved cross-doc) and `refid` (intra-page), emit `[text](url)`. Absolute canonical URLs come from overriding `get_target_uri(docname)` to return `f"{base}/{docname}.html"` and `get_relative_uri(from_, to)` to return `get_target_uri(to)` unrelativized, so `make_refnode` bakes absolute URLs in at resolution time. Both overrides are required: overriding only `get_target_uri` yields broken links, because the default `get_relative_uri` would relativize between two absolute URLs.
- **Signatures:** C++ (breathe) and Python (autodoc) both emit `desc > desc_signature` trees. The clean one-line signature is reconstructable from the signature node. Iterate the `desc_signature` children for overloads; render the `desc_content` docstring separately as prose.
- **Headings and anchors:** `section` / `title` become `#` headings with stable anchors from the signature node ids or a human slug.

Notebook prompts are HTML-only nodes that drop automatically when the builder honors the `only` expression; notebook outputs are per-format raw nodes, so the translator selects the text format and never the HTML one.

## 4. The one piece of real net-new work

Base `sphinx-markdown-builder`, and therefore `sphinx-llm` which inherits from it, sends the C++ signature token family (`desc_sig_name`, `desc_sig_keyword`, `desc_sig_keyword_type`, `desc_sig_punctuation`, `desc_sig_operator`, `desc_sig_space`, and related) to `unknown_visit`, which raises `SkipNode`. The result: return types, `*`, keywords, and parameter types are silently dropped from every breathe-rendered C++ signature. That is issues #21 and #42, still open, and it is precisely the `cpp_api` surface that produced bug #3 in the downstream tool.

So the differentiating contribution is a translator that handles those signature-token nodes faithfully. It is small and well-bounded, but it fails by omission with an easy-to-miss warning, so it must be validated with a signature-diff harness against Doxygen. "Built with no errors" does not mean the signatures survived.

## 5. Scope (phases)

0. **Baseline and harness.** Pin the toolchain, stand up `sphinx-llm` as the base, and build a signature-diff harness (emitted C++ `.md` signatures versus Doxygen) to quantify today's silent omission.
1. **Prototype pass.** Run the Markdown builder as a second `sphinx-build` pass alongside the HTML pass; verify fenced code with language, math, headings, anchors, and toctree expansion on the hand-written RST.
2. **C++ signature fidelity (the crux).** Implement the `desc_sig_*` translator handlers; validate overloads; drive the harness diff to zero on the C++ API pages.
3. **Absolute URLs and notebooks.** Wire the base-URL config and the two URI overrides (including intra-doc anchor absolutization); handle notebook text outputs, the `ipython3 -> python` fence mapping, HTML-only prompt elision, and inline-tab flattening.
4. **Replace pandoc and emit artifacts.** Swap the `pandoc <html> -t markdown` step in `build_docs.sh` for the builder pass; regenerate `llms.txt` / `llms-full.txt` from the clean Markdown; add the signature harness to CI.
5. **Upstream.** Land as an opt-in extension in `docs/sphinx`, and contribute the `desc_sig_*` fix back to `NVIDIA/sphinx-llm` and the base library (resolving #21 and #42), so the whole ecosystem gains it.

## 6. Hard parts and residual lossiness (honest)

- **C++ signatures are the hard center.** The failure is silent omission; it must be diffed against Doxygen, not assumed from a clean build.
- **C++ anchors are Doxygen-mangled** and a single signature carries multiple ABI-variant ids. Heading slugs and link targets must stay consistent or intra-doc links break.
- **Absolute-anchor correctness is subtle.** Override one URI method without the other and links break; intra-doc references set a bare `refid`, which must be absolutized against the current document's URL.
- **`conf.py` sets no `html_baseurl` today,** so the builder must own and thread its own base-URL config; subdirectory docs need URL joining, not string concatenation.
- **Notebook outputs are format-gated raw nodes.** If the builder's format is not one the raw nodes carry, outputs vanish unless the translator explicitly selects a text format. Rich or image outputs need asset handling, not text extraction.
- **Parallel writes.** `write_doc` runs in worker processes; any per-document translator state must not live on shared mutable builder state, or parallel output is nondeterministic.
- **Residual lossiness that remains even here:** nbsphinx still uses pandoc at build time for notebook markdown cells (this route removes pandoc from the HTML-to-Markdown hop, not from the upstream toolchain); inline-tab multi-language blocks must be deliberately flattened; rich notebook outputs and very long template signatures degrade. Markdown is less expressive than RST plus Doxygen, so a few constructs will not survive perfectly. Better by a wide margin, not literally lossless.

## 7. Upstream path

Land it as an opt-in Sphinx extension inside `cuda-quantum/docs/sphinx`, registered in a small `setup(app)` and selected with `sphinx-build -b <name>`. It is additive and low-risk: it runs as a separate builder pass and does not touch the HTML build, so the site is unaffected until the team chooses to swap the `pandoc` step. It composes with work already merged: NVIDIA already owns the architecture in `sphinx-llm`, so the net-new contribution is the C++ signature-fidelity translator that `sphinx-llm` currently inherits as a gap. That fix belongs upstream in `NVIDIA/sphinx-llm` and the base library, so the change is small, reviewable, and benefits the broader ecosystem. Ship it with the signature-diff CI harness so the silent-omission failure mode is caught automatically.

## 8. Payoff

Every agent-facing consumer benefits at once, and fidelity is fixed at the source rather than patched downstream. `llms.txt` and `llms-full.txt` readers, any RAG or MCP index (including this project's server), get fenced code with language, real single-backslash LaTeX, pristine C++ and Python signatures, absolute canonical cross-reference URLs, heading anchors, and zero nav or escaping noise, because types are never flattened to HTML and back and the doctree contains no chrome. This is strictly higher-leverage than any downstream cleaner: a downstream pass can only guess at structure that HTML and pandoc already destroyed, and a dropped C++ return type cannot be recovered from HTML that never rendered it faithfully. Generating from the resolved doctree makes the clean Markdown a first-class, deterministic, version-controlled build artifact, so every current and future agent tool inherits the fidelity for free.

---

*Grounded in a verified survey of the Sphinx builder API (`sphinx.builders.Builder`, `get_and_resolve_doctree`, `ReferencesResolver`, `make_refnode`, the `TextBuilder` model), the breathe and autodoc signature node families, and the prior art (`NVIDIA/sphinx-llm`, `liran-funaro/sphinx-markdown-builder` and its open issues #21 and #42).*
