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


CPP_SAMPLE = """\
::: {itemprop="articleBody"}
# Kernels[¶](#kernels "Permalink to this heading"){.headerlink}

Prose with a [relative link](../other.html){.reference .internal} and an
inline lambda `[](int n) __qpu__ {}` that must survive.

::: {.highlight-cpp .notranslate}
::: highlight
    auto kernel = [](float theta) __qpu__ -> bool {
      return true;
    };
    auto multi = [](const std::vector<int64_t> &dims,
                    double t) __qpu__ {};
:::
:::
:::
::: {.rst-footer-buttons role="navigation"}
:::
"""


def test_code_is_never_link_rewritten():
    """Regression for issue #1: C++ lambdas look like markdown links."""
    doc = clean_page(CPP_SAMPLE, page_url=URL)
    assert "auto kernel = [](float theta) __qpu__ -> bool {" in doc.text
    assert "auto multi = [](const std::vector<int64_t> &dims," in doc.text
    assert "`[](int n) __qpu__ {}`" in doc.text
    fenced = doc.text.split("```")[1]
    assert "](https://" not in fenced
    # Prose links are still absolutized.
    assert "(https://nvidia.github.io/cuda-quantum/latest/other.html)" in doc.text


INDENTED_SAMPLE = """\
::: {itemprop="articleBody"}
# API[¶](#api "Permalink to this heading"){.headerlink}

See [the basics](basics/basics.html){.reference .internal} and the
figure ![](../_images/bell.png){.align-center}.

cudaq::draw
:   Draw a kernel.

        auto kernel = [](float theta) __qpu__ {};
        auto capture = [&](int x) { return x; };
        auto copy = [=](double t) -> double { return t; };
::: {.rst-footer-buttons role="navigation"}
:::
"""


def test_indented_code_outside_fences_survives():
    """Issue #1, second shape: Doxygen examples are indented, not fenced."""
    doc = clean_page(INDENTED_SAMPLE, page_url=URL)
    assert "auto kernel = [](float theta) __qpu__ {};" in doc.text
    assert "auto capture = [&](int x) { return x; };" in doc.text
    assert "auto copy = [=](double t) -> double { return t; };" in doc.text
    # Real relative links and images are still absolutized.
    assert "(https://nvidia.github.io/cuda-quantum/latest/using/basics/basics.html)" in doc.text
    assert "![](https://nvidia.github.io/cuda-quantum/latest/_images/bell.png)" in doc.text


NESTED_HL_SAMPLE = """\
::: {itemprop="articleBody"}
# API[¶](#api "Permalink to this heading"){.headerlink}

cudaq::draw

:   Draws a kernel.

    Usage:

    ::: {.highlight-cpp .notranslate}
    ::: highlight
        #include <cudaq.h>

        auto bell = []() __qpu__ {
          h(q[0]);
        };
    :::
    :::

    Returns a std::vector\\<double\\> of amplitudes for a std::complex\\<double\\>
    state. For \\(i \\< d\\) the norm is \\(\\|\\mathbf{x}\\|_2\\).
::: {.rst-footer-buttons role="navigation"}
:::
"""


def test_nested_highlight_block_is_fenced():
    """Issue #3: highlight divs nested in a definition list must fence."""
    doc = clean_page(NESTED_HL_SAMPLE, page_url=URL)
    code = doc.text.split("```")[1]
    assert "#include <cudaq.h>" in code
    assert "auto bell = []() __qpu__ {" in code
    # dedented to column zero, not left at the definition-list indent
    assert "\n#include <cudaq.h>" in "\n" + code.lstrip("cpp\n")


def test_signature_escapes_unescaped_in_prose():
    """Issue #3: pandoc-escaped C++ template brackets read as real C++."""
    doc = clean_page(NESTED_HL_SAMPLE, page_url=URL)
    assert "std::vector<double>" in doc.text
    assert "std::complex<double>" in doc.text
    assert "std::vector\\<" not in doc.text


def test_latex_math_is_preserved():
    """Issue #3: math delimiters and norm bars are LaTeX, not escapes."""
    doc = clean_page(NESTED_HL_SAMPLE, page_url=URL)
    assert "\\(i \\< d\\)" in doc.text
    assert "\\(\\|\\mathbf{x}\\|_2\\)" in doc.text


DISPLAY_MATH_SAMPLE = """\
::: {itemprop="articleBody"}
# Dynamics[¶](#dynamics "Permalink to this heading"){.headerlink}

The Hamiltonian \\(\\sigma_z\\) evolves per \\[H = \\frac{\\omega_z}{2}
\\sigma_z + \\omega_x \\cos(\\omega_d t)\\]. Returns a std::vector\\<double\\>.
::: {.rst-footer-buttons role="navigation"}
:::
"""


def test_display_and_inline_math_survive_with_signatures():
    """Issue #3: real \\(..\\) and \\[..\\] math is preserved, signatures unescaped."""
    doc = clean_page(DISPLAY_MATH_SAMPLE, page_url=URL)
    assert "\\(\\sigma_z\\)" in doc.text
    assert "\\frac{\\omega_z}{2}" in doc.text
    assert "\\sigma_z + \\omega_x \\cos(\\omega_d t)\\]" in doc.text
    assert "std::vector<double>" in doc.text  # signature still fixed
