from cudaq_docs_mcp.clean import chunk_doc, clean_page

SAMPLE = """\
::: wy-grid-for-nav
::: {.wy-menu .wy-menu-vertical role="navigation"}
-   [Nav only link](../index.html){.reference .internal}
:::
::: {itemprop="articleBody"}
::: {#quick-start .section}
# Quick Start[¶](#quick-start "Permalink to this heading"){.headerlink}

Intro paragraph with a [link](../other.html){.reference .internal} and
[`cudaq`{.docutils .literal .notranslate}]{.pre} inline code.

::: {#install .section}
## Install CUDA-Q[¶](#install "Permalink to this heading"){.headerlink}

::: {.highlight-console .notranslate}
::: highlight
    pip install cudaq
:::
:::

More text after the code block.
:::
:::
:::
::: {.rst-footer-buttons role="navigation" aria-label="Footer"}
[Next](x.html){.btn .btn-neutral}
:::
::: {role="contentinfo"}
© Copyright 2026, NVIDIA Corporation & Affiliates.
:::
"""

URL = "https://nvidia.github.io/cuda-quantum/latest/using/quick_start.html"


def test_strips_chrome_keeps_content():
    doc = clean_page(SAMPLE, page_url=URL)
    assert doc.title == "Quick Start"
    assert "Nav only link" not in doc.text
    assert "wy-grid" not in doc.text
    assert "© Copyright" not in doc.text
    assert "More text after the code block." in doc.text


def test_code_blocks_rebuilt_with_language():
    doc = clean_page(SAMPLE, page_url=URL)
    assert "```console\npip install cudaq\n```" in doc.text


def test_inline_spans_and_links():
    doc = clean_page(SAMPLE, page_url=URL)
    assert "`cudaq`" in doc.text
    assert "{.docutils" not in doc.text
    assert "(https://nvidia.github.io/cuda-quantum/latest/other.html)" in doc.text


def test_headings_carry_real_anchors():
    doc = clean_page(SAMPLE, page_url=URL)
    assert [(h.level, h.anchor) for h in doc.headings] == [
        (1, "quick-start"),
        (2, "install"),
    ]


def test_chunking_breadcrumbs():
    doc = clean_page(SAMPLE, page_url=URL)
    chunks = chunk_doc(doc)
    assert chunks, "expected at least one chunk"
    install = next(c for c in chunks if c.anchor == "install")
    assert install.breadcrumb == "Quick Start › Install CUDA-Q"
    assert "pip install cudaq" in install.content
