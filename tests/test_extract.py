# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Extraction helpers that do not need docling."""

from __future__ import annotations

import pytest

from app import extract


def test_slugify_folds_polish_diacritics() -> None:
    assert extract.slugify("Wtórnik emiterowy") == "wtornik-emiterowy"
    assert extract.slugify("2.3.1 — Emitter Follower!") == "2-3-1-emitter-follower"
    assert extract.slugify("???") == "untitled"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("2 Transistors", 2),
        ("Chapter 11 Oscillators", 11),
        ("Rozdział 3 Wzmacniacze", 3),
        ("Appendix A", None),
    ],
)
def test_chapter_number(title: str, expected: int | None) -> None:
    assert extract.chapter_number(title) == expected


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("3 Sampling", True),
        ("Chapter 3", True),
        ("Rozdział 11 Mikroprocesory", True),
        ("4.07 Limits of the sampling method", False),
        ("EXERCISE 4.3", False),
        ("Remarks", False),
        ("Figure 4.19", False),
    ],
)
def test_is_chapter_heading(title: str, expected: bool) -> None:
    assert extract.is_chapter_heading(title) is expected


def test_split_markdown_by_chapter() -> None:
    markdown = (
        "front matter\n\n## 3 Sampling\n\ntext\n\n"
        "### 3.12 Windows\n\nmore\n\n## 4 Filters\n\ntail"
    )
    sections = extract.split_markdown_by_chapter(markdown)
    assert [title for title, _ in sections] == ["", "3 Sampling", "4 Filters"]
    assert "### 3.12 Windows" in sections[1][1]
    assert sections[2][1].endswith("tail")


def test_split_markdown_by_chapter_on_a_mid_chapter_page_range() -> None:
    # What a four-page range in the middle of a chapter produces: paragraph
    # headings, which docling gives the same level as a chapter title.
    markdown = "## Remarks\n\ntext\n\n## EXERCISE 4.3\n\nmore\n"
    assert extract.split_markdown_by_chapter(markdown) == []
    assert extract.split_markdown_by_chapter("no headings at all") == []


def test_slice_section_stops_at_same_level() -> None:
    markdown = (
        "# 2 Transistors\n\nintro\n\n"
        "## 2.3.1 Emitter follower\n\nbody\n\n"
        "### Detail\n\ndeep\n\n"
        "## 2.3.2 Next\n\nother\n"
    )
    sliced = extract.slice_section(markdown, "2.3.1 Emitter follower")
    assert sliced is not None
    assert "deep" in sliced
    assert "other" not in sliced


def test_slice_section_is_whitespace_and_case_tolerant() -> None:
    markdown = "## 2.3.1  Emitter   follower\n\nbody\n"
    assert extract.slice_section(markdown, "2.3.1 emitter follower") is not None
    assert extract.slice_section(markdown, "2.3.2 Missing") is None


def test_bbox_to_pixels_bottom_left_origin() -> None:
    # A4-ish page, 100 pt tall box 72 pt from the bottom, 72 dpi, no padding.
    box = extract.bbox_to_pixels((72.0, 172.0, 144.0, 72.0), 792.0, dpi=72, pad_pt=0.0)
    assert box == (72, 620, 144, 720)


def test_bbox_to_pixels_top_left_origin_and_padding() -> None:
    box = extract.bbox_to_pixels(
        (100.0, 100.0, 200.0, 300.0),
        792.0,
        dpi=144,
        pad_pt=10.0,
        origin_bottom_left=False,
    )
    assert box == (180, 180, 420, 620)


def test_load_figures_without_file(tmp_path) -> None:
    assert extract.load_figures("missing-book") == []
