# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""EPUB reading: pages cut at the table of contents, listings kept whole."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

pytest.importorskip("bs4")

from app import book, config, epub
from app import chunk as chunk_module

CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

OPF = """<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="mark" href="Text/mark.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="ch2" href="Text/ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="mark"/><itemref idref="ch1"/><itemref idref="ch2"/>
  </spine>
</package>"""

NCX = """<?xml version="1.0"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><navMap>
  <navPoint id="n1"><navLabel><text>1. Queues</text></navLabel>
    <content src="Text/ch1.xhtml"/>
    <navPoint id="n2"><navLabel><text>1.1. A ring buffer</text></navLabel>
      <content src="Text/ch1.xhtml#s11"/></navPoint>
    <navPoint id="n3"><navLabel><text>1.2. Locks</text></navLabel>
      <content src="Text/ch1.xhtml#s12"/></navPoint>
  </navPoint>
  <navPoint id="n4"><navLabel><text>2. Stacks</text></navLabel>
    <content src="Text/ch2.xhtml"/></navPoint>
</navMap></ncx>"""


def xhtml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title></head>'
        f"<body>{body}</body></html>"
    )


MARK = xhtml("<p>This copy belongs to reader@example.org</p>")
CH1 = xhtml(
    "<h1>1. Queues</h1><p>A queue keeps order.</p>"
    '<h2 id="s11">1.1. A ring buffer</h2>'
    "<p>The size is 2<sup>10</sup> slots, a&nbsp;power of two.</p>"
    '<pre class="listing">int next(int i)</pre>'
    '<pre class="listing">{</pre>'
    '<pre class="listing">&#160;&#160;&#160;&#160;return (i + 1) % SIZE;</pre>'
    '<pre class="listing">}</pre>'
    '<p class="listing-podpis">A caption, not code</p>'
    '<p><a id="s12"/></p><p class="H2">1.2. Locks</p>'
    '<p class="listing">lock(&amp;q);</p>'
    "<ul><li>first</li><li>second<ul><li>inner</li></ul></li></ul>"
    "<table><tr><th>op</th><th>cost</th></tr><tr><td>push</td><td>O(1)</td></tr>"
    "</table>"
)
CH2 = xhtml("<h1>2. Stacks</h1><div>A stack<span> reverses</span> order.</div>")


@pytest.fixture
def sample(tmp_path: Path) -> Path:
    path = tmp_path / "sample.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("OEBPS/content.opf", OPF)
        archive.writestr("OEBPS/toc.ncx", NCX)
        archive.writestr("OEBPS/Text/mark.xhtml", MARK)
        archive.writestr("OEBPS/Text/ch1.xhtml", CH1)
        archive.writestr("OEBPS/Text/ch2.xhtml", CH2)
    return path


def test_every_bookmark_starts_a_page(sample: Path) -> None:
    marks = book.read_toc(sample)
    assert [(mark.title, mark.level) for mark in marks] == [
        ("1. Queues", 0),
        ("1.1. A ring buffer", 1),
        ("1.2. Locks", 1),
        ("2. Stacks", 0),
    ]
    assert [mark.page for mark in marks] == [1, 2, 3, 4]
    assert book.page_count(sample) == 4
    assert book.page_text(sample, 2, 2).startswith("## 1.1. A ring buffer")
    assert book.page_text(sample, 3, 3).startswith("1.2. Locks")


def test_listing_lines_become_one_block_as_typed(sample: Path) -> None:
    page = book.page_text(sample, 2, 2)
    assert "```\nint next(int i)\n{\n    return (i + 1) % SIZE;\n}\n```" in page
    assert "A caption, not code" in page
    assert "```\nA caption" not in page
    assert "lock(&q);" in book.page_text(sample, 3, 3)


def test_running_text_keeps_exponents_lists_and_tables(sample: Path) -> None:
    assert "2^{10} slots, a power of two." in book.page_text(sample, 2, 2)
    locks = book.page_text(sample, 3, 3)
    assert "- first\n\n- second\n\n  - inner" in locks
    assert "| op | cost |\n| --- | --- |\n| push | O(1) |" in locks
    assert book.page_text(sample, 4, 4) == "# 2. Stacks\n\nA stack reverses order."


def test_a_page_naming_the_buyer_is_left_out(sample: Path) -> None:
    text = book.page_text(sample, 1, book.page_count(sample))
    assert "@" not in text


def _block_texts(body: str) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(xhtml(body), "xml")
    return [block.text for block in epub._blocks(soup.body, "Text/a.xhtml", set())]


def test_a_tip_beside_an_icon_is_a_quote_not_a_table() -> None:
    tip = (
        '<table id="t1"><tbody><tr><td class="ikonka"><img src="i.jpeg"/></td>'
        '<td><p class="uwaga">Keep the interfaces small.</p><p>Really.</p></td>'
        "</tr></tbody></table>"
    )
    assert _block_texts(tip) == ["> Keep the interfaces small.", "> Really."]


def test_a_table_of_one_row_with_two_texts_stays_a_table() -> None:
    row = "<table><tr><td>push</td><td>O(1)</td></tr></table>"
    assert _block_texts(row) == ["| push | O(1) |\n| --- | --- |"]


def test_long_text_is_cut_into_pages_at_paragraphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "EPUB_PAGE_CHARS", 10)
    blocks = [epub.Block("a" * 8), epub.Block("b" * 8), epub.Block("c" * 8)]
    pages, _starts = epub.paginate(blocks, set())
    assert pages == ["a" * 8 + "\n\n" + "b" * 8, "c" * 8]


def test_extract_writes_pages_the_chunker_reads(
    sample: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sample is far smaller than a chunk worth a note.
    monkeypatch.setattr(config, "CHUNK_SKIP_TOKENS", 0)
    epub.extract("bk-epub", sample)
    chunks = chunk_module.plan("bk-epub", sample)
    text = "\n".join(item.text_path.read_text(encoding="utf-8") for item in chunks)
    assert "return (i + 1) % SIZE;" in text
    assert "2. Stacks" in text
