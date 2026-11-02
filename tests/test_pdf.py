# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

from app import book, pdf


def _blank_pdf(path: Path, sizes: list[tuple[float, float]]) -> Path:
    document = pdfium.PdfDocument.new()
    for width, height in sizes:
        document.new_page(width, height)
    document.save(path)
    return path


def test_landscape_pages_are_a_slide_deck(tmp_path: Path) -> None:
    slides = _blank_pdf(tmp_path / "slides.pdf", [(720, 405)] * 9 + [(595, 842)])
    assert pdf.is_slide_deck(slides)
    assert book.is_slide_deck(slides)


def test_upright_pages_are_a_book(tmp_path: Path) -> None:
    pages = _blank_pdf(tmp_path / "book.pdf", [(595, 842)] * 8 + [(842, 595)] * 2)
    assert not pdf.is_slide_deck(pages)


def test_a_missing_file_is_no_slide_deck(tmp_path: Path) -> None:
    assert not book.is_slide_deck(tmp_path / "missing.pdf")
