# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Chunk planning: numbering, page spans, merging, page-range parsing."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import chunk as chunk_module
from app import config, extract, log
from app.chunk import Chunk, Span
from app.pdf import Bookmark


@pytest.fixture(autouse=True)
def no_outline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Page-range plans read the outline for chapters; the test PDFs have none."""
    monkeypatch.setattr(chunk_module.pdf, "read_toc", lambda _path: [])


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


def test_split_to_budget_leaves_a_small_range_alone(monkeypatch) -> None:
    monkeypatch.setattr(chunk_module.pdf, "page_text", lambda _p, _f, _l: "x" * 400)
    assert chunk_module.split_to_budget(Path("/b.pdf"), 13, 16) == [(13, 16)]


def test_split_to_budget_cuts_a_long_range_at_page_boundaries(monkeypatch) -> None:
    # Every page is a third of the budget, so three pages fit and the fourth
    # starts a new slice.
    page = "x" * (config.CHUNK_MAX_TOKENS // 3 * config.CHARS_PER_TOKEN)
    monkeypatch.setattr(chunk_module.pdf, "page_text", lambda _p, _f, _l: page)
    assert chunk_module.split_to_budget(Path("/b.pdf"), 1, 7) == [
        (1, 3),
        (4, 6),
        (7, 7),
    ]


def test_split_to_budget_keeps_an_oversized_page_whole(monkeypatch) -> None:
    page = "x" * ((config.CHUNK_MAX_TOKENS + 1) * config.CHARS_PER_TOKEN)
    monkeypatch.setattr(chunk_module.pdf, "page_text", lambda _p, _f, _l: page)
    assert chunk_module.split_to_budget(Path("/b.pdf"), 5, 6) == [(5, 5), (6, 6)]


def test_plan_cuts_a_forty_page_range_into_readable_chunks(monkeypatch) -> None:
    # What pressing "Run everything" on pages 13-56 actually produced: one
    # chunk of 28607 tokens, which the generate stage refused.
    page = "x" * (650 * config.CHARS_PER_TOKEN)
    monkeypatch.setattr(chunk_module.pdf, "page_count", lambda _path: 200)
    monkeypatch.setattr(chunk_module.pdf, "page_text", lambda _p, _f, _l: page)

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
    monkeypatch.setattr(chunk_module.pdf, "page_count", lambda _path: 20)
    monkeypatch.setattr(chunk_module.pdf, "read_toc", lambda _path: bookmarks)
    monkeypatch.setattr(
        chunk_module.pdf, "page_text", lambda _p, first, last: f"text {first}-{last}"
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
    monkeypatch.setattr(chunk_module.pdf, "page_count", lambda _path: 20)
    monkeypatch.setattr(chunk_module.pdf, "read_toc", lambda _path: [])
    monkeypatch.setattr(
        chunk_module.pdf, "page_text", lambda _p, first, last: f"text {first}-{last}"
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
    page = "x" * (config.CHUNK_MAX_TOKENS * config.CHARS_PER_TOKEN)
    monkeypatch.setattr(chunk_module.pdf, "page_text", lambda _p, _f, _l: page)
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
    monkeypatch.setattr(
        chunk_module.pdf, "page_text", lambda _p, first, _last: pages[first]
    )
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
    monkeypatch.setattr(chunk_module.pdf, "page_count", lambda _path: 3)
    monkeypatch.setattr(
        chunk_module.pdf,
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
    monkeypatch.setattr(
        chunk_module.pdf, "page_text", lambda _p, first, _last: layer[first]
    )
    path = extract.page_markdown_path("bk1", 1)
    path.parent.mkdir(parents=True)
    path.write_text("In this case,\n\n$$V_{BE} < 0.6$$\n", encoding="utf-8")

    text = chunk_module.readable_text(Path("/b.pdf"), 1, 2, "bk1")
    assert text == "In this case,\n\n$$V_{BE} < 0.6$$\n\ntext layer two"


def test_readable_text_drops_a_contents_page_docling_made_a_table(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        chunk_module.pdf, "page_text", lambda _p, _first, _last: CONTENTS_PAGE
    )
    path = extract.page_markdown_path("bk1", 1)
    path.parent.mkdir(parents=True)
    path.write_text("| 1.1 | Section | 3 |\n", encoding="utf-8")
    assert chunk_module.readable_text(Path("/b.pdf"), 1, 1, "bk1") == ""


def test_running_head_reads_a_markdown_heading() -> None:
    assert chunk_module.running_head("## 1.4 Current & Voltage\nbody") == (
        "1.4",
        "Current & Voltage",
    )
