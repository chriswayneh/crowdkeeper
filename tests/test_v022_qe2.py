"""QE round 2 on PR #4: no autolinks under cmark-gfm or linkify, distinguishable escapes."""

import html as htmllib
import re
from pathlib import Path

import cmarkgfm
import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st
from markdown_it import MarkdownIt

from crowdkeeper import core

MDIT = MarkdownIt("gfm-like", {"linkify": True})
MDIT.enable(["linkify", "strikethrough"])


def gfm(src):  # GitHub-flavored: table, strikethrough and autolink extensions
    return cmarkgfm.github_flavored_markdown_to_html(src)


RENDERERS = {"cmark-gfm": gfm, "markdown-it-linkify": MDIT.render}
TABLE = "| G | M |\n|---|---|\n| {} | 1 |\n"
LINKY = [
    "a@b.co",
    "mailto:a@b.co",
    "x+y@evil.example",
    "a@@b.co",
    "evil.com",
    "ftp.evil.com",
    "//evil.com/x",
    "evil.co.uk/path",
    "xn--80ak6aa92e.com",
    "www.evil.com",
    "https://evil.example/a",
    "0.KW",
    "пример.рф",
]


def _text(h):
    return htmllib.unescape(re.sub(r"<[^>]+>", "", h))


def _cell(render, s):
    h = render(TABLE.format(core.md_safe(s)))
    return h, h.split("<td>")[1].split("</td>")[0] if h.count("<td>") == 2 else None


@pytest.mark.parametrize("name", RENDERERS)
@pytest.mark.parametrize("s", LINKY)
def test_md_safe_never_links(name, s):
    h, cell = _cell(RENDERERS[name], s)
    assert cell is not None and "<a " not in h.lower(), h
    assert _text(cell).strip() == s  # still shown exactly


@pytest.mark.parametrize("name", RENDERERS)
@pytest.mark.parametrize("s", LINKY)
def test_code_spans_never_link(name, s):
    h = RENDERERS[name]("- `" + core.md_code_safe(s) + "`\n")
    assert "<a " not in h.lower() and "<code>" in h, h


def test_at_sign_is_broken_out_of_text():
    # kills the mutant that drops the @ rule: cmark-gfm links a\@b.co
    out = core.md_safe("a@b.co")
    assert "@" in out and "<a " not in gfm(out)
    assert out != "a\\@b\\.co"


def test_dots_between_alphanumerics_escaped():
    assert core.md_safe("evil.com") == "evil\\.com"


PLAIN = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn")),
    max_size=40,
)


@pytest.mark.parametrize("name", RENDERERS)
def test_md_safe_property_both_renderers(name):
    render = RENDERERS[name]

    @settings(max_examples=1500, deadline=None)
    @given(PLAIN)
    @example("0.KW")
    @example("a@b.co")
    @example("mailto:a@b.co")
    @example("evil.co.uk/path")
    @example("@@")
    @example("a`b@c")
    def check(s):
        h, cell = _cell(render, s)
        assert cell is not None and "<a " not in h.lower(), (s, h)
        assert not re.search(r"<(em|strong|s|del|img|script)\b", cell, re.I), (s, h)

    check()


# minor: a literal "U+001B" must not look like a real ESC
def test_term_safe_distinguishes_literals():
    assert core.term_safe("\x1b") != core.term_safe("U+001B")
    assert core.term_safe("\x1b") != core.term_safe("\\u001b")
    assert core.term_safe("a\x1bb") == "a\\u001bb"
    assert core.term_safe("a\\b") == "a\\\\b"
    assert core.term_safe("\t\n") == "\\t\\n"


def test_roadmap_ticks_v022_items():
    text = (Path(__file__).parent.parent / "ROADMAP.md").read_text()
    sec = text.split("## Patch: v0.2.2")[1].split("\n## ")[0]
    for k in ("row length", "UTF-8", "control character", "row errors", "term_safe"):
        assert re.search(r"- \[x\] .*" + re.escape(k), sec, re.I), k


def test_term_safe_astral_uses_capital_u_escape():
    from crowdkeeper.core import term_safe

    assert term_safe("\U000e0001") == "\\U000e0001"
    assert term_safe("a\U000e0001b") == "a\\U000e0001b"
