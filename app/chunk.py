# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Turn bookmarks into an ordered chunk plan.

A chunk is one note. Sections are never split; sections too small to be worth
a note are merged with the ones that follow them, up to the token budget in
``config``.
"""

from __future__ import annotations

import html
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
    r"^[ \t\r]*(?:#{1,6}[ \t]+)?"
    r"(\d{1,2}\.\d{1,2})[ \t\r]+(\S[^\n]*?)[ \t\r]*(?:\d{1,4})?[ \t\r]*$",
    re.MULTILINE,
)
# Leader dots between a contents entry and its page number: "Ohm's Law .... 32".
CONTENTS_LEADER_RE = re.compile(r"(?:\.\s?){4,}")
CONTENTS_ENTRY_RE = re.compile(r"^[^\n]*?(?:\.\s?){4,}\s*\d{1,4}[ \t]*$", re.MULTILINE)
PAGE_SEPARATOR = "\n\n"
CONTINUED = " (continued)"
# balanced_split raises its trial ceiling by a twentieth at a time.
BALANCE_STEP_DIVISOR = 20
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


def note_budget(listings: bool = False) -> Budget:
    """Chunks sized for the local model: one chunk is one note.

    A book whose notes copy its listings gets smaller ones (see
    ``config.LISTING_CHUNK_MAX_TOKENS``).
    """
    if listings:
        return Budget(
            config.LISTING_CHUNK_MIN_TOKENS,
            config.LISTING_CHUNK_MAX_TOKENS,
            "chunks",
            CHUNKS_JSON,
        )
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
    """A bookmark and the page range it owns.

    ``outline_chapter`` is the chapter the outline puts the first page in. It
    is the only chapter a page-range span has when its title is "pages 9-20".
    """

    title: str
    level: int
    page_start: int
    page_end: int
    outline_chapter: int | None = None

    @property
    def section(self) -> str | None:
        return section_number(self.title)

    @property
    def chapter(self) -> int | None:
        number = self.section
        if number:
            return int(number.split(".")[0])
        from_title = extract.chapter_number(self.title)
        return from_title if from_title is not None else self.outline_chapter


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


def running_head(text: str, chapter: int | None = None) -> tuple[str, str] | None:
    """Section number and title from the running head, or ``None``.

    The head repeats on every page of a section, so the number seen most often
    is the section the chunk is mostly about; the earliest wins a tie.
    """
    counts: Counter[str] = Counter()
    titles: dict[str, str] = {}
    for number, title in headings(text, chapter):
        counts[number] += 1
        titles.setdefault(number, title)
    if not counts:
        return None
    number = max(counts, key=counts.__getitem__)
    return number, titles[number]


def headings(text: str, chapter: int | None = None) -> list[tuple[str, str]]:
    """Every numbered heading line in the text, in order, as (number, title).

    With ``chapter`` known from the outline, a number from another chapter is
    not a heading of this text: it is a value ("0.25 - 0.3V") or a reference
    that happened to start a line.
    """
    found: list[tuple[str, str]] = []
    for match in RUNNING_HEAD_RE.finditer(text):
        # docling writes "&" as "&amp;"; a title is a file name, not HTML.
        title = html.unescape(match.group(2).strip())
        number, title = _reunite_split_number(match.group(1), title)
        if not is_heading_title(title):
            continue
        if chapter is not None and int(number.split(".")[0]) != chapter:
            continue
        found.append((number, title))
    return found


def is_heading_title(title: str) -> bool:
    """False for the two kinds of line that look numbered and are not heads.

    A contents entry carries leader dots out to its page number, and became
    a note title once, dots and all. A sentence wrapped after a figure number
    ("Figure\n6.3 shows an excerpt ...") starts lower case, and one wrapped
    inside a caption starts with a bracket or a dash; a heading starts with a
    capital or a digit.
    """
    if CONTENTS_LEADER_RE.search(title):
        return False
    first = title[:1]
    return first.isalnum() and not first.islower()


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


def identify(
    span: Span,
    text: str,
    order: int,
    carried: tuple[str, str] | None = None,
) -> tuple[int | None, str, str]:
    """Chapter, section number and title for a chunk.

    A numbered bookmark answers it outright. Otherwise the running head in the
    chunk's own text does, which is what a book with a damaged outline leaves
    us. A chunk with no head of its own continues ``carried``, the last head
    the chunks before it showed, as long as the outline puts both in the same
    chapter. Failing all of that, the chunk is numbered by its position.
    """
    if span.section:
        return span.chapter, span.section, section_title(span.title)
    head = running_head(text, span.chapter)
    if head:
        number, title = head
        return int(number.split(".")[0]), number, title
    if carried and _same_chapter(carried[0], span.chapter):
        number, title = carried
        return int(number.split(".")[0]), number, f"{title}{CONTINUED}"
    return span.chapter, f"{order:03d}", section_title(span.title)


def _same_chapter(number: str, chapter: int | None) -> bool:
    return chapter is None or int(number.split(".")[0]) == chapter


def outline_chapter(bookmarks: Sequence[Bookmark], page: int) -> int | None:
    """Chapter of the last numbered chapter bookmark at or before ``page``.

    A book whose outline names only its chapters ("Chapter 2 - Basic Analog
    Circuit Analysis") cannot drive chunking, but it still says which chapter
    a page is in, and a note without a chapter lands outside every chapter
    folder. A top-level bookmark that is not a chapter ends the chapter
    before it: an appendix or the index after the last chapter is not part
    of it.
    """
    chapter = None
    for mark in sorted(bookmarks, key=lambda mark: mark.page):
        if mark.page > page:
            break
        number = extract.chapter_number(mark.title)
        if number is not None:
            chapter = number
        elif mark.level == 0:
            chapter = None
    return chapter


def is_contents_page(text: str) -> bool:
    """True for a table of contents page, which has headings and no text."""
    entries = [match.group(0) for match in CONTENTS_ENTRY_RE.finditer(text)]
    if len(entries) >= config.CONTENTS_PAGE_MIN_LINES:
        return True
    dotted = sum(len(entry) for entry in entries)
    return bool(entries) and dotted >= config.CONTENTS_PAGE_MIN_SHARE * len(text)


def readable_text(
    pdf_path: Path, first_page: int, last_page: int, book_slug: str | None = None
) -> str:
    """Text of a page range, without its contents pages.

    A page docling extracted is read from its markdown: reading order across
    columns, tables, and formulas as LaTeX, which the text layer either
    scrambles or loses ("In this case," followed by nothing). A page it has
    not extracted falls back to the text layer.

    A book that opens every chapter with its own contents puts several pages
    of dotted headings into the first chunk of the chapter. The model reads
    them as the subject of the note, and they cost the budget nothing useful.
    The text layer decides that, because docling may turn a contents page
    into a table that has no dotted lines left in it.
    """
    texts: list[str] = []
    for page in range(first_page, last_page + 1):
        layer = pdf.page_text(pdf_path, page, page)
        if is_contents_page(layer):
            continue
        texts.append(_extracted_page(book_slug, page) or layer)
    return PAGE_SEPARATOR.join(texts)


def _extracted_page(book_slug: str | None, page: int) -> str | None:
    if book_slug is None:
        return None
    path = extract.page_markdown_path(book_slug, page)
    return path.read_text(encoding="utf-8").strip() if path.exists() else None


def estimate_tokens(text: str) -> int:
    return len(text) // config.CHARS_PER_TOKEN


def spans_from_bookmarks(
    bookmarks: Sequence[Bookmark],
    page_count: int,
    selected: Sequence[str] | None = None,
) -> list[Span]:
    """Page range per bookmark, in document order.

    Each span knows the chapter the outline puts it in, for a book whose
    sections are not numbered: under "Rozdział 1. Wstęp", "Wskaźniki i
    pamięć" belongs to chapter 1, which its own title cannot say.

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
        chapter = outline_chapter(bookmarks, mark.page)
        spans.append(Span(mark.title, mark.level, mark.page, page_end, chapter))

    if selected is None:
        return spans
    wanted = {title.strip() for title in selected}
    return [span for span in spans if span.title.strip() in wanted]


def is_deep_outline(bookmarks: Sequence[Bookmark]) -> bool:
    """True when numbered sections have unnumbered bookmarks below them.

    The LPI learning materials number each objective ("101.1 Determine and
    configure hardware settings") and hang "Lesson 1", "Introduction", "Guided
    Exercises" and the topics of the lesson under it, unnumbered. Every such
    title repeats in every lesson, and the children share their pages with
    each other, so a span per bookmark reads the same page into several
    chunks and names a chunk "003 Introduction".
    """
    numbered_above: list[tuple[int, bool]] = []
    for mark in bookmarks:
        while numbered_above and numbered_above[-1][0] >= mark.level:
            numbered_above.pop()
        is_numbered = section_number(mark.title) is not None
        if not is_numbered and any(numbered for _level, numbered in numbered_above):
            return True
        numbered_above.append((mark.level, is_numbered))
    return False


def section_ranges(
    bookmarks: Sequence[Bookmark], page_count: int
) -> list[tuple[str, int, int]]:
    """One page range per numbered section of a deep outline, children included.

    An unnumbered bookmark belongs to the numbered section before it, and so
    does a numbered one that repeats the section's number ("101.1 Lesson 2"
    under "101.1 Determine and configure hardware settings"), so the title is
    always the section's own. A range ends where the next section begins.
    Bookmarks before the first numbered one keep their own titles.
    """
    owners: list[tuple[str, int]] = []
    for mark in sorted(bookmarks, key=lambda mark: mark.page):
        number = section_number(mark.title)
        current = section_number(owners[-1][0]) if owners else None
        if not owners or (number is not None and number != current):
            owners.append((mark.title, mark.page))
    ranges: list[tuple[str, int, int]] = []
    for index, (title, first_page) in enumerate(owners):
        following = owners[index + 1][1] if index + 1 < len(owners) else None
        last_page = page_count if following is None else max(following - 1, first_page)
        ranges.append((title, first_page, last_page))
    return ranges


def section_spans(
    pdf_path: Path,
    bookmarks: Sequence[Bookmark],
    page_count: int,
    sizes: Budget,
    book_slug: str,
    selected: Sequence[str] | None = None,
) -> list[Span]:
    """Spans of a deep outline: a section per range, cut to the budget.

    A section of the LPI materials is two lessons with their exercises and
    answers, three times the budget, so it is cut by pages like an operator's
    range. Every part keeps the section's title, and the plan marks all but
    the first "(continued)".
    """
    wanted = {title.strip() for title in selected} if selected else None
    return [
        Span(title, 0, start, end, outline_chapter(bookmarks, start))
        for title, first_page, last_page in section_ranges(bookmarks, page_count)
        if wanted is None or title.strip() in wanted
        for start, end in balanced_split(
            pdf_path, first_page, last_page, sizes, book_slug
        )
    ]


def balanced_split(
    pdf_path: Path, first_page: int, last_page: int, sizes: Budget, book_slug: str
) -> list[tuple[int, int]]:
    """The fewest slices the budget allows, made as even as the pages permit.

    Cut greedily, a section of 6300 tokens is one note of 6000 and one of 300
    about a single page. The same number of slices under a lower ceiling
    gives two notes of about 3000, so the ceiling is lowered in steps until
    the count would grow.
    """

    def cut(ceiling: int) -> list[tuple[int, int]]:
        return split_to_budget(
            pdf_path,
            first_page,
            last_page,
            max_tokens=ceiling,
            min_tokens=min(sizes.min_tokens, ceiling),
            book_slug=book_slug,
        )

    greedy = cut(sizes.max_tokens)
    if len(greedy) < 2:
        return greedy
    total = estimate_tokens(readable_text(pdf_path, first_page, last_page, book_slug))
    ceiling = total // len(greedy)
    while ceiling < sizes.max_tokens:
        even = cut(ceiling)
        if len(even) == len(greedy):
            return even
        ceiling += max(1, ceiling // BALANCE_STEP_DIVISOR)
    return greedy


def _drop_empty(
    groups: list[list[Span]], text_by_span: dict[Span, str], book_slug: str
) -> list[list[Span]]:
    """Leave out a chunk with next to no text: a title page, a bare contents.

    The model would be asked for a note about nothing, and writes one.
    """
    kept = []
    for group in groups:
        tokens = sum(estimate_tokens(text_by_span[span]) for span in group)
        if tokens >= config.CHUNK_SKIP_TOKENS:
            kept.append(group)
            continue
        log.event(
            "chunk",
            "chunk too small; skipped",
            book=book_slug,
            title=group[0].title,
            tokens=tokens,
        )
    return kept


def split_to_budget(
    pdf_path: Path,
    first_page: int,
    last_page: int,
    *,
    max_tokens: int | None = None,
    min_tokens: int | None = None,
    book_slug: str | None = None,
) -> list[tuple[int, int]]:
    """Cut a page range into consecutive slices that fit the token budget.

    A range is a boundary the operator drew, not a note: forty-four pages of a
    textbook are five times what the model can read at once. Pages are never
    split, so a single page over the budget stays whole and the generate stage
    refuses it.

    Once a slice holds ``min_tokens``, it also ends before a page on which a
    numbered section starts. A slice cut only at the ceiling carries the end
    of one section and the start of the third after it, and its note, at most
    700 words, then covers a dozen pages of several subjects and leaves most
    of them out.
    """
    ceiling = max_tokens if max_tokens is not None else config.CHUNK_MAX_TOKENS
    # Measured in characters, as estimate_tokens measures the joined chunk,
    # and with the separator each page adds to the join. Rounding every page
    # down to whole tokens let a chunk of fifteen pages end 8 tokens over.
    ceiling_chars = ceiling * config.CHARS_PER_TOKEN
    floor_chars = (min_tokens or ceiling) * config.CHARS_PER_TOKEN
    sizes: dict[int, int] = {}
    opens_section: dict[int, bool] = {}
    for page in range(first_page, last_page + 1):
        text = readable_text(pdf_path, page, page, book_slug)
        sizes[page] = len(text) + len(PAGE_SEPARATOR) if text else 0
        opens_section[page] = bool(headings(text))
    slices: list[tuple[int, int]] = []
    start, total = first_page, 0
    for page in range(first_page, last_page + 1):
        full = total + sizes[page] > ceiling_chars
        at_section = total >= floor_chars and opens_section[page]
        if total and (full or at_section):
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
    return readable_text(pdf_path, span.page_start, span.page_end, book_slug)


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
    by_section = False
    if page_ranges:
        bookmarks = pdf.read_toc(pdf_path)
        spans = [
            Span(
                f"pages {start}-{end}", 0, start, end, outline_chapter(bookmarks, start)
            )
            for first_page, last_page in page_ranges
            for start, end in split_to_budget(
                pdf_path,
                first_page,
                last_page,
                max_tokens=sizes.max_tokens,
                min_tokens=sizes.min_tokens,
                book_slug=book_slug,
            )
        ]
    else:
        bookmarks = pdf.read_toc(pdf_path)
        for problem in outline_problems(bookmarks):
            log.event("chunk", "outline problem", book=book_slug, problem=problem)
        by_section = is_deep_outline(bookmarks)
        spans = (
            section_spans(pdf_path, bookmarks, page_total, sizes, book_slug, selected)
            if by_section
            else spans_from_bookmarks(bookmarks, page_total, selected)
        )
    if not spans:
        raise ValueError("no bookmarks selected and no page ranges given")

    by_pages = bool(page_ranges) or by_section
    texts = [
        readable_text(pdf_path, span.page_start, span.page_end, book_slug)
        if by_pages
        else span_text(book_slug, pdf_path, span)
        for span in spans
    ]
    # Page ranges are boundaries the operator drew: they are never merged
    # across, and split_to_budget has already cut them to a readable size.
    if page_ranges:
        groups = [[span] for span in spans]
    else:
        groups = group_spans(
            spans, [estimate_tokens(text) for text in texts], budget=sizes
        )
    text_by_span = dict(zip(spans, texts, strict=True))
    if by_section:
        groups = _drop_empty(groups, text_by_span, book_slug)

    chunk_dir = config.WORK_DIR / book_slug / sizes.subdir
    chunk_dir.mkdir(parents=True, exist_ok=True)

    chunks: list[Chunk] = []
    used: set[str] = set()
    carried: tuple[str, str] | None = None
    for order, group in enumerate(groups, start=1):
        head = group[0]
        text = "\n\n".join(text_by_span[span] for span in group).strip()
        chapter, number, title = identify(head, text, order, carried)
        if number in used and not title.endswith(CONTINUED):
            title = f"{title}{CONTINUED}"
        carried = next(reversed(headings(text, head.chapter)), carried)
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
