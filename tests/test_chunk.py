# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Chunk planning: numbering, page spans, merging, page-range parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import chunk as chunk_module
from app import config, log
from app.chunk import Chunk, Span
from app.pdf import Bookmark


def test_section_number_and_title() -> None:
    assert chunk_module.section_number("2.3.1 Emitter follower") == "2.3.1"
    assert chunk_module.section_title("2.3.1 Emitter follower") == "Emitter follower"
    assert chunk_module.section_number("Appendix A") is None
    assert chunk_module.section_title("Appendix A") == "Appendix A"


def test_span_chapter_comes_from_the_section_number() -> None:
    assert Span("2.3.1 Emitter follower", 2, 71, 74).chapter == 2
    assert Span("11 Oscillators", 0, 500, 540).chapter == 11
    assert Span("pages 1-3", 0, 1, 3).chapter is None


def test_spans_from_bookmarks_fills_page_ranges() -> None:
    bookmarks = [
        Bookmark("2 Transistors", 0, 71),
        Bookmark("2.3 Followers", 1, 73),
        Bookmark("2.3.1 Emitter follower", 2, 74),
        Bookmark("3 Diodes", 0, 90),
    ]
    spans = chunk_module.spans_from_bookmarks(bookmarks, page_count=120)
    assert [(span.page_start, span.page_end) for span in spans] == [
        (71, 72),
        (73, 73),
        (74, 89),
        (90, 120),
    ]


def test_spans_from_bookmarks_never_ends_before_it_starts() -> None:
    bookmarks = [Bookmark("2 A", 0, 71), Bookmark("2.1 B", 1, 71)]
    spans = chunk_module.spans_from_bookmarks(bookmarks, page_count=80)
    assert spans[0] == Span("2 A", 0, 71, 71)


def test_spans_from_bookmarks_filters_by_selection() -> None:
    bookmarks = [Bookmark("2 A", 0, 10), Bookmark("3 B", 0, 20)]
    spans = chunk_module.spans_from_bookmarks(bookmarks, 30, selected=["3 B"])
    assert [span.title for span in spans] == ["3 B"]


def _span(section: str, page: int) -> Span:
    return Span(f"{section} title", 1, page, page)


def test_group_spans_merges_small_sections() -> None:
    spans = [_span("2.1", 1), _span("2.2", 2), _span("2.3", 3)]
    small = config.CHUNK_MIN_TOKENS // 2
    groups = chunk_module.group_spans(spans, [small, small, small])
    assert [[span.section for span in group] for group in groups] == [
        ["2.1", "2.2"],
        ["2.3"],
    ]


def test_group_spans_does_not_merge_across_chapters() -> None:
    spans = [_span("2.9", 1), _span("3.1", 2)]
    small = config.CHUNK_MIN_TOKENS // 2
    groups = chunk_module.group_spans(spans, [small, small])
    assert [[span.section for span in group] for group in groups] == [["2.9"], ["3.1"]]


def test_group_spans_keeps_an_oversized_section_whole() -> None:
    spans = [_span("2.1", 1), _span("2.2", 2)]
    groups = chunk_module.group_spans(
        spans, [config.CHUNK_MAX_TOKENS * 2, config.CHUNK_MIN_TOKENS]
    )
    assert [[span.section for span in group] for group in groups] == [["2.1"], ["2.2"]]


def test_group_spans_flushes_at_the_minimum() -> None:
    spans = [_span("2.1", 1), _span("2.2", 2)]
    groups = chunk_module.group_spans(
        spans, [config.CHUNK_MIN_TOKENS, config.CHUNK_MIN_TOKENS]
    )
    assert len(groups) == 2


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("71-96", [(71, 96)]),
        ("71-96, 100", [(71, 96), (100, 100)]),
        ("1-2\n5-6;9", [(1, 2), (5, 6), (9, 9)]),
        ("  ", []),
    ],
)
def test_parse_page_ranges(text: str, expected: list[tuple[int, int]]) -> None:
    assert chunk_module.parse_page_ranges(text) == expected


