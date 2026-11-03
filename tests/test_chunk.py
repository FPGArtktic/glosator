# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Chunk planning: numbering, page spans, merging, page-range parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import chunk as chunk_module
from app import config, extract, log, pdf
from app.chunk import Chunk, Span
from app.pdf import Bookmark


@pytest.fixture(autouse=True)
def no_outline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Page-range plans read the outline for chapters; the test PDFs have none."""
    monkeypatch.setattr(pdf, "read_toc", lambda _path: [])


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
    assert spans[0] == Span("2 A", 0, 71, 71, outline_chapter=2)


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
    monkeypatch.setattr(pdf, "page_count", lambda _path: 20)
    monkeypatch.setattr(pdf, "read_toc", lambda _path: bookmarks)
    monkeypatch.setattr(
        pdf,
        "page_text",
        lambda _p, first, last: f"text {first}-{last} " + "x" * 400,
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
    monkeypatch.setattr(pdf, "page_count", lambda _path: 5)
    monkeypatch.setattr(pdf, "read_toc", lambda _path: [])
    with pytest.raises(ValueError):
        chunk_module.plan("bk1", Path("/nonexistent/book.pdf"))


def test_plan_from_page_ranges(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pdf, "page_count", lambda _path: 50)
    monkeypatch.setattr(
        pdf, "page_text", lambda _p, first, last: f"pages {first}-{last}"
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
    monkeypatch.setattr(pdf, "page_count", lambda _path: 200)
    monkeypatch.setattr(
        pdf,
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


def test_running_head_skips_a_contents_entry() -> None:
    # A chapter's own contents page, as the second book tested prints it.
    text = (
        "   1.1 Introduction to Digital and Analog Electronics ........... 8\n"
        "1.4 Current & Voltage\n"
    )
    assert chunk_module.running_head(text) == ("1.4", "Current & Voltage")


def test_running_head_skips_a_sentence_wrapped_after_a_figure_number() -> None:
    text = "as Figure\n6.3 shows an excerpt from the TI 74HC164 chip\n"
    assert chunk_module.running_head(text) is None


def test_running_head_skips_a_line_wrapped_inside_a_caption() -> None:
    text = "Figure\n9.29 (with highlighting on changed pins)\n"
    assert chunk_module.running_head(text) is None


def test_running_head_skips_a_number_from_another_chapter() -> None:
    text = "0.25 - 0.3V and finally the signal\n9.6 Video\n"
    assert chunk_module.running_head(text, chapter=9) == ("9.6", "Video")


def test_headings_are_listed_in_page_order() -> None:
    text = "1.4 Current & Voltage\nbody\n1.5 Units\nbody\n1.6 Power\n"
    assert [number for number, _title in chunk_module.headings(text)] == [
        "1.4",
        "1.5",
        "1.6",
    ]


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
    monkeypatch.setattr(pdf, "page_count", lambda _path: 200)
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: RUNNING_HEAD_SAMPLE)
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


def test_split_to_budget_leaves_a_small_range_alone(monkeypatch) -> None:
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: "x" * 400)
    assert chunk_module.split_to_budget(Path("/b.pdf"), 13, 16) == [(13, 16)]


def test_split_to_budget_cuts_a_long_range_at_page_boundaries(monkeypatch) -> None:
    # Every page is a third of the budget less the joins, so three pages fit
    # and the fourth starts a new slice.
    page = "x" * (config.CHUNK_MAX_TOKENS // 3 * config.CHARS_PER_TOKEN - 8)
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: page)
    assert chunk_module.split_to_budget(Path("/b.pdf"), 1, 7) == [
        (1, 3),
        (4, 6),
        (7, 7),
    ]


def test_split_to_budget_keeps_an_oversized_page_whole(monkeypatch) -> None:
    page = "x" * ((config.CHUNK_MAX_TOKENS + 1) * config.CHARS_PER_TOKEN)
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: page)
    assert chunk_module.split_to_budget(Path("/b.pdf"), 5, 6) == [(5, 5), (6, 6)]


def test_title_offset_ignores_punctuation_and_spacing() -> None:
    page = "end of 1.7\n\n## 1.8. Values - passed by copy\n\nbody\n"
    offset = chunk_module.title_offset(page, "1.8.Values \u2014 passed by copy")
    assert offset is not None
    assert page[offset:].startswith("## 1.8.")


def test_title_offset_accepts_a_chapter_title_cut_in_two() -> None:
    page = "## Chapter 5.\n\n## LOOPS AND BRANCHES\n\ntext\n"
    assert chunk_module.title_offset(page, "Chapter 5. Loops and branches") == 0


def test_title_offset_finds_a_title_numbered_its_own_way_on_the_page() -> None:
    page = "## 0.12 Interrupts\n\ntop half\n\n## 0.13 Memory split\n\nbody\n"
    offset = chunk_module.title_offset(page, "13 Memory split")
    assert page[offset:].startswith("## 0.13 Memory split")
    page = "Board setup steps.\n\nMore guidelines\n\nRead the manual first.\n"
    offset = chunk_module.title_offset(page, "1.4 More guidelines")
    assert page[offset:].startswith("More guidelines")
    assert chunk_module.title_offset(page, "1.5 Kernel sources") is None


def test_title_offset_prefers_a_whole_heading_to_a_prefix() -> None:
    page = "## Pointers\n\nintro\n\n## Pointers and arrays\n\nbody\n"
    offset = chunk_module.title_offset(page, "Pointers and arrays")
    assert page[offset:].startswith("## Pointers and arrays")


def test_title_offset_finds_a_plain_line_of_the_text_layer() -> None:
    page = "the end of the last section.\n3.2 Branches\nnew text\n"
    assert chunk_module.title_offset(page, "3.2. Branches") == page.index("3.2")


def _pages(monkeypatch: pytest.MonkeyPatch, pages: dict[int, str]) -> None:
    monkeypatch.setattr(pdf, "page_text", lambda _p, first, _last: pages[first])


def test_bookmark_parts_reads_past_a_heading_the_outline_lacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every heading on the page has the same level, as docling writes them;
    # "4.11.1" is not a bookmark and must not end "4.11".
    _pages(
        monkeypatch,
        {
            7: "tail of 4.10\n\n## 4.11 Macros\n\nopening\n\n"
            "## 4.11.1 Include\n\nmiddle",
            8: "more of 4.11\n\n## 5 Pointers\n\nnext chapter",
        },
    )
    bookmarks = [
        Bookmark("4.10 Recursion", 1, 6),
        Bookmark("4.11 Macros", 1, 7),
        Bookmark("5 Pointers", 0, 8),
    ]
    spans = chunk_module.spans_from_bookmarks(bookmarks, page_count=8)
    sizes = chunk_module.note_budget()
    parts = chunk_module.bookmark_parts(
        Path("/b.pdf"), bookmarks, spans[1:2], sizes, "bk1"
    )
    [(span, text)] = parts
    assert text.startswith("## 4.11 Macros")
    assert "middle" in text
    assert "more of 4.11" in text
    assert "tail of 4.10" not in text
    assert "next chapter" not in text
    assert (span.page_start, span.page_end) == (7, 8)


def test_bookmark_parts_leaves_a_page_without_the_next_title_to_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pages(monkeypatch, {3: "## 1 Start\n\nbody", 4: "heading lost by docling"})
    bookmarks = [Bookmark("1 Start", 0, 3), Bookmark("2 Next", 0, 4)]
    spans = chunk_module.spans_from_bookmarks(bookmarks, page_count=4)
    sizes = chunk_module.note_budget()
    [(span, text)] = chunk_module.bookmark_parts(
        Path("/b.pdf"), bookmarks, spans[:1], sizes, "bk1"
    )
    assert "lost" not in text
    assert (span.page_start, span.page_end) == (3, 3)


def test_bookmark_parts_cuts_a_long_section_by_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sizes = chunk_module.note_budget()
    filler = "x" * (sizes.max_tokens // 3 * config.CHARS_PER_TOKEN)
    _pages(monkeypatch, {page: f"page {page} {filler}" for page in range(1, 7)})
    bookmarks = [Bookmark("A.7 Expressions", 1, 1)]
    spans = chunk_module.spans_from_bookmarks(bookmarks, page_count=6)
    parts = chunk_module.bookmark_parts(Path("/b.pdf"), bookmarks, spans, sizes, "bk1")
    assert len(parts) > 1
    assert {span.title for span, _text in parts} == {"A.7 Expressions"}
    assert parts[0][0].page_start == 1
    assert parts[-1][0].page_end == 6
    assert all(
        chunk_module.estimate_tokens(text) <= sizes.max_tokens for _span, text in parts
    )


def test_plan_cuts_a_forty_page_range_into_readable_chunks(monkeypatch) -> None:
    # What pressing "Run everything" on pages 13-56 actually produced: one
    # chunk of 28607 tokens, which the generate stage refused.
    page = "x" * (650 * config.CHARS_PER_TOKEN)
    monkeypatch.setattr(pdf, "page_count", lambda _path: 200)
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: page)

    chunks = chunk_module.plan("bk1", Path("/b.pdf"), page_ranges=[(13, 56)])

    assert len(chunks) > 1
    assert chunk_module.oversized(chunks) == []
    assert chunks[0].page_start == 13
    assert chunks[-1].page_end == 56


def test_running_head_reunites_a_section_number_split_by_ocr() -> None:
    # The first book tested prints "2.11" as "2.1 1" on some pages, which put
    # the stray digit into the note's title and into every link to it.
    head = "2.1 1 The emitter follower revisited"
    text = f"{head} 72\n{head} 74\n"
    assert chunk_module.running_head(text) == ("2.11", "The emitter follower revisited")


def test_running_head_leaves_a_title_that_really_starts_with_a_number() -> None:
    text = "3.5 2N3904 characteristics 88\n3.5 2N3904 characteristics 90\n"
    assert chunk_module.running_head(text) == ("3.5", "2N3904 characteristics")


def test_running_head_does_not_glue_onto_a_two_decimal_number() -> None:
    text = "2.11 1 of 3 approaches 72\n2.11 1 of 3 approaches 74\n"
    assert chunk_module.running_head(text)[0] == "2.11"


def test_the_two_budgets_write_to_separate_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither pass may land on the other's plan: both are kept side by side."""
    bookmarks = [Bookmark("2 Transistors", 0, 10), Bookmark("2.1 Basics", 1, 11)]
    monkeypatch.setattr(pdf, "page_count", lambda _path: 20)
    monkeypatch.setattr(pdf, "read_toc", lambda _path: bookmarks)
    monkeypatch.setattr(
        pdf,
        "page_text",
        lambda _p, first, last: f"text {first}-{last} " + "x" * 400,
    )
    pdf_path = Path("/nonexistent/book.pdf")

    chunk_module.plan("bk1", pdf_path)
    notes_manifest = config.WORK_DIR / "bk1" / chunk_module.CHUNKS_JSON
    before = notes_manifest.read_bytes()

    exported = chunk_module.plan("bk1", pdf_path, budget=chunk_module.export_budget())

    assert notes_manifest.read_bytes() == before
    assert (config.WORK_DIR / "bk1" / chunk_module.EXPORT_CHUNKS_JSON).exists()
    assert exported[0].text_path.parent.name == "chunks-export"
    assert (config.WORK_DIR / "bk1" / "chunks").is_dir()


