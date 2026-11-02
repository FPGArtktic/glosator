# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The book file, PDF or EPUB: what chunking and the UI ask of it."""

from __future__ import annotations

from pathlib import Path

from app import epub, pdf
from app.pdf import Bookmark


def page_count(path: Path) -> int:
    return epub.page_count(path) if epub.is_epub(path) else pdf.page_count(path)


def read_toc(path: Path) -> list[Bookmark]:
    return epub.read_toc(path) if epub.is_epub(path) else pdf.read_toc(path)


def page_text(path: Path, first_page: int, last_page: int) -> str:
    if epub.is_epub(path):
        return epub.page_text(path, first_page, last_page)
    return pdf.page_text(path, first_page, last_page)
