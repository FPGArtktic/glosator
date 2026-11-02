# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Extraction helpers that do not need docling."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app import config, extract


def test_slugify_folds_polish_diacritics() -> None:
    assert extract.slugify("Wtórnik emiterowy") == "wtornik-emiterowy"
    assert extract.slugify("2.3.1 — Emitter Follower!") == "2-3-1-emitter-follower"
    assert extract.slugify("???") == "untitled"


def test_slugify_folds_the_letters_nfkd_leaves_whole() -> None:
    assert extract.slugify("Układy cyfrowe") == "uklady-cyfrowe"
    assert extract.slugify("ŁĄCZNIK") == "lacznik"


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


def test_batches_cover_the_range_without_overlap() -> None:
    assert extract.batches(9, 100, size=40) == [(9, 48), (49, 88), (89, 100)]
    assert extract.batches(5, 5, size=40) == [(5, 5)]


def _fake_child(calls: list[tuple[int, int]]):
    """Stands in for the docling child: one page file and one figure per batch."""

    def run_child(book_slug: str, _pdf: Path, settings: dict) -> dict:
        first, last = settings["pages"]
        calls.append((first, last))
        for page in range(first, last + 1):
            path = extract.page_markdown_path(book_slug, page)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"page {page}\n", encoding="utf-8")
        figure = extract.Figure(
            id=f"fig-{first}-{settings['figure_offset'] + 1}",
            page=first,
            bbox=(0.0, 0.0, 1.0, 1.0),
            caption=f"Figure {first}",
            heading=settings["heading"] or f"heading {first}",
            path=f"figures/fig-{first}.png",
        )
        record = {
            "settings": settings,
            "device": "cpu",
            "ocr_pages": [],
            "figures": [extract.asdict(figure)],
            "last_heading": f"heading {first}",
        }
        batch = extract._batch_path(config.WORK_DIR / book_slug, settings)
        extract._write_json(batch, record)
        return record

    return run_child