def test_load_plan_reads_the_plan_of_the_budget_it_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf, "page_count", lambda _path: 20)
    monkeypatch.setattr(pdf, "read_toc", lambda _path: [])
    monkeypatch.setattr(
        pdf,
        "page_text",
        lambda _p, first, last: f"text {first}-{last} " + "x" * 400,
    )
    pdf_path = Path("/nonexistent/book.pdf")
    chunk_module.plan("bk1", pdf_path, page_ranges=[(1, 2)])
    chunk_module.plan(
        "bk1", pdf_path, page_ranges=[(5, 6)], budget=chunk_module.export_budget()
    )

    assert chunk_module.load_plan("bk1")[0].page_start == 1
    exported = chunk_module.load_plan("bk1", budget=chunk_module.export_budget())
    assert exported[0].page_start == 5


def test_the_export_budget_merges_further_than_the_note_budget() -> None:
    """The point of the second budget: fewer files, each holding more."""
    spans = [_span(f"2.{number}", number) for number in range(1, 9)]
    sizes = [config.CHUNK_MIN_TOKENS // 2] * 8

    for_notes = chunk_module.group_spans(spans, sizes)
    for_export = chunk_module.group_spans(
        spans, sizes, budget=chunk_module.export_budget()
    )

    assert len(for_notes) == 4
    assert len(for_export) == 1


def test_split_to_budget_honours_a_larger_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = "x" * (config.CHUNK_MAX_TOKENS * config.CHARS_PER_TOKEN - 8)
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: page)
    pdf_path = Path("/nonexistent/book.pdf")

    assert len(chunk_module.split_to_budget(pdf_path, 1, 3)) == 3
    assert (
        len(
            chunk_module.split_to_budget(
                pdf_path, 1, 3, max_tokens=config.CHUNK_MAX_TOKENS * 3
            )
        )
        == 1
    )


