# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""PDF to markdown plus figure crops.

Output under ``work/<book>/``:
  ``<nn>-<chapter>.md``  one file per top-level heading in the page range
  ``pages/<nnnn>.md``    docling's markdown for one page
  ``figures/*.png``      one crop per picture docling found
  ``figures.json``       bbox, page, caption and owning heading per crop
  ``batches/*.json``     what each docling run produced, for resuming
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import itertools
import json
import os
import re
import signal
import subprocess
import sys
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

from app import config, listing, log, pdf

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$", re.MULTILINE)

# A heading's leading number, unless a hyphen joins it to a word: the "1"
# of "1-Wire" (a bus) or "8-bitowy" is part of a name, not a chapter.
CHAPTER_NUMBER_RE = re.compile(
    r"\s*(?:chapter|rozdzia[lł])?\s*(\d{1,2})\b(?![-\u2010\u2013])", re.IGNORECASE
)
# A chapter heading is numbered and that number is not a section number:
# "3 Sampling" and "Chapter 3" are chapters, "3.12 Windows" is not.
CHAPTER_HEADING_RE = re.compile(
    r"\s*(?:chapter|rozdzia[lł])?\s*(\d{1,2})(?!\s*\.\s*\d)\b(?![-\u2010\u2013])",
    re.IGNORECASE,
)
FIGURES_JSON = "figures.json"
TABLE_ROW_RE = re.compile(r"^\|.*\|[ \t]*$", re.MULTILINE)
TABLE_PADDING_RE = re.compile(r"[ \t]{2,}")
TABLE_RULE_RE = re.compile(r"-{4,}")
# The rule under a markdown table's header row: "| --- | :-: |".
TABLE_HEADER_RULE_RE = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")
# The shape of a per-copy watermark: an MD5-sized lowercase hex digest.
WATERMARK_RE = re.compile(r"\b[0-9a-f]{32}\b")
PAGES_DIR = "pages"
BATCHES_DIR = "batches"
# Bumped when what a batch writes changes, so older batches are not reused.
BATCH_FORMAT = 2
# From <linux/prctl.h>: deliver a signal to this process when its parent dies.
PR_SET_PDEATHSIG = 1

# NFKD decomposes ą, ć, ę, ń, ó, ś, ź and ż into a plain letter plus a
# combining mark, which the ASCII encode in slugify then drops. It does not
# decompose ł, because ł is a letter in its own right rather than l with a
# stroke, so without this table "Układy cyfrowe" slugifies to "ukady-cyfrowe"
# and the chapter folder and every link to it carry the typo.
_UNDECOMPOSED = str.maketrans(
    {"ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ø": "o", "Ø": "O"}
)


@dataclass(frozen=True)
class Figure:
    """One picture crop and everything a vision prompt needs about it."""

    id: str
    page: int
    bbox: tuple[float, float, float, float]
    caption: str
    heading: str
    path: str


@dataclass(frozen=True)
class ExtractResult:
    book_dir: Path
    chapter_files: list[Path]
    figures: list[Figure]
    ocr_pages: list[int]


def slugify(text: str) -> str:
    """ASCII, lowercase, hyphenated. Polish diacritics fold to plain letters."""
    folded = (
        unicodedata.normalize("NFKD", text.translate(_UNDECOMPOSED))
        .encode("ascii", "ignore")
        .decode()
    )
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-") or "untitled"


def chapter_number(title: str) -> int | None:
    """Leading chapter number of a heading, if it has one."""
    match = CHAPTER_NUMBER_RE.match(title)
    return int(match.group(1)) if match else None


def is_chapter_heading(title: str) -> bool:
    """True for ``3 Sampling`` or ``Chapter 3``, false for ``3.12 Windows``.

    Heading level cannot be used for this: docling assigns the same level to a
    chapter title and to a one-word paragraph heading, so the number
    is the only signal that a chapter starts here.
    """
    return CHAPTER_HEADING_RE.match(title) is not None


def split_markdown_by_chapter(markdown: str) -> list[tuple[str, str]]:
    """Split at chapter headings. Empty when the text starts no chapter.

    An extraction run covers a page range, which is often a fraction of a
    chapter; then there is nothing to split and the caller writes one file.
    """
    cuts = [
        match
        for match in HEADING_RE.finditer(markdown)
        if is_chapter_heading(match.group(2))
    ]
    if not cuts:
        return []

    sections: list[tuple[str, str]] = []
    preamble = markdown[: cuts[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for index, cut in enumerate(cuts):
        end = cuts[index + 1].start() if index + 1 < len(cuts) else len(markdown)
        sections.append((cut.group(2), markdown[cut.start() : end].strip()))
    return sections


def pages_needing_ocr(pdf_path: Path, first_page: int, last_page: int) -> list[int]:
    """Pages whose text layer is too thin to use."""
    counts = pdf.page_char_counts(pdf_path, range(first_page, last_page + 1))
    return [
        page for page, chars in counts.items() if chars < config.TEXT_LAYER_MIN_CHARS
    ]


def bbox_to_pixels(
    bbox: tuple[float, float, float, float],
    page_height_pt: float,
    *,
    dpi: int = config.FIGURE_DPI,
    pad_pt: float = config.FIGURE_PAD_PT,
    origin_bottom_left: bool = True,
) -> tuple[int, int, int, int]:
    """Convert a docling bbox in points to a PIL crop box in pixels."""
    left, top, right, bottom = bbox
    if origin_bottom_left:
        top, bottom = page_height_pt - top, page_height_pt - bottom
    scale = dpi / pdf.POINTS_PER_INCH
    box = (
        (min(left, right) - pad_pt) * scale,
        (min(top, bottom) - pad_pt) * scale,
        (max(left, right) + pad_pt) * scale,
        (max(top, bottom) + pad_pt) * scale,
    )
    return tuple(max(0, round(value)) for value in box)  # type: ignore[return-value]


def batches(
    first_page: int, last_page: int, size: int | None = None
) -> list[tuple[int, int]]:
    """Consecutive page ranges of at most ``size`` pages covering the range."""
    step = size or config.EXTRACT_BATCH_PAGES
    return [
        (start, min(start + step - 1, last_page))
        for start in range(first_page, last_page + 1, step)
    ]


def page_markdown_path(book_slug: str, page: int) -> Path:
    """docling's markdown for one page, which chunking reads by page range."""
    return config.WORK_DIR / book_slug / PAGES_DIR / f"{page:04d}.md"


def run(
    book_slug: str,
    pdf_path: Path,
    first_page: int,
    last_page: int,
    ocr_langs: str = config.OCR_LANGS,
    *,
    force: bool = False,
    listings: bool = False,
) -> ExtractResult:
    """Extract a page range, batch by batch, each batch in a child process.

    A batch extracted earlier with the same settings is reused unless
    ``force``, so a stopped extraction of a long book resumes instead of
    starting over. The chapter files and ``figures.json`` are rewritten from
    all batches at the end. ``listings`` rebuilds the code listings of a
    programming book from the text layer, and turns formula recognition off,
    which read code as mathematics.
    """
    book_dir = config.WORK_DIR / book_slug
    (book_dir / "figures").mkdir(parents=True, exist_ok=True)
    log.event("extract", "starting", book=book_slug, pages=[first_page, last_page])

    figures: list[Figure] = []
    ocr_pages: list[int] = []
    heading = ""
    for start, end in batches(first_page, last_page):
        wanted = _batch_settings(start, end, ocr_langs, len(figures), heading, listings)
        record = None if force else _reusable_batch(book_dir, wanted)
        if record is None:
            record = _run_batch_child(book_slug, pdf_path, wanted)
        figures += [_figure(entry) for entry in record["figures"]]
        ocr_pages += record["ocr_pages"]
        heading = record["last_heading"]

    markdown = "\n\n".join(
        page_markdown_path(book_slug, page).read_text(encoding="utf-8")
        for page in range(first_page, last_page + 1)
    )
    chapter_files = _write_chapters(book_dir, markdown, first_page, last_page)
    # Ids count every picture docling found, decorations included, so that a
    # kept batch's ids stay valid; only the list the notes see drops them.
    figures = [figure for figure in figures if not is_decoration(figure)]
    figures = drop_repeated(figures, book_dir)
    _write_json(book_dir / FIGURES_JSON, [asdict(figure) for figure in figures])
    log.event(
        "extract",
        "done",
        book=book_slug,
        chapters=len(chapter_files),
        figures=len(figures),
        ocr_pages=len(ocr_pages),
    )
    return ExtractResult(book_dir, chapter_files, figures, ocr_pages)


def _batch_settings(
    first_page: int,
    last_page: int,
    ocr_langs: str,
    figure_offset: int,
    heading: str,
    listings: bool = False,
) -> dict[str, object]:
    """Everything a batch's output depends on. A batch is reused only on a match.

    The figure offset and the heading carried in from the batch before are
    part of it: figure ids count through the whole range, and a figure before
    the first heading of a batch belongs to the last heading of the previous.
    """
    return {
        "format": BATCH_FORMAT,
        "pages": [first_page, last_page],
        "ocr_langs": ocr_langs,
        "formulas": config.DOCLING_FORMULAS and not listings,
        "listings": listings,
        "figure_offset": figure_offset,
        "heading": heading,
    }


def _batch_path(book_dir: Path, settings: dict[str, object]) -> Path:
    first_page, last_page = settings["pages"]  # type: ignore[misc]
    return book_dir / BATCHES_DIR / f"{first_page:04d}-{last_page:04d}.json"


def _reusable_batch(book_dir: Path, wanted: dict[str, object]) -> dict | None:
    path = _batch_path(book_dir, wanted)
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("settings") != wanted:
        return None
    log.event("extract", "batch reused", pages=wanted["pages"])
    return record


def is_decoration(figure: Figure) -> bool:
    """True for a margin icon: a picture with no caption, narrower than a figure.

    "Design Your Own Video Game Console" marks every callout box with a black
    "WARNING!", "TIP", "NOTE" or "INTERESTING FACT" tile, and docling crops
    each one as a picture: over a hundred in one book. They would be embedded
    in the notes and described by the vision pass, one model call each.
    """
    left, _top, right, _bottom = figure.bbox
    return not figure.caption and abs(right - left) <= config.DECORATION_MAX_WIDTH_PT


def image_hash(path: Path) -> int:
    """64-bit average hash: which of 8x8 grey cells are brighter than the mean.

    Survives the small shifts and rescaling between two crops of the same
    logo, which an exact comparison of the pixels would not.
    """
    with Image.open(path) as image:
        cells = image.convert("L").resize((8, 8)).tobytes()
    mean = sum(cells) / len(cells)
    return sum(1 << bit for bit, cell in enumerate(cells) if cell > mean)


@dataclass(frozen=True)
class Sighting:
    """One uncaptioned picture, as far as telling repeats apart needs."""

    image: int  # image_hash of the crop
    page: int
    width_pt: float
    height_pt: float

    def same_picture(self, other: Sighting) -> bool:
        # A logo or a reprinted cover is placed at the same size every time;
        # code listings printed as grey boxes hash alike but differ in height.
        tolerance = config.REPEATED_FIGURE_SIZE_TOLERANCE_PT
        return (
            (self.image ^ other.image).bit_count() <= config.REPEATED_FIGURE_MAX_BITS
            and abs(self.width_pt - other.width_pt) <= tolerance
            and abs(self.height_pt - other.height_pt) <= tolerance
        )


def repeated_figures(sightings: dict[str, Sighting]) -> set[str]:
    """Ids of pictures that recur across the book: part of the page, not the text.

    Each picture joins the group of the first earlier one it matches.
    """
    groups: list[tuple[Sighting, list[str], set[int]]] = []
    for figure_id, sighting in sightings.items():
        for first, members, pages in groups:
            if first.same_picture(sighting):
                members.append(figure_id)
                pages.add(sighting.page)
                break
        else:
            groups.append((sighting, [figure_id], {sighting.page}))
    return {
        figure_id
        for _first, members, pages in groups
        if len(pages) >= config.REPEATED_FIGURE_MIN_PAGES
        and max(pages) - min(pages) >= config.REPEATED_FIGURE_MIN_SPAN_PAGES
        for figure_id in members
    }


def drop_repeated(figures: list[Figure], book_dir: Path) -> list[Figure]:
    """The figures without the uncaptioned pictures the book keeps reprinting."""
    sightings = {
        figure.id: Sighting(
            image_hash(book_dir / figure.path),
            figure.page,
            abs(figure.bbox[2] - figure.bbox[0]),
            abs(figure.bbox[1] - figure.bbox[3]),
        )
        for figure in figures
        if not figure.caption and (book_dir / figure.path).exists()
    }
    repeated = repeated_figures(sightings)
    if repeated:
        log.event("extract", "repeated pictures dropped", count=len(repeated))
    return [figure for figure in figures if figure.id not in repeated]


def _figure(entry: dict) -> Figure:
    return Figure(**{**entry, "bbox": tuple(entry["bbox"])})


# The batch child currently running, so that a worker being stopped takes it
# with it instead of leaving it holding the card.
_child: subprocess.Popen | None = None


def kill_active_child() -> None:
    """Kill the extraction child, if one is running. For the worker's SIGTERM."""
    process = _child
    if process is not None and process.poll() is None:
        process.kill()
        log.event("extract", "extraction child killed")


def _run_batch_child(
    book_slug: str, pdf_path: Path, settings: dict[str, object]
) -> dict:
    """Extract one batch in a child process and read back what it wrote.

    docling's models stay in the process that loaded them, and torch keeps a
    caching allocator on the card: freeing the converter hands its memory back
    to that cache, not to the driver. The worker outlives the stage and goes
    on to the generate job, whose Ollama model would find the card still half
    taken. Process exit is the only thing that returns device memory
    unconditionally, so every batch runs in a child that writes its record
    and exits. tachygraf learned the same about its ASR stage.
    """
    global _child
    first_page, last_page = settings["pages"]  # type: ignore[misc]
    argv = [
        sys.executable,
        "-m",
        "app.extract",
        "--book",
        book_slug,
        "--pdf",
        str(pdf_path),
        "--settings",
        json.dumps(settings),
    ]
    log.event("extract", "starting a batch", pages=[first_page, last_page])
    try:
        _child = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=_die_with_parent,
        )
        _stdout, stderr = _child.communicate(timeout=config.EXTRACT_BATCH_TIMEOUT_S)
        code = _child.returncode
    except subprocess.TimeoutExpired as error:
        kill_active_child()
        raise RuntimeError(
            f"pages {first_page}-{last_page} did not finish within "
            f"{config.EXTRACT_BATCH_TIMEOUT_S} s"
        ) from error
    finally:
        _child = None

    if code != 0:
        # The child logs to the same file; this is what reaches the job row.
        tail = (stderr or b"").decode("utf-8", errors="replace").strip()
        last = tail.splitlines()[-1] if tail else "no output"
        raise RuntimeError(f"pages {first_page}-{last_page} failed ({code}): {last}")
    book_dir = config.WORK_DIR / book_slug
    return json.loads(_batch_path(book_dir, settings).read_text(encoding="utf-8"))


def _die_with_parent() -> None:
    """Have the kernel kill the child when the worker dies, however it dies.

    "Stop now" ends the worker; a child left behind would keep a GPU and a
    docling run nobody is waiting for. Linux only, as the container is.
    """
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL)


def extract_batch(book_slug: str, pdf_path: Path, settings: dict[str, object]) -> dict:
    """The child's whole job: one docling run, its pages, its figures, its record."""
    first_page, last_page = settings["pages"]  # type: ignore[misc]
    book_dir = config.WORK_DIR / book_slug
    ocr_pages = pages_needing_ocr(pdf_path, first_page, last_page)
    document, device = _convert_on_best_device(
        pdf_path,
        first_page,
        last_page,
        str(settings["ocr_langs"]),
        bool(ocr_pages),
        formulas=bool(settings["formulas"]),
    )
    if settings.get("listings"):
        rebuild_listings(document, pdf_path)
    _write_pages(book_slug, document, first_page, last_page)
    figures, last_heading = _write_figures(
        book_dir,
        pdf_path,
        document,
        figure_offset=int(settings["figure_offset"]),  # type: ignore[arg-type]
        heading=str(settings["heading"]),
    )
    record = {
        "settings": settings,
        "device": device,
        "ocr_pages": ocr_pages,
        "figures": [asdict(figure) for figure in figures],
        "last_heading": last_heading,
    }
    _write_json(_batch_path(book_dir, settings), record)
    log.event(
        "extract",
        "batch done",
        pages=[first_page, last_page],
        device=device,
        figures=len(figures),
    )
    return record


def gpu_free_mb() -> int | None:
    """Free VRAM on the first card, or ``None`` when the card cannot be asked.

    ``None`` is not zero: it means nvml was not there to answer, which is also
    what a host without an NVIDIA card looks like. Both mean the CPU.
    """
    try:
        import pynvml
    except ImportError:
        return None
    try:
        pynvml.nvmlInit()
    except Exception as error:  # no driver, no CDI spec, no card
        log.event("extract", "nvml unavailable", error=repr(error))
        return None
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        return int(pynvml.nvmlDeviceGetMemoryInfo(handle).free // 1_000_000)
    except Exception as error:
        log.event("extract", "could not read VRAM", error=repr(error))
        return None
    finally:
        # Failing to shut nvml down cannot be allowed to fail a job.
        with contextlib.suppress(Exception):
            pynvml.nvmlShutdown()


def choose_device(setting: str = config.DOCLING_DEVICE) -> tuple[str, str]:
    """``(device, reason)`` for docling: ``"cuda"`` or ``"cpu"``.

    The CPU is a correct answer, not a failure: it is what a card still held
    by Ollama gets, and the extraction is slower there, not worse.
    """
    if setting in ("cpu", "cuda"):
        return setting, f"GLOSATOR_DOCLING_DEVICE={setting}"
    free = gpu_free_mb()
    if free is None:
        return "cpu", "no usable NVIDIA card was found"
    if free < config.EXTRACT_MIN_FREE_MB:
        return (
            "cpu",
            f"{free} MB of VRAM is free and extraction needs "
            f"{config.EXTRACT_MIN_FREE_MB} MB",
        )
    return "cuda", f"{free} MB of VRAM is free"


def _convert_on_best_device(
    pdf_path: Path,
    first_page: int,
    last_page: int,
    ocr_langs: str,
    do_ocr: bool,
    *,
    formulas: bool = config.DOCLING_FORMULAS,
):
    """Convert on the card if it is free, on the CPU if it is not or if it fails.

    nvml answering "free" is not a promise, and docling on a card that runs
    short does not raise: it logs "Stage layout failed" and returns half the
    figures. _convert turns that into an exception, which is what sends the
    batch to the CPU here instead of into the notes.
    """
    device, reason = choose_device()
    log.event("extract", "device chosen", device=device, reason=reason)
    try:
        return _convert(
            pdf_path,
            first_page,
            last_page,
            ocr_langs,
            do_ocr,
            device,
            formulas=formulas,
        ), device
    except Exception as error:
        if device == "cpu":
            raise
        log.event(
            "extract",
            "the GPU attempt failed; falling back to the CPU",
            pages=[first_page, last_page],
            error=repr(error),
        )
    return _convert(
        pdf_path, first_page, last_page, ocr_langs, do_ocr, "cpu", formulas=formulas
    ), "cpu"


def rebuild_listings(document, pdf_path: Path) -> int:
    """Give each code block of ``document`` its lines and indentation back.

    A block keeps docling's text when the text layer has nothing in its box,
    as on a scanned page, and when it runs over more than one page. Returns
    how many blocks were rebuilt.
    """
    from docling_core.types.doc.labels import DocItemLabel

    glyphs: dict[int, list[pdf.Glyph]] = {}
    rebuilt = 0
    for item, _level in document.iterate_items():
        if getattr(item, "label", None) != DocItemLabel.CODE or len(item.prov) != 1:
            continue
        page = item.prov[0].page_no
        if page not in glyphs:
            glyphs[page] = pdf.page_glyphs(pdf_path, page)
        text = listing.layout(listing.inside(glyphs[page], _box(document, item)))
        if text.strip():
            item.text = text
            rebuilt += 1
    log.event("extract", "listings rebuilt", count=rebuilt)
    return rebuilt


def _box(document, item) -> tuple[float, float, float, float]:
    """An item's box as (left, bottom, right, top) in points from the bottom left."""
    provenance = item.prov[0]
    height = document.pages[provenance.page_no].size.height
    box = provenance.bbox.to_bottom_left_origin(height)
    return (box.l, box.b, box.r, box.t)


def _write_pages(book_slug: str, document, first_page: int, last_page: int) -> None:
    numbers = range(first_page, last_page + 1)
    pages = [compact_tables(page_markdown(document, page)) for page in numbers]
    for page, markdown in zip(numbers, drop_watermarks(pages), strict=True):
        _write_text(page_markdown_path(book_slug, page), markdown.strip() + "\n")


def drop_watermarks(pages: list[str]) -> list[str]:
    """Remove a hex digest that repeats on several pages, wherever it landed.

    docling reads the footer digest into the nearest paragraph, so it ends up
    in the middle of a sentence or ahead of one, and from there in the notes.
    """
    counts = Counter(
        token for page in pages for token in set(WATERMARK_RE.findall(page))
    )
    needed = max(2, min(config.WATERMARK_MIN_PAGES, len(pages)))
    marks = sorted(token for token, count in counts.items() if count >= needed)
    if not marks:
        return pages
    pattern = re.compile(r"[ \t]*\b(?:" + "|".join(marks) + r")\b[ \t]*")
    return [pattern.sub(_watermark_gap, page) for page in pages]


def _watermark_gap(match: re.Match[str]) -> str:
    """One space between two words, nothing at the edge of a line."""
    text = match.string
    at_line_start = match.start() == 0 or text[match.start() - 1] == "\n"
    at_line_end = match.end() == len(text) or text[match.end()] == "\n"
    return "" if at_line_start or at_line_end else " "


def page_markdown(document, page: int | None = None) -> str:
    """docling's markdown of one page, or of all, with the text as printed.

    Its defaults escape HTML and underscores for a markdown renderer. The
    reader here is a model, which copies what it is shown: a programming book
    came out with "&amp;&amp;" for "&&" and "unique\\_ptr" for "unique_ptr".
    """
    return document.export_to_markdown(
        page_no=page, escape_html=False, escape_underscores=False
    )


def compact_tables(markdown: str) -> str:
    """Strip the padding docling puts into every table cell.

    docling pads each cell to the widest one in its column, and a column with
    one long description pads the whole table: a pin table of "Design Your
    Own Video Game Console" came out at 36 kB, of which 5 kB was content. The
    padding goes to the model as tokens and past the chunk budget as size.
    """
    return TABLE_ROW_RE.sub(_compact_row, markdown)


def _compact_row(match: re.Match[str]) -> str:
    row = TABLE_PADDING_RE.sub(" ", match.group(0))
    return TABLE_RULE_RE.sub("---", row)


def icon_boxes_as_quotes(markdown: str) -> str:
    """A box set beside an icon, as a quotation rather than a table of one row.

    docling reads a note or a warning printed beside an icon as a table: an
    empty cell where the icon is, the whole text of the box in the other, and
    no row under the header. The model copies every table whole, so the notes
    of a C book carried a paragraph each as one table cell, fifteen times.
    """
    kept: list[str] = []
    for is_table, rows in itertools.groupby(markdown.split("\n"), key=_is_table_row):
        block = list(rows)
        text = _icon_box_text(block) if is_table else None
        kept += block if text is None else [f"> {text}"]
    return "\n".join(kept)


def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def _icon_box_text(rows: list[str]) -> str | None:
    """The box's text, if the table is a header row of two cells, one empty."""
    if len(rows) != 2 or not TABLE_HEADER_RULE_RE.match(rows[1]):
        return None
    cells = [cell.strip() for cell in rows[0].strip().strip("|").split("|")]
    if len(cells) != 2 or cells[0] or not cells[1]:
        return None
    return cells[1]


def _write_json(path: Path, payload: object) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _write_text(path: Path, text: str) -> None:
    """Through a temporary file and a rename, so a killed batch leaves no half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def preview(
    pdf_path: Path,
    first_page: int,
    ocr_langs: str = config.OCR_LANGS,
    pages: int = config.PREVIEW_PAGES,
) -> str:
    """Markdown of a few pages, for the UI's pre-flight check.

    Always on the CPU: this runs in the interface's own process, which lives
    for the whole session and would keep whatever it put on the card.
    """
    last_page = min(first_page + pages - 1, pdf.page_count(pdf_path))
    needs_ocr = bool(pages_needing_ocr(pdf_path, first_page, last_page))
    document = _convert(pdf_path, first_page, last_page, ocr_langs, needs_ocr, "cpu")
    return page_markdown(document)


class ExtractionIncomplete(RuntimeError):
    """docling returned a document but reported that part of it failed."""


def _convert(
    pdf_path: Path,
    first_page: int,
    last_page: int,
    ocr_langs: str,
    do_ocr: bool,
    device: str,
    *,
    formulas: bool = config.DOCLING_FORMULAS,
):
    """The only place that talks to docling. Keep version churn contained here."""
    from docling.datamodel.accelerator_options import (
        AcceleratorDevice,
        AcceleratorOptions,
    )
    from docling.datamodel.base_models import ConversionStatus, InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TesseractCliOcrOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    if config.DOCLING_MODELS.is_dir():
        options.artifacts_path = config.DOCLING_MODELS
    options.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CUDA if device == "cuda" else AcceleratorDevice.CPU,
        num_threads=config.DOCLING_THREADS,
    )
    options.do_ocr = do_ocr
    options.do_table_structure = True
    options.do_formula_enrichment = formulas
    options.generate_picture_images = False
    if do_ocr:
        # force_full_page_ocr stays off: pages that do have a text layer keep
        # it, which is both faster and more accurate than OCR.
        options.ocr_options = TesseractCliOcrOptions(lang=ocr_langs.split("+"))

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    result = converter.convert(
        pdf_path, page_range=(first_page, last_page), raises_on_error=False
    )
    if result.status != ConversionStatus.SUCCESS:
        # A partial result is the silent half-extraction docs/PILOT.md records:
        # figures missing from the notes with nothing in the log but a warning.
        errors = "; ".join(str(error.error_message) for error in result.errors)
        raise ExtractionIncomplete(
            f"pages {first_page}-{last_page} on {device}: {result.status}: {errors}"
        )
    return result.document


def _write_chapters(
    book_dir: Path, markdown: str, first_page: int, last_page: int
) -> list[Path]:
    """One file per chapter, or one file for the run when it starts no chapter."""
    chapters = split_markdown_by_chapter(markdown)
    if not chapters:
        path = book_dir / f"pages-{first_page:04d}-{last_page:04d}.md"
        path.write_text(markdown.strip() + "\n", encoding="utf-8")
        return [path]

    written: list[Path] = []
    for index, (title, text) in enumerate(chapters, start=1):
        number = chapter_number(title) if title else 0
        name = f"{number if number is not None else index:02d}"
        path = book_dir / f"{name}-{slugify(title or 'front-matter')}.md"
        path.write_text(text + "\n", encoding="utf-8")
        written.append(path)
    return written


def _write_figures(
    book_dir: Path,
    pdf_path: Path,
    document,
    *,
    figure_offset: int = 0,
    heading: str = "",
) -> tuple[list[Figure], str]:
    """Crop every picture docling located into ``figures/``.

    Returns the figures and the last heading seen, which the next batch's
    first figures belong to until that batch reaches a heading of its own.
    """
    figures: list[Figure] = []
    for item, _level in document.iterate_items():
        label = str(getattr(item, "label", ""))
        if label.endswith("section_header") or label.endswith("title"):
            heading = item.text.strip()
            continue
        if not label.endswith("picture") or not item.prov:
            continue
        provenance = item.prov[0]
        page = int(provenance.page_no)
        bbox = provenance.bbox
        figure_id = f"fig-{page}-{figure_offset + len(figures) + 1}"
        relative = f"figures/{figure_id}.png"
        _crop(pdf_path, page, bbox, book_dir / relative)
        figures.append(
            Figure(
                id=figure_id,
                page=page,
                bbox=(bbox.l, bbox.t, bbox.r, bbox.b),
                caption=(item.caption_text(document) or "").strip(),
                heading=heading,
                path=relative,
            )
        )
    return figures, heading


def _crop(pdf_path: Path, page: int, bbox, out_path: Path) -> None:
    image = pdf.render_page(pdf_path, page)
    box = bbox_to_pixels(
        (bbox.l, bbox.t, bbox.r, bbox.b),
        pdf.page_height_pt(pdf_path, page),
        origin_bottom_left=str(bbox.coord_origin).endswith("BOTTOMLEFT"),
    )
    image.crop(box).save(out_path)


def load_figures(book_slug: str) -> list[Figure]:
    """The book's figures, the template's bands left out.

    The bands are left out here rather than at extraction, so that a book
    extracted before the rule needs no second pass on the card.
    """
    path = config.WORK_DIR / book_slug / FIGURES_JSON
    if not path.exists():
        return []
    figures = [
        _figure(record) for record in json.loads(path.read_text(encoding="utf-8"))
    ]
    return drop_bands(figures)


def drop_bands(figures: Sequence[Figure]) -> list[Figure]:
    """The figures without the bands every page of a template prints.

    The repeated-picture check compares the crops, and a slide's title bar
    is a different crop on every slide: its title changes and its width with
    it. Its place does not, so the left edge, top and bottom decide here.
    """
    groups: list[tuple[Figure, list[str], set[int]]] = []
    for figure in figures:
        if figure.caption:
            continue
        for first, members, pages in groups:
            if _same_band(first, figure):
                members.append(figure.id)
                pages.add(figure.page)
                break
        else:
            groups.append((figure, [figure.id], {figure.page}))
    bands = {
        figure_id
        for _first, members, pages in groups
        if len(pages) >= config.FIGURE_BAND_MIN_PAGES
        for figure_id in members
    }
    return [figure for figure in figures if figure.id not in bands]


def _same_band(one: Figure, other: Figure) -> bool:
    """Same left edge, top and bottom, within the repeated-figure tolerance."""
    tolerance = config.REPEATED_FIGURE_SIZE_TOLERANCE_PT
    return all(
        abs(one.bbox[index] - other.bbox[index]) <= tolerance for index in (0, 1, 3)
    )


def main(argv: list[str] | None = None) -> int:
    """``python -m app.extract``: one batch, run by ``_run_batch_child``.

    Internal, as ``python -m app.worker`` is: ``bin/glosator`` stays the only
    way in.
    """
    parser = argparse.ArgumentParser(prog="app.extract")
    parser.add_argument("--book", required=True)
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--settings", required=True, type=json.loads)
    args = parser.parse_args(argv)
    config.ensure_dirs()
    extract_batch(args.book, args.pdf, args.settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
