# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Low-level PDF access: page count, raw text, bookmarks, page rendering.

pypdfium2 only (BSD/Apache). docling owns the structured extraction; this
module answers the cheap questions that extraction and chunking both ask.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium

from app import config

POINTS_PER_INCH = 72.0


@dataclass(frozen=True)
class Bookmark:
    """A PDF outline entry. ``page`` is 1-indexed, ``level`` starts at 0."""

    title: str
    level: int
    page: int


def page_count(pdf_path: Path) -> int:
    with _document(pdf_path) as pdf:
        return len(pdf)


def read_toc(pdf_path: Path) -> list[Bookmark]:
    """Bookmarks in document order. Empty list when the PDF has no outline.

    A bookmark whose destination does not resolve to a page is dropped: it
    cannot be given a page range, and a chunk without pages is useless.
    """
    with _document(pdf_path) as pdf:
        marks = []
        for item in pdf.get_toc():
            page = _bookmark_page(item)
            title = (item.get_title() or "").strip()
            if page is not None and title:
                marks.append(Bookmark(title=title, level=item.level, page=page))
        return marks


def _bookmark_page(bookmark) -> int | None:
    destination = bookmark.get_dest()
    if destination is None:
        return None
    index = destination.get_index()
    return None if index is None else index + 1


def page_text(pdf_path: Path, first_page: int, last_page: int) -> str:
    """Text layer of an inclusive, 1-indexed page range."""
    with _document(pdf_path) as pdf:
        return "\n\n".join(_page_texts(pdf, range(first_page, last_page + 1)))


def page_char_counts(pdf_path: Path, pages: Iterable[int]) -> dict[int, int]:
    """Extractable characters per page, used to decide whether OCR is needed."""
    with _document(pdf_path) as pdf:
        wanted = list(pages)
        texts = _page_texts(pdf, wanted)
        return dict(zip(wanted, (len(text.strip()) for text in texts), strict=True))


def page_height_pt(pdf_path: Path, page: int) -> float:
    with _document(pdf_path) as pdf:
        return float(pdf[page - 1].get_height())


def render_page(pdf_path: Path, page: int, dpi: int = config.FIGURE_DPI):
    """Render one 1-indexed page to a PIL image."""
    with _document(pdf_path) as pdf:
        scale = dpi / POINTS_PER_INCH
        return pdf[page - 1].render(scale=scale).to_pil()


def _page_texts(pdf: pdfium.PdfDocument, pages: Iterable[int]) -> Iterator[str]:
    for number in pages:
        page = pdf[number - 1]
        textpage = page.get_textpage()
        try:
            # pdfium hands back the line endings the PDF carries, CRLF here.
            # A stray carriage return breaks every line-anchored pattern that
            # reads this text, so the normalisation belongs at the source.
            yield textpage.get_text_bounded().replace("\r\n", "\n").replace("\r", "\n")
        finally:
            textpage.close()
            page.close()


class _document:
    """Context manager so no run leaks pdfium handles over a 30-hour job."""

    def __init__(self, pdf_path: Path) -> None:
        self._path = Path(pdf_path)

    def __enter__(self) -> pdfium.PdfDocument:
        self._pdf = pdfium.PdfDocument(self._path)
        return self._pdf

    def __exit__(self, *_exc: object) -> None:
        self._pdf.close()