CONTENTS_PAGE = "\n".join(
    f"   1.{index} Section number {index} " + "." * 40 + f" {index * 3}"
    for index in range(1, 9)
)


def test_a_contents_page_is_recognised() -> None:
    assert chunk_module.is_contents_page(CONTENTS_PAGE)
    assert not chunk_module.is_contents_page(RUNNING_HEAD_SAMPLE)


def test_the_short_last_page_of_a_contents_is_recognised() -> None:
    page = (
        "Design Your Own Video Game Console\n"
        "11.9.3 Switching Schemes and Added Features Via Cartridge"
        + "." * 60
        + " 829\n7\n"
    )
    assert chunk_module.is_contents_page(page)


def test_one_dotted_line_on_a_page_of_text_is_not_a_contents() -> None:
    page = "body text " * 100 + "\nTotal " + "." * 10 + " 42\n"
    assert not chunk_module.is_contents_page(page)


def test_readable_text_leaves_out_contents_pages(monkeypatch) -> None:
    pages = {1: CONTENTS_PAGE, 2: "1.1 Analog Electronics\nbody text"}
    monkeypatch.setattr(pdf, "page_text", lambda _p, first, _last: pages[first])
    assert chunk_module.readable_text(Path("/b.pdf"), 1, 2) == pages[2]