@pytest.mark.parametrize("text", ["96-71", "abc", "71-"])
def test_parse_page_ranges_rejects_nonsense(text: str) -> None:
    with pytest.raises(ValueError):
        chunk_module.parse_page_ranges(text)


def _chunk(order: int, chapter: int | None, section: str, title: str) -> Chunk:
    return Chunk(order, chapter, section, title, order, order, Path("x.md"))


def test_chapter_titles_prefers_the_chapter_level_chunk() -> None:
    chunks = [
        _chunk(1, 2, "2.1", "Early section"),
        _chunk(2, 2, "2", "Transistors"),
        _chunk(3, 3, "3.1", "Diodes intro"),
    ]
    # Chapter 3 has no chapter-level chunk, so it stays unnamed rather than
    # being called after its first section.
    assert chunk_module.chapter_titles(chunks) == {2: "Transistors", 3: ""}


def test_plan_writes_text_files_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    pdf_path = Path("/nonexistent/book.pdf")
    bookmarks = [
        Bookmark("2 Transistors", 0, 10),
        Bookmark("2.1 Basics", 1, 11),
    ]
    monkeypatch.setattr(chunk_module.pdf, "page_count", lambda _path: 20)
    monkeypatch.setattr(chunk_module.pdf, "read_toc", lambda _path: bookmarks)
    monkeypatch.setattr(
        chunk_module.pdf, "page_text", lambda _p, first, last: f"text {first}-{last}"
    )

    chunks = chunk_module.plan("bk1", pdf_path)
    assert len(chunks) == 1
    only = chunks[0]
    assert only.section == "2"
    assert only.page_start == 10
    assert only.page_end == 20
    assert "text 10-10" in only.text_path.read_text(encoding="utf-8")
    assert (config.WORK_DIR / "bk1" / chunk_module.CHUNKS_JSON).exists()
    assert chunk_module.load_plan("bk1")[0].section == "2"


def test_plan_without_bookmarks_or_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunk_module.pdf, "page_count", lambda _path: 5)
    monkeypatch.setattr(chunk_module.pdf, "read_toc", lambda _path: [])
    with pytest.raises(ValueError):
        chunk_module.plan("bk1", Path("/nonexistent/book.pdf"))


def test_plan_from_page_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chunk_module.pdf, "page_count", lambda _path: 50)
    monkeypatch.setattr(
        chunk_module.pdf, "page_text", lambda _p, first, last: f"pages {first}-{last}"
    )
    chunks = chunk_module.plan(
        "bk1", Path("/nonexistent/book.pdf"), page_ranges=[(1, 2), (3, 4)]
    )
    assert [chunk.section for chunk in chunks] == ["001", "002"]


def test_outline_problems_on_a_healthy_outline() -> None:
    bookmarks = [
        Bookmark("2 Transistors", 0, 71),
        Bookmark("2.1 Basics", 1, 73),
    ]
    assert chunk_module.outline_problems(bookmarks) == []


def test_outline_problems_reports_a_missing_outline() -> None:
    assert chunk_module.outline_problems([]) == ["the PDF has no bookmarks"]


def test_outline_problems_reports_backwards_destinations() -> None:
    # The shape a damaged outline has in practice: chapter-level bookmarks
    # whose destinations point back at the printed contents pages.
    bookmarks = [
        Bookmark("Ch2: Second chapter", 0, 14),
        Bookmark("Ch3: Third chapter", 0, 3),
        Bookmark("Ch4: Fourth chapter", 0, 3),
        Bookmark("Ch5: Fifth chapter", 0, 213),
    ]
    problems = chunk_module.outline_problems(bookmarks)
    assert any("earlier page" in problem for problem in problems)
    assert any("numbered section" in problem for problem in problems)


def test_spans_step_over_backwards_bookmarks() -> None:
    # A chapter is not collapsed into one page by the broken bookmark that
    # follows it; the broken bookmark itself still yields a useless span,
    # which is what outline_problems warns about.
    bookmarks = [
        Bookmark("Ch2: Second chapter", 0, 14),
        Bookmark("Ch3: Third chapter", 0, 3),
        Bookmark("Ch5: Fifth chapter", 0, 213),
    ]
    spans = chunk_module.spans_from_bookmarks(bookmarks, page_count=1041)
    assert [(span.page_start, span.page_end) for span in spans] == [
        (14, 212),
        (3, 212),
        (213, 1041),
    ]