def test_run_numbers_figures_through_every_batch(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(config, "EXTRACT_BATCH_PAGES", 2)
    monkeypatch.setattr(extract, "_run_batch_child", _fake_child(calls))

    result = extract.run("bk", Path("/b.pdf"), 1, 5)

    assert calls == [(1, 2), (3, 4), (5, 5)]
    assert [figure.id for figure in result.figures] == [
        "fig-1-1",
        "fig-3-2",
        "fig-5-3",
    ]
    # A batch's first figure belongs to the heading the batch before ended on.
    assert result.figures[1].heading == "heading 1"
    assert "page 3" in result.chapter_files[0].read_text(encoding="utf-8")
    assert len(extract.load_figures("bk")) == 3


def test_run_resumes_from_the_batches_already_done(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(config, "EXTRACT_BATCH_PAGES", 2)
    monkeypatch.setattr(extract, "_run_batch_child", _fake_child(calls))
    extract.run("bk", Path("/b.pdf"), 1, 4)
    calls.clear()

    extract.run("bk", Path("/b.pdf"), 1, 4)
    assert calls == []

    extract.run("bk", Path("/b.pdf"), 1, 4, force=True)
    assert calls == [(1, 2), (3, 4)]


def test_a_batch_made_with_other_settings_is_not_reused(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(config, "EXTRACT_BATCH_PAGES", 2)
    monkeypatch.setattr(extract, "_run_batch_child", _fake_child(calls))
    extract.run("bk", Path("/b.pdf"), 1, 2, ocr_langs="eng")
    calls.clear()

    extract.run("bk", Path("/b.pdf"), 1, 2, ocr_langs="pol")
    assert calls == [(1, 2)]


@pytest.mark.parametrize("setting", ["cpu", "cuda"])
def test_a_forced_device_is_used_as_given(setting: str, monkeypatch) -> None:
    monkeypatch.setattr(extract, "gpu_free_mb", lambda: pytest.fail("asked nvml"))
    assert extract.choose_device(setting)[0] == setting


@pytest.mark.parametrize(
    ("free", "device"),
    [(None, "cpu"), (1000, "cpu"), (config.EXTRACT_MIN_FREE_MB, "cuda")],
)
def test_auto_takes_the_card_only_when_it_is_free(free, device, monkeypatch) -> None:
    monkeypatch.setattr(extract, "gpu_free_mb", lambda: free)
    assert extract.choose_device("auto")[0] == device


def test_a_failed_gpu_conversion_is_redone_on_the_cpu(monkeypatch) -> None:
    devices: list[str] = []

    def convert(_pdf, _first, _last, _langs, _ocr, device, **_options):
        devices.append(device)
        if device == "cuda":
            raise extract.ExtractionIncomplete("Stage layout failed")
        return "document"

    monkeypatch.setattr(extract, "choose_device", lambda: ("cuda", "free"))
    monkeypatch.setattr(extract, "_convert", convert)

    assert extract._convert_on_best_device(Path("/b.pdf"), 1, 2, "eng", False) == (
        "document",
        "cpu",
    )
    assert devices == ["cuda", "cpu"]


def test_a_failed_cpu_conversion_is_not_hidden(monkeypatch) -> None:
    def convert(*_args, **_options):
        raise extract.ExtractionIncomplete("page failed")

    monkeypatch.setattr(extract, "choose_device", lambda: ("cpu", "no card"))
    monkeypatch.setattr(extract, "_convert", convert)
    with pytest.raises(extract.ExtractionIncomplete):
        extract._convert_on_best_device(Path("/b.pdf"), 1, 2, "eng", False)


def test_the_preview_never_touches_the_card(monkeypatch) -> None:
    class Document:
        def export_to_markdown(self, **_options) -> str:
            return "text"

    devices: list[str] = []

    def convert(*args):
        devices.append(args[-1])
        return Document()

    monkeypatch.setattr(extract.pdf, "page_count", lambda _path: 10)
    monkeypatch.setattr(extract, "pages_needing_ocr", lambda *_args: [])
    monkeypatch.setattr(extract, "_convert", convert)
    assert extract.preview(Path("/b.pdf"), 1) == "text"
    assert devices == ["cpu"]


def test_a_failing_child_reports_its_last_words(monkeypatch) -> None:
    class Child:
        returncode = 1

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def communicate(self, timeout: int):
            return b"", b"Traceback\nRuntimeError: CUDA error: no kernel image\n"

    monkeypatch.setattr(subprocess, "Popen", Child)
    settings = extract._batch_settings(1, 2, "eng", 0, "")
    with pytest.raises(RuntimeError, match="no kernel image"):
        extract._run_batch_child("bk", Path("/b.pdf"), settings)


def test_the_child_entry_point_runs_one_batch(monkeypatch) -> None:
    seen: list[tuple] = []
    monkeypatch.setattr(extract, "extract_batch", lambda *args: seen.append(args) or {})
    settings = extract._batch_settings(3, 4, "eng", 0, "")
    code = extract.main(
        ["--book", "bk", "--pdf", "/b.pdf", "--settings", json.dumps(settings)]
    )
    assert code == 0
    assert seen == [("bk", Path("/b.pdf"), settings)]


def test_turning_formulas_off_does_not_reuse_a_batch_made_with_them(
    monkeypatch,
) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(extract, "_run_batch_child", _fake_child(calls))
    monkeypatch.setattr(config, "DOCLING_FORMULAS", True)
    extract.run("bk", Path("/b.pdf"), 1, 2)
    calls.clear()

    monkeypatch.setattr(config, "DOCLING_FORMULAS", False)
    extract.run("bk", Path("/b.pdf"), 1, 2)
    assert calls == [(1, 2)]


def test_compact_tables_strips_cell_padding_and_long_rules() -> None:
    markdown = (
        "Figure 11.4 - Pins.\n\n"
        "| Name      | Type   |\n"
        "|-----------|--------|\n"
        "| RTCC      | Input  |\n"
        "\nText  with  two  spaces stays.\n"
    )
    assert extract.compact_tables(markdown) == (
        "Figure 11.4 - Pins.\n\n"
        "| Name | Type |\n"
        "|---|---|\n"
        "| RTCC | Input |\n"
        "\nText  with  two  spaces stays.\n"
    )


def _picture(caption: str, width_pt: float) -> extract.Figure:
    return extract.Figure(
        id="fig-1-1",
        page=1,
        bbox=(100.0, 500.0, 100.0 + width_pt, 400.0),
        caption=caption,
        heading="",
        path="figures/fig-1-1.png",
    )


def test_a_narrow_uncaptioned_picture_is_a_decoration() -> None:
    # The black "WARNING!" tile beside a callout box: 63 pt, no caption.
    assert extract.is_decoration(_picture("", 63.0))


def test_a_captioned_or_wide_picture_is_a_figure() -> None:
    assert not extract.is_decoration(_picture("Figure 3.2 - Switches.", 63.0))
    assert not extract.is_decoration(_picture("", 95.0))


def _logo(path: Path, shift: int = 0) -> None:
    """A yellow disc beside a block of text, like the LPI logo."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (200, 80), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((5 + shift, 5, 75 + shift, 75), fill="gold")
    draw.rectangle((95 + shift, 20, 190, 30), fill="black")
    draw.rectangle((95 + shift, 45, 170, 55), fill="black")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _diagram(path: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (200, 80), "white")
    ImageDraw.Draw(image).line((0, 79, 199, 0), fill="black", width=6)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _figure_on(page: int, name: str, caption: str = "") -> extract.Figure:
    return extract.Figure(
        id=name,
        page=page,
        bbox=(100.0, 500.0, 300.0, 400.0),
        caption=caption,
        heading="",
        path=f"figures/{name}.png",
    )


def test_a_logo_on_every_lesson_is_dropped(tmp_path: Path) -> None:
    figures = []
    for page in (11, 40, 75):
        figures.append(_figure_on(page, f"logo-{page}"))
        _logo(tmp_path / "figures" / f"logo-{page}.png", shift=page % 3)
    figures.append(_figure_on(41, "diagram"))
    _diagram(tmp_path / "figures" / "diagram.png")

    kept = extract.drop_repeated(figures, tmp_path)

    assert [figure.id for figure in kept] == ["diagram"]


def test_a_picture_on_two_pages_or_with_a_caption_is_kept(tmp_path: Path) -> None:
    figures = [_figure_on(11, "a"), _figure_on(40, "b")]
    figures += [_figure_on(75, "c", caption="Figure 1. The logo")]
    for figure in figures:
        _logo(tmp_path / figure.path)

    kept = extract.drop_repeated(figures, tmp_path)

    assert [figure.id for figure in kept] == ["a", "b", "c"]


def test_repeated_figures_groups_within_the_bit_tolerance() -> None:
    near = 0b111  # three bits from zero
    far = (1 << 40) - 1  # forty bits from zero
    sightings = {
        "x1": _sighting(0, 1),
        "x2": _sighting(near, 50),
        "x3": _sighting(0, 90),
        "y": _sighting(far, 120),
    }
    assert extract.repeated_figures(sightings) == {"x1", "x2", "x3"}


def test_alike_drawings_on_neighbouring_pages_are_kept() -> None:
    # Pinouts of a 74HC00 and a 74HC08 on pages 236-240 of the console book
    # hash two bits apart, but they are figures, not a running logo.
    sightings = {
        "pinout-00": _sighting(0, 236),
        "pinout-08": _sighting(0b11, 237),
        "gates": _sighting(0, 240),
    }
    assert extract.repeated_figures(sightings) == set()


def test_alike_boxes_of_different_sizes_are_kept() -> None:
    # Code listings printed as grey boxes on pages 210, 567 and 721 hash
    # within the tolerance, but each box is as tall as its listing.
    sightings = {
        "listing-a": _sighting(0, 210, height=61.0),
        "listing-b": _sighting(0b1, 567, height=40.0),
        "listing-c": _sighting(0b11, 721, height=41.0),
    }
    assert extract.repeated_figures(sightings) == set()


def _sighting(image: int, page: int, height: float = 70.0) -> extract.Sighting:
    return extract.Sighting(image, page, 197.0, height)


def test_page_markdown_keeps_code_characters_as_printed() -> None:
    pytest.importorskip("docling_core")
    from docling_core.types.doc.document import DoclingDocument
    from docling_core.types.doc.labels import DocItemLabel

    document = DoclingDocument(name="sample")
    document.add_text(
        label=DocItemLabel.TEXT, text="while (left_index < n && *cursor != 0)"
    )
    markdown = extract.page_markdown(document)
    assert "left_index < n && *cursor" in markdown


MARK = "0123456789abcdef0123456789abcdef"


def test_a_digest_on_every_page_is_dropped_wherever_it_landed() -> None:
    pages = [
        f"First sentence. {MARK} Second sentence.",
        f"{MARK} Opening words.",
        f"Closing words.\n\n{MARK}",
    ]
    assert extract.drop_watermarks(pages) == [
        "First sentence. Second sentence.",
        "Opening words.",
        "Closing words.\n\n",
    ]


def test_a_digest_printed_once_stays() -> None:
    pages = [f"The checksum is {MARK}.", "Other text.", "More text."]
    assert extract.drop_watermarks(pages) == pages


def test_dropping_a_watermark_keeps_code_indentation() -> None:
    listing = "```\nint main(void)\n{\n    return 0;\n}\n```"
    pages = [f"{listing}\n{MARK}", MARK, MARK]
    assert extract.drop_watermarks(pages)[0] == f"{listing}\n"