def test_outline_chapter_is_the_last_chapter_bookmark_before_the_page() -> None:
    bookmarks = [
        Bookmark("Chapter 1 - Introduction to Electronics", 0, 1),
        Bookmark("1: Table of Contents", 1, 9),
        Bookmark("Chapter 2 - Basic Analog Circuit Analysis", 0, 72),
    ]
    assert chunk_module.outline_chapter(bookmarks, 40) == 1
    assert chunk_module.outline_chapter(bookmarks, 72) == 2
    assert chunk_module.outline_chapter([], 40) is None


def test_a_page_range_span_takes_its_chapter_from_the_outline() -> None:
    assert Span("pages 80-90", 0, 80, 90, outline_chapter=2).chapter == 2


def test_identify_continues_the_previous_head() -> None:
    span = Span("pages 30-41", 0, 30, 41, outline_chapter=1)
    assert chunk_module.identify(span, "body only", 4, ("1.7", "Resistors")) == (
        1,
        "1.7",
        "Resistors (continued)",
    )


def test_identify_does_not_carry_a_head_into_another_chapter() -> None:
    span = Span("pages 80-90", 0, 80, 90, outline_chapter=2)
    assert chunk_module.identify(span, "body only", 9, ("1.9", "Summary")) == (
        2,
        "009",
        "pages 80-90",
    )