def test_oversized_reports_chunks_above_the_budget(tmp_path: Path) -> None:
    big = tmp_path / "big.md"
    big.write_text("x" * (config.CHUNK_MAX_TOKENS + 1) * config.CHARS_PER_TOKEN)
    small = tmp_path / "small.md"
    small.write_text("x" * 100)
    chunks = [
        Chunk(1, 2, "2.1", "Big", 1, 30, big),
        Chunk(2, 2, "2.2", "Small", 31, 32, small),
    ]
    assert [chunk.section for chunk in chunk_module.oversized(chunks)] == ["2.1"]


def test_plan_warns_about_an_oversized_page_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chunk_module.pdf, "page_count", lambda _path: 200)
    monkeypatch.setattr(
        chunk_module.pdf,
        "page_text",
        lambda _p, first, last: (
            "x" * (config.CHUNK_MAX_TOKENS + 1) * config.CHARS_PER_TOKEN
        ),
    )
    chunk_module.plan("bk1", Path("/nonexistent/book.pdf"), page_ranges=[(71, 96)])
    assert "over budget" in log.tail()


RUNNING_HEAD_SAMPLE = """SAMPLING AND QUANTISATION
4.07 Limits of the sampling method 212
Figure 4.19. Aliasing of a tone above half the
sampling rate.
amplitude (dB)
120-
4.07 Limits of the sampling method 214
a window of finite length, which is the usual case in practice
"""


def test_running_head_reads_the_section_from_a_page() -> None:
    assert chunk_module.running_head(RUNNING_HEAD_SAMPLE) == (
        "4.07",
        "Limits of the sampling method",
    )


def test_running_head_prefers_the_section_seen_most_often() -> None:
    text = "4.07 Limits 212\n4.08 Examples 215\n4.08 Examples 217\n"
    assert chunk_module.running_head(text) == ("4.08", "Examples")


def test_running_head_ignores_figure_captions_and_body_text() -> None:
    text = "Figure 4.19. Aliasing of a tone\nsee section 4.07 for details\n"
    assert chunk_module.running_head(text) is None
    assert chunk_module.running_head("no numbers here at all") is None


def test_identify_prefers_a_numbered_bookmark() -> None:
    span = Span("2.3.1 Emitter follower", 2, 71, 74)
    assert chunk_module.identify(span, RUNNING_HEAD_SAMPLE, 1) == (
        2,
        "2.3.1",
        "Emitter follower",
    )


def test_identify_falls_back_to_the_running_head() -> None:
    span = Span("pages 99-102", 0, 99, 102)
    assert chunk_module.identify(span, RUNNING_HEAD_SAMPLE, 1) == (
        4,
        "4.07",
        "Limits of the sampling method",
    )


def test_identify_falls_back_to_the_chunk_position() -> None:
    span = Span("pages 99-102", 0, 99, 102)
    assert chunk_module.identify(span, "nothing identifiable", 7) == (
        None,
        "007",
        "pages 99-102",
    )


def test_plan_names_a_page_range_chunk_from_its_running_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(chunk_module.pdf, "page_count", lambda _path: 200)
    monkeypatch.setattr(
        chunk_module.pdf, "page_text", lambda _p, _f, _l: RUNNING_HEAD_SAMPLE
    )
    chunks = chunk_module.plan(
        "bk1", Path("/nonexistent/book.pdf"), page_ranges=[(99, 102)]
    )
    assert (chunks[0].chapter, chunks[0].section, chunks[0].title) == (
        4,
        "4.07",
        "Limits of the sampling method",
    )


def test_running_head_survives_crlf_line_endings() -> None:
    # pdfium returns whatever line endings the PDF carries, CRLF for the first
    # book tested; the carriage return used to end up inside the note title.
    text = "SAMPLING \r\n4.07 Limits of the sampling method 212 \r\nbody\r\n"
    assert chunk_module.running_head(text) == ("4.07", "Limits of the sampling method")
