# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Turn bookmarks into an ordered chunk plan.

A chunk is one note. Sections are never split; sections too small to be worth
a note are merged with the ones that follow them, up to the token budget in
``config``.
"""

from __future__ import annotations

import itertools
import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from app import config, extract, log, pdf
from app.pdf import Bookmark

SECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\.?\s+(.*\S)\s*$")

# The running head a textbook prints on every page of a section:
# "4.07 Limits of the sampling method 214", the trailing number being the
# printed page. It is the only section marker a book without usable bookmarks
# still carries (see docs/DECISIONS.md).
RUNNING_HEAD_RE = re.compile(
    r"^[ \t\r]*(\d{1,2}\.\d{1,2})[ \t\r]+(\S[^\n]*?)[ \t\r]*(?:\d{1,4})?[ \t\r]*$",
    re.MULTILINE,
)
CHUNKS_JSON = "chunks.json"
EXPORT_CHUNKS_JSON = "chunks-export.json"


@dataclass(frozen=True)
class Budget:
    """Token sizes for one chunking pass, and where its output goes.

    Two passes exist over the same book: one sized for the model on this
    machine, one for the export stage. They must not land on each other's
    files, so the subfolder and the manifest travel with the sizes.
    """

    min_tokens: int
    max_tokens: int
    subdir: str
    manifest: str


def note_budget() -> Budget:
    """Chunks sized for the local model: one chunk is one note."""
    return Budget(
        config.CHUNK_MIN_TOKENS, config.CHUNK_MAX_TOKENS, "chunks", CHUNKS_JSON
    )


def export_budget() -> Budget:
    """Chunks sized for a model elsewhere. See config.EXPORT_MIN_TOKENS."""
    return Budget(
        config.EXPORT_MIN_TOKENS,
        config.EXPORT_MAX_TOKENS,
        "chunks-export",
        EXPORT_CHUNKS_JSON,
    )


@dataclass(frozen=True)
class Span:
    """A bookmark and the page range it owns."""

    title: str
    level: int
    page_start: int
    page_end: int

    @property
    def section(self) -> str | None:
        return section_number(self.title)

    @property
    def chapter(self) -> int | None:
        number = self.section
        return (
            int(number.split(".")[0]) if number else extract.chapter_number(self.title)
        )


@dataclass(frozen=True)
class Chunk:
    ord: int
    chapter: int | None
    section: str
    title: str
    page_start: int
    page_end: int
    text_path: Path


def section_number(title: str) -> str | None:
    """``"2.3.1 Emitter follower"`` -> ``"2.3.1"``; ``None`` when unnumbered."""
    match = SECTION_RE.match(title)
    return match.group(1) if match else None


def section_title(title: str) -> str:
    """The same heading without its number."""
    match = SECTION_RE.match(title)
    return match.group(2) if match else title.strip()


def running_head(text: str) -> tuple[str, str] | None:
    """Section number and title from the running head, or ``None``.

    The head repeats on every page of a section, so the number seen most often
    is the section the chunk is mostly about; the earliest wins a tie.
    """
    counts: Counter[str] = Counter()
    titles: dict[str, str] = {}
    for match in RUNNING_HEAD_RE.finditer(text):
        number, title = _reunite_split_number(match.group(1), match.group(2).strip())
        counts[number] += 1
        titles.setdefault(number, title)
    if not counts:
        return None
    number = max(counts, key=counts.__getitem__)
    return number, titles[number]


def _reunite_split_number(number: str, title: str) -> tuple[str, str]:
    """Repair a section number OCR split in two: "2.1 1 Title" is 2.11.

    The first book tested prints the same section head both ways on different
    pages, so the broken form would otherwise become its own section, with the
    stray digit in the note's title and in every link to it. Only a lone digit
    is reunited, and only with a number that has a single decimal place.
    """
    split = re.match(r"^(\d)\s+(\S.*)$", title)
    if split and re.fullmatch(r"\d+\.\d", number):
        return number + split.group(1), split.group(2)
    return number, title


def identify(span: Span, text: str, order: int) -> tuple[int | None, str, str]:
    """Chapter, section number and title for a chunk.

    A numbered bookmark answers it outright. Otherwise the running head in the
    chunk's own text does, which is what a book with a damaged outline leaves
    us. Failing both, the chunk is numbered by its position.
    """
    if span.section:
        return span.chapter, span.section, section_title(span.title)
    head = running_head(text)
    if head:
        number, title = head
        return int(number.split(".")[0]), number, title
    return span.chapter, f"{order:03d}", section_title(span.title)


def estimate_tokens(text: str) -> int:
    return len(text) // config.CHARS_PER_TOKEN


def spans_from_bookmarks(
    bookmarks: Sequence[Bookmark],
    page_count: int,
    selected: Sequence[str] | None = None,
) -> list[Span]:
    """Page range per bookmark, in document order.

    A bookmark that has children keeps only the pages before its first child;
    the rest belongs to the children. ``selected`` filters by bookmark title,
    which is what the UI's TOC checkboxes produce.
    """
    spans: list[Span] = []
    for index, mark in enumerate(bookmarks):
        # A span ends where the next bookmark begins. Bookmarks that point
        # backwards are skipped over rather than closing the span, because a
        # damaged outline must not collapse a chapter into one page. See
        # outline_problems: a span of a single page is the symptom, not a fix.
        following = next(
            (other.page for other in bookmarks[index + 1 :] if other.page >= mark.page),
            None,
        )
        page_end = page_count if following is None else max(following - 1, mark.page)
        spans.append(Span(mark.title, mark.level, mark.page, page_end))

    if selected is None:
        return spans
    wanted = {title.strip() for title in selected}
    return [span for span in spans if span.title.strip() in wanted]


def split_to_budget(
    pdf_path: Path,
    first_page: int,
    last_page: int,
    *,
    max_tokens: int | None = None,
) -> list[tuple[int, int]]:
    """Cut a page range into consecutive slices that fit the token budget.

    A range is a boundary the operator drew, not a note: forty-four pages of a
    textbook are five times what the model can read at once. Pages are never
    split, so a single page over the budget stays whole and the generate stage
    refuses it.
    """
    ceiling = max_tokens if max_tokens is not None else config.CHUNK_MAX_TOKENS
    sizes = {
        page: estimate_tokens(pdf.page_text(pdf_path, page, page))
        for page in range(first_page, last_page + 1)
    }
    slices: list[tuple[int, int]] = []
    start, total = first_page, 0
    for page in range(first_page, last_page + 1):
        if total and total + sizes[page] > ceiling:
            slices.append((start, page - 1))
            start, total = page, 0
        total += sizes[page]
    slices.append((start, last_page))
    return slices


def outline_problems(bookmarks: Sequence[Bookmark]) -> list[str]:
    """Reasons this PDF's outline cannot be trusted to drive chunking.

    Scanned and re-typeset books carry outlines that point at the printed
    contents pages, or at nothing at all. Chunking still runs, but the result
    is whole chapters or worse, so the caller has to be told.
    """
    if not bookmarks:
        return ["the PDF has no bookmarks"]

    problems: list[str] = []
    backwards = sum(
        1
        for earlier, later in itertools.pairwise(bookmarks)
        if later.page < earlier.page
    )
    if backwards:
        problems.append(
            f"{backwards} of {len(bookmarks)} bookmarks point at an earlier page "
            "than the bookmark before them, so their destinations are wrong"
        )
    if not any(section_number(mark.title) for mark in bookmarks):
        problems.append(
            "no bookmark is a numbered section, so a chunk is a whole chapter "
            "at best; give page ranges instead"
        )
    return problems


def group_spans(
    spans: Sequence[Span],
    token_counts: Sequence[int],
    *,
    budget: Budget | None = None,
) -> list[list[Span]]:
    """Merge consecutive spans into chunks within the token budget.

    Never splits a span, never merges across a chapter boundary.
    """
    sizes = budget or note_budget()
    groups: list[list[Span]] = []
    current: list[Span] = []
    current_tokens = 0

    for span, tokens in zip(spans, token_counts, strict=True):
        crosses_chapter = bool(current) and span.chapter != current[0].chapter
        too_big = bool(current) and current_tokens + tokens > sizes.max_tokens
        if crosses_chapter or too_big:
            groups.append(current)
            current, current_tokens = [], 0

        current.append(span)
        current_tokens += tokens
        if current_tokens >= sizes.min_tokens:
            groups.append(current)
            current, current_tokens = [], 0

    if current:
        groups.append(current)
    return groups


def span_text(book_slug: str, pdf_path: Path, span: Span) -> str:
    """Source text of a span: the extracted markdown if found, else raw PDF text."""
    for chapter_file in sorted((config.WORK_DIR / book_slug).glob("*.md")):
        sliced = extract.slice_section(
            chapter_file.read_text(encoding="utf-8"), span.title
        )
        if sliced:
            return sliced
    return pdf.page_text(pdf_path, span.page_start, span.page_end)


def plan(
    book_slug: str,
    pdf_path: Path,
    selected: Sequence[str] | None = None,
    page_ranges: Sequence[tuple[int, int]] | None = None,
    *,
    budget: Budget | None = None,
) -> list[Chunk]:
    """Build the chunk plan and write one text file per chunk."""
    sizes = budget or note_budget()
    page_total = pdf.page_count(pdf_path)
    if page_ranges:
        spans = [
            Span(f"pages {start}-{end}", 0, start, end)
            for first_page, last_page in page_ranges
            for start, end in split_to_budget(
                pdf_path, first_page, last_page, max_tokens=sizes.max_tokens
            )
        ]
    else:
        bookmarks = pdf.read_toc(pdf_path)
        for problem in outline_problems(bookmarks):
            log.event("chunk", "outline problem", book=book_slug, problem=problem)
        spans = spans_from_bookmarks(bookmarks, page_total, selected)
    if not spans:
        raise ValueError("no bookmarks selected and no page ranges given")

    texts = [span_text(book_slug, pdf_path, span) for span in spans]
    # Page ranges are boundaries the operator drew: they are never merged
    # across, and split_to_budget has already cut them to a readable size.
    if page_ranges:
        groups = [[span] for span in spans]
    else:
        groups = group_spans(
            spans, [estimate_tokens(text) for text in texts], budget=sizes
        )
    text_by_span = dict(zip(spans, texts, strict=True))

    chunk_dir = config.WORK_DIR / book_slug / sizes.subdir
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[Chunk] = []
    used: set[str] = set()
    for order, group in enumerate(groups, start=1):
        head = group[0]
        text = "\n\n".join(text_by_span[span] for span in group).strip()
        chapter, number, title = identify(head, text, order)
        section = _unique(number, used)
        text_path = chunk_dir / f"{order:03d}-{extract.slugify(section)}.md"
        text_path.write_text(text + "\n", encoding="utf-8")
        chunks.append(
            Chunk(
                ord=order,
                chapter=chapter,
                section=section,
                title=title,
                page_start=min(span.page_start for span in group),
                page_end=max(span.page_end for span in group),
                text_path=text_path,
            )
        )

    _write_plan(book_slug, chunks, sizes.manifest)
    log.event("chunk", "planned", book=book_slug, chunks=len(chunks), spans=len(spans))
    for chunk in oversized(chunks, max_tokens=sizes.max_tokens):
        log.event(
            "chunk",
            "chunk over budget; the generate stage will refuse it",
            book=book_slug,
            section=chunk.section,
            pages=[chunk.page_start, chunk.page_end],
            tokens=estimate_tokens(chunk.text_path.read_text(encoding="utf-8")),
            budget=sizes.max_tokens,
        )
    return chunks


def oversized(chunks: Sequence[Chunk], *, max_tokens: int | None = None) -> list[Chunk]:
    """Chunks whose source text does not fit the model's context window.

    Only reachable through explicit page ranges: a range is honoured as given,
    and a 26-page range of a textbook is three times the budget.
    """
    ceiling = max_tokens if max_tokens is not None else config.CHUNK_MAX_TOKENS
    return [
        chunk
        for chunk in chunks
        if estimate_tokens(chunk.text_path.read_text(encoding="utf-8")) > ceiling
    ]


def _unique(section: str, used: set[str]) -> str:
    candidate = section
    suffix = 2
    while candidate in used:
        candidate = f"{section}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _write_plan(book_slug: str, chunks: Sequence[Chunk], manifest: str) -> None:
    path = config.WORK_DIR / book_slug / manifest
    records = [
        {
            "ord": chunk.ord,
            "chapter": chunk.chapter,
            "section": chunk.section,
            "title": chunk.title,
            "pages": [chunk.page_start, chunk.page_end],
            "text_path": str(chunk.text_path),
        }
        for chunk in chunks
    ]
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def chapter_titles(chunks: Sequence[Chunk]) -> dict[int, str]:
    """Chapter number to a title for its output subfolder.

    The chunk whose section *is* the chapter number names it; otherwise the
    first chunk of that chapter does.
    """
    titles: dict[int, str] = {}
    for chunk in chunks:
        if chunk.chapter is None or chunk.chapter in titles:
            continue
        if chunk.section == str(chunk.chapter):
            titles[chunk.chapter] = chunk.title
    for chunk in chunks:
        if chunk.chapter is not None:
            titles.setdefault(chunk.chapter, "")
    return titles


def load_plan(book_slug: str, *, budget: Budget | None = None) -> list[Chunk]:
    path = config.WORK_DIR / book_slug / (budget or note_budget()).manifest
    records = json.loads(path.read_text(encoding="utf-8"))
    return [
        Chunk(
            ord=record["ord"],
            chapter=record["chapter"],
            section=record["section"],
            title=record["title"],
            page_start=record["pages"][0],
            page_end=record["pages"][1],
            text_path=Path(record["text_path"]),
        )
        for record in records
    ]


def parse_page_ranges(text: str) -> list[tuple[int, int]]:
    """``"60-120, 131, 140-142"`` -> ``[(60, 120), (131, 131), (140, 142)]``."""
    ranges: list[tuple[int, int]] = []
    for part in re.split(r"[,\n;]+", text):
        token = part.strip()
        if not token:
            continue
        # An en dash is accepted: page ranges copied out of a PDF carry one.
        match = re.fullmatch(r"(\d+)\s*(?:[-–]\s*(\d+))?", token)  # noqa: RUF001
        if not match:
            raise ValueError(f"not a page range: {token!r}")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if end < start:
            raise ValueError(f"page range ends before it starts: {token!r}")
        ranges.append((start, end))
    return ranges