def test_plan_names_a_headless_chunk_after_the_section_it_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {1: "1.6 Power\nbody", 2: "1.7 Resistors\nbody", 3: "more body"}
    page = "x" * (config.CHUNK_MAX_TOKENS // 2 * config.CHARS_PER_TOKEN)
    monkeypatch.setattr(pdf, "page_count", lambda _path: 3)
    monkeypatch.setattr(
        pdf,
        "page_text",
        lambda _p, first, _last: pages[first] + "\n" + page,
    )
    chunks = chunk_module.plan(
        "bk1", Path("/nonexistent/book.pdf"), page_ranges=[(1, 3)]
    )
    # Every page is half the budget, so each one is a chunk of its own.
    assert [(chunk.section, chunk.title) for chunk in chunks] == [
        ("1.6", "Power"),
        ("1.7", "Resistors"),
        ("1.7-2", "Resistors (continued)"),
    ]


def test_readable_text_prefers_the_page_docling_extracted(monkeypatch) -> None:
    layer = {1: "In this case,\n", 2: "text layer two"}
    monkeypatch.setattr(pdf, "page_text", lambda _p, first, _last: layer[first])
    path = extract.page_markdown_path("bk1", 1)
    path.parent.mkdir(parents=True)
    path.write_text("In this case,\n\n$$V_{BE} < 0.6$$\n", encoding="utf-8")

    text = chunk_module.readable_text(Path("/b.pdf"), 1, 2, "bk1")
    assert text == "In this case,\n\n$$V_{BE} < 0.6$$\n\ntext layer two"


def test_readable_text_drops_a_contents_page_docling_made_a_table(
    monkeypatch,
) -> None:
    monkeypatch.setattr(pdf, "page_text", lambda _p, _first, _last: CONTENTS_PAGE)
    path = extract.page_markdown_path("bk1", 1)
    path.parent.mkdir(parents=True)
    path.write_text("| 1.1 | Section | 3 |\n", encoding="utf-8")
    assert chunk_module.readable_text(Path("/b.pdf"), 1, 1, "bk1") == ""


def test_running_head_reads_a_markdown_heading() -> None:
    assert chunk_module.running_head("## 1.4 Current & Voltage\nbody") == (
        "1.4",
        "Current & Voltage",
    )


def test_split_to_budget_counts_the_separators_between_pages(monkeypatch) -> None:
    # Three pages that fit only if the joins are left out of the count.
    page = "x" * (config.CHUNK_MAX_TOKENS * config.CHARS_PER_TOKEN // 3)
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: page)
    slices = chunk_module.split_to_budget(Path("/b.pdf"), 1, 3)
    for first, last in slices:
        joined = chunk_module.readable_text(Path("/b.pdf"), first, last)
        assert chunk_module.estimate_tokens(joined) <= config.CHUNK_MAX_TOKENS


def test_split_to_budget_ends_a_slice_where_a_section_starts(monkeypatch) -> None:
    # Pages of a quarter of the budget: past the minimum after two pages, the
    # slice ends before the page that opens 1.5 instead of running to four.
    body = "x" * (config.CHUNK_MAX_TOKENS * config.CHARS_PER_TOKEN // 4 - 40)
    pages = {
        1: "1.4 Current\n" + body,
        2: body,
        3: body,
        4: "1.5 Units\n" + body,
        5: body,
    }
    monkeypatch.setattr(pdf, "page_text", lambda _p, first, _last: pages[first])
    slices = chunk_module.split_to_budget(
        Path("/b.pdf"), 1, 5, min_tokens=config.CHUNK_MAX_TOKENS // 2
    )
    assert slices == [(1, 3), (4, 5)]


def test_a_heading_from_docling_loses_its_html_escapes() -> None:
    assert chunk_module.running_head("## 1.4 Current &amp; Voltage\n") == (
        "1.4",
        "Current & Voltage",
    )


LPI_OUTLINE = [
    Bookmark("Learning Materials: LPIC-1 (101)", 0, 1),
    Bookmark("Topic 101: System Architecture", 0, 11),
    Bookmark("101.1 Determine and configure hardware settings", 1, 12),
    Bookmark("101.1 Lesson 1", 2, 13),
    Bookmark("Introduction", 3, 13),
    Bookmark("Guided Exercises", 3, 24),
    Bookmark("101.1 Lesson 2", 2, 26),
    Bookmark("Introduction", 3, 26),
    Bookmark("101.2 Boot the system", 1, 29),
    Bookmark("101.2 Lesson 1", 2, 30),
    Bookmark("Introduction", 3, 30),
]


def test_an_outline_with_unnumbered_children_of_sections_is_deep() -> None:
    assert chunk_module.is_deep_outline(LPI_OUTLINE)
    shallow = [
        Bookmark("2 Transistors", 0, 10),
        Bookmark("2.1 Basics", 1, 11),
        Bookmark("Appendix A", 0, 90),
    ]
    assert not chunk_module.is_deep_outline(shallow)


def test_section_ranges_give_each_section_its_children_and_its_own_title() -> None:
    assert chunk_module.section_ranges(LPI_OUTLINE, 44) == [
        ("Learning Materials: LPIC-1 (101)", 1, 11),
        ("101.1 Determine and configure hardware settings", 12, 28),
        ("101.2 Boot the system", 29, 44),
    ]


def test_balanced_split_keeps_the_count_and_evens_the_slices(monkeypatch) -> None:
    # Eleven pages a tenth of the budget each: greedy cuts 10 + 1 pages,
    # balanced cuts the same two slices of five and six.
    page = "x" * (config.CHUNK_MAX_TOKENS * config.CHARS_PER_TOKEN // 10 - 8)
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: page)
    slices = chunk_module.balanced_split(
        Path("/b.pdf"), 1, 11, chunk_module.note_budget(), "bk1"
    )
    assert len(slices) == 2
    sizes = [last - first + 1 for first, last in slices]
    assert max(sizes) - min(sizes) <= 1


def test_plan_of_a_deep_outline_names_every_part_after_its_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = "x" * (config.CHUNK_MAX_TOKENS * config.CHARS_PER_TOKEN // 8)
    monkeypatch.setattr(pdf, "page_count", lambda _path: 44)
    monkeypatch.setattr(pdf, "read_toc", lambda _path: LPI_OUTLINE)
    # Pages 1-11 are the title page and the topic page: a line each.
    monkeypatch.setattr(
        pdf,
        "page_text",
        lambda _p, first, _last: "Topic 101" if first <= 11 else page,
    )
    chunks = chunk_module.plan("bk1", Path("/nonexistent/book.pdf"))

    titles = [(chunk.section, chunk.title) for chunk in chunks]
    assert titles[0] == ("101.1", "Determine and configure hardware settings")
    assert titles[1] == (
        "101.1-2",
        "Determine and configure hardware settings (continued)",
    )
    assert ("101.2", "Boot the system") in titles
    # The title page and the topic page hold no section and make no note.
    assert all("Learning Materials" not in title for _section, title in titles)


def test_a_programming_book_is_cut_into_smaller_chunks() -> None:
    listings = chunk_module.note_budget(listings=True)
    prose = chunk_module.note_budget()
    assert listings.max_tokens < prose.max_tokens
    assert listings.manifest == prose.manifest


def test_an_unnumbered_section_takes_the_chapter_it_stands_under() -> None:
    bookmarks = [
        Bookmark("Preface", 0, 9),
        Bookmark("Why this book", 1, 9),
        Bookmark("Chapter 1. Introduction", 0, 15),
        Bookmark("Memory and addresses", 1, 16),
        Bookmark("Chapter 2. Allocation", 0, 51),
        Bookmark("Freeing memory", 1, 52),
    ]
    spans = chunk_module.spans_from_bookmarks(bookmarks, page_count=60)
    assert [span.chapter for span in spans] == [None, None, 1, 1, 2, 2]


def test_an_appendix_after_the_last_chapter_is_not_part_of_it() -> None:
    bookmarks = [
        Bookmark("Chapter 8. Odds and ends", 0, 200),
        Bookmark("Appendix A. Answers", 0, 230),
        Bookmark("Index", 0, 250),
    ]
    assert chunk_module.outline_chapter(bookmarks, 210) == 8
    assert chunk_module.outline_chapter(bookmarks, 235) is None


def test_readable_text_keeps_a_blank_extracted_page_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf, "page_text", lambda _p, first, _l: f"Footer {first} 0f1e")
    path = extract.page_markdown_path("bk1", 2)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n", encoding="utf-8")
    assert chunk_module.readable_text(Path("/b.pdf"), 1, 2, "bk1") == "Footer 1 0f1e"


def test_plan_leaves_out_the_contents_and_the_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bookmarks = [
        Bookmark("Spis treści", 0, 1),
        Bookmark("1 Start", 0, 3),
        Bookmark("Index", 0, 9),
    ]
    monkeypatch.setattr(pdf, "page_count", lambda _path: 10)
    monkeypatch.setattr(pdf, "read_toc", lambda _path: bookmarks)
    monkeypatch.setattr(
        pdf, "page_text", lambda _p, first, _l: f"page {first} " + "x" * 400
    )
    chunks = chunk_module.plan("bk1", Path("/nonexistent/book.pdf"))
    assert [item.title for item in chunks] == ["Start"]
    assert (chunks[0].page_start, chunks[0].page_end) == (3, 8)


def test_a_bibliography_section_is_left_out() -> None:
    assert chunk_module.is_apparatus("13.2 BIBLIOGRAFIA W PORZĄDKU ALFABETYCZNYM")
    assert chunk_module.is_apparatus("Bibliography and further reading")
    assert chunk_module.is_apparatus("Index")
    assert not chunk_module.is_apparatus("13.1 Sugerowane publikacje dodatkowe")
    assert not chunk_module.is_apparatus("7.7 References and pointers")


def test_a_publishers_front_and_back_matter_is_left_out() -> None:
    for title in ("Cover", "Title Page", "Copyright and Credits", "Dedication"):
        assert chunk_module.is_apparatus(title)
    assert chunk_module.is_apparatus("Other Books You May Enjoy")
    assert not chunk_module.is_apparatus("Preface")
    assert not chunk_module.is_apparatus("3.4 Cover letters and title pages")


def test_a_bookmark_takes_the_spelling_of_its_page() -> None:
    page = "## 2.4.3. Obsługa błędów\n\nObsługa błędów to temat obszerny."
    assert chunk_module.spelled_as_printed("2.4.3. Obsł uga bł ędów", page) == (
        "2.4.3. Obsługa błędów"
    )
    assert chunk_module.spelled_as_printed("Stał e", "## STAŁE\n") == "Stałe"
    assert chunk_module.spelled_as_printed(
        "Rozdział 1. Uwagi", "Rozdział 1. Uwagi"
    ) == ("Rozdział 1. Uwagi")
    assert chunk_module.spelled_as_printed("Stał e", "nothing like it") == "Stał e"


def test_plan_names_a_chunk_as_its_page_spells_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pdf, "page_count", lambda _path: 10)
    monkeypatch.setattr(pdf, "read_toc", lambda _path: [Bookmark("1 Stał e", 0, 1)])
    monkeypatch.setattr(pdf, "page_text", lambda _p, first, _l: "1 Stałe\n" + "x" * 400)
    chunks = chunk_module.plan("bk1", Path("/nonexistent/book.pdf"))
    assert [item.title for item in chunks] == ["Stałe"]


def test_a_section_cut_inside_a_code_block_keeps_its_fences_paired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = (
        "1 Alpha\nWe declare it:\n```\nint a;\n2 Beta\nThen we use it:\n"
        "a = 1;\n```\nThat is all.\n3 Gamma\nThe end."
    )
    monkeypatch.setattr(pdf, "page_count", lambda _path: 1)
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: page)
    marks = [Bookmark(title, 0, 1) for title in ("1 Alpha", "2 Beta", "3 Gamma")]
    spans = chunk_module.spans_from_bookmarks(marks, 1)
    parts = chunk_module.bookmark_parts(
        Path("/nonexistent/book.pdf"), marks, spans, chunk_module.note_budget(), "bk1"
    )
    texts = [text for _span, text in parts]
    assert texts[0].endswith("int a;\n```")
    assert texts[1].startswith("```\n2 Beta")
    assert texts[2] == "3 Gamma\nThe end."
    assert all(text.count("```") % 2 == 0 for text in texts)


def test_a_trusted_outline_names_its_chunk_despite_a_numbered_line() -> None:
    span = Span("Glossary", 0, 320, 330)
    text = "Glossary\n\n19.1 Explain the difference between two orders\n"
    assert chunk_module.identify(span, text, 54)[1:] == (
        "19.1",
        "Explain the difference between two orders",
    )
    assert chunk_module.identify(span, text, 54, trusted=True)[1:] == (
        "054",
        "Glossary",
    )


def test_an_appendix_under_a_part_ends_the_last_chapter() -> None:
    bookmarks = [
        Bookmark("Part Five. Parallel organization", 0, 250),
        Bookmark("Chapter 21. Multicore computers", 1, 251),
        Bookmark("21.1. Performance", 2, 252),
        Bookmark("Appendix A. System buses", 1, 278),
        Bookmark("A.1. Bus structure", 2, 279),
    ]
    assert chunk_module.outline_chapter(bookmarks, 252) == 21
    assert chunk_module.outline_chapter(bookmarks, 279) is None


def test_a_merged_chunk_names_its_sections_and_keeps_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bookmarks = [
        Bookmark("1.6. Arrays", 1, 3),
        Bookmark("1.7. Functions", 1, 4),
        Bookmark("1.8. Arguments", 1, 5),
    ]
    monkeypatch.setattr(pdf, "page_count", lambda _path: 5)
    monkeypatch.setattr(pdf, "read_toc", lambda _path: bookmarks)
    monkeypatch.setattr(
        pdf, "page_text", lambda _p, first, _l: f"page {first} " + "x" * 400
    )
    chunks = chunk_module.plan("bk1", Path("/nonexistent/book.pdf"))
    assert chunks[0].parts == ("1.6 Arrays", "1.7 Functions", "1.8 Arguments")
    assert chunk_module.load_plan("bk1")[0].parts == chunks[0].parts


def test_a_single_section_chunk_has_no_parts() -> None:
    assert chunk_module.merged_parts([Span("1.6. Arrays", 1, 3, 3)]) == ()
    split = [Span("1.6. Arrays", 1, 3, 3), Span("1.6. Arrays", 1, 4, 4)]
    assert chunk_module.merged_parts(split) == ()


def test_a_section_number_without_a_space_after_its_dot() -> None:
    assert chunk_module.section_number("1.8.Arguments - by value") == "1.8"
    assert (
        chunk_module.section_title("1.8.Arguments - by value") == "Arguments - by value"
    )
    assert chunk_module.section_number("3.5mm jack") is None
    assert chunk_module.section_number("2024 Edition") == "2024"


def test_a_chapter_bookmark_is_numbered_as_its_chapter() -> None:
    span = Span("Rozdział 5. Wskaźniki i tablice", 0, 113, 117)
    assert chunk_module.identify(span, "text", 23) == (5, "5", "Wskaźniki i tablice")
    assert chunk_module.chapter_name("Chapter 2 - Transistors") == "Transistors"


def test_the_second_part_of_an_unnumbered_section_is_a_continuation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sizes = chunk_module.note_budget()
    filler = "x" * (sizes.max_tokens // 3 * config.CHARS_PER_TOKEN)
    bookmarks = [Bookmark("Details", 1, 1), Bookmark("Summary", 1, 7)]
    monkeypatch.setattr(pdf, "page_count", lambda _path: 7)
    monkeypatch.setattr(pdf, "read_toc", lambda _path: bookmarks)
    monkeypatch.setattr(pdf, "page_text", lambda _p, first, _l: f"p{first} {filler}")
    titles = [c.title for c in chunk_module.plan("bk1", Path("/nonexistent/b.pdf"))]
    assert titles[0] == "Details"
    assert titles[1] == f"Details{chunk_module.CONTINUED}"
    assert titles[-1] == "Summary"


# A training course's outline: modules, sections, slides, and none numbered.
COURSE_OUTLINE = [
    Bookmark("Shell scripting training", 0, 1),
    Bookmark("About the trainer", 0, 2),
    Bookmark("Generic course information", 0, 3),
    Bookmark("Training goals", 1, 3),
    Bookmark("Variables and quoting", 0, 5),
    Bookmark("Variables", 1, 5),
    Bookmark("Assigning a value", 2, 5),
    Bookmark("Quoting", 1, 7),
    Bookmark("Exit codes", 0, 9),
    Bookmark("Last slides", 0, 10),
    Bookmark("Thank you", 1, 10),
]


def test_an_unnumbered_outline_is_numbered_by_module_and_section() -> None:
    numbered = chunk_module.number_outline(COURSE_OUTLINE)
    assert [mark.title for mark in numbered] == [
        # The title slide and the trainer's slide, before the first module,
        # are left out; the apparatus stays for the plan to leave out.
        "Generic course information",
        "Training goals",
        "1 Variables and quoting",
        "1.1 Variables",
        "Assigning a value",
        "1.2 Quoting",
        # A module with no sections is a chapter all the same.
        "2 Exit codes",
        "Last slides",
        "Thank you",
    ]


def test_a_numbered_outline_keeps_its_own_numbers() -> None:
    outline = [
        Bookmark("Rozdział 1. Wstęp", 0, 1),
        Bookmark("Pierwszy program", 1, 2),
        Bookmark("Rozdział 2. Typy", 0, 9),
    ]
    assert chunk_module.number_outline(outline) == outline


def test_apparatus_beside_a_section_is_not_part_of_it() -> None:
    numbered = chunk_module.number_outline(COURSE_OUTLINE)
    ranges = chunk_module.section_ranges(numbered, 11)
    assert ("2 Exit codes", 9, 9) in ranges
    assert ("Last slides", 10, 11) in ranges


def test_a_line_at_the_edge_of_most_pages_is_furniture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    book_path = tmp_path / "course.pdf"
    book_path.write_bytes(b"%PDF")
    footer = "Shell course - https://example.org"

    def page(_path: Path, number: int, _last: int) -> str:
        # "fi" closes a script on every page, but in the middle of it.
        topic = "abcdefghijklm"[number]
        return "\n".join(
            [
                *(f"{line} {topic}" for line in ("Topic", "Case", "Usage")),
                "fi",
                *(f"{line} {topic}" for line in ("Note", "Run")),
                footer,
                f"{number}/12",
            ]
        )

    monkeypatch.setattr(pdf, "page_count", lambda _path: 12)
    monkeypatch.setattr(pdf, "page_text", page)
    text = chunk_module.without_furniture(page(book_path, 3, 3), book_path)
    assert footer not in text
    assert "fi" in text.split("\n")
    assert text.startswith("Topic d")


def test_a_short_document_has_no_furniture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    book_path = tmp_path / "leaflet.pdf"
    book_path.write_bytes(b"%PDF")
    monkeypatch.setattr(pdf, "page_count", lambda _path: 3)
    monkeypatch.setattr(pdf, "page_text", lambda _p, _f, _l: "Same line\nbody")
    assert chunk_module.furniture(book_path) == frozenset()
