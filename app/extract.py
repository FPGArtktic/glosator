# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""PDF to markdown plus figure crops.

Output under ``work/<book>/``:
  ``<nn>-<chapter>.md``  one file per top-level heading in the page range
  ``figures/*.png``      one crop per picture docling found
  ``figures.json``       bbox, page, caption and owning heading per crop
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from app import config, log, pdf

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$", re.MULTILINE)

# A chapter heading is numbered and that number is not a section number:
# "3 Sampling" and "Chapter 3" are chapters, "3.12 Windows" is not.
CHAPTER_HEADING_RE = re.compile(
    r"\s*(?:chapter|rozdzia[lł])?\s*(\d{1,2})(?!\s*\.\s*\d)\b", re.IGNORECASE
)
FIGURES_JSON = "figures.json"


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
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-") or "untitled"


def chapter_number(title: str) -> int | None:
    """Leading chapter number of a heading, if it has one."""
    match = re.match(r"\s*(?:chapter|rozdzia[lł])?\s*(\d{1,2})\b", title, re.IGNORECASE)
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


def slice_section(markdown: str, heading: str) -> str | None:
    """Text of one heading, down to the next heading of the same or higher level.

    Used by chunking to get a section's source text out of a chapter file.
    """
    target = _normalise(heading)
    for match in HEADING_RE.finditer(markdown):
        if _normalise(match.group(2)) != target:
            continue
        level = len(match.group(1))
        for following in HEADING_RE.finditer(markdown, match.end()):
            if len(following.group(1)) <= level:
                return markdown[match.start() : following.start()].strip()
        return markdown[match.start() :].strip()
    return None


def _normalise(heading: str) -> str:
    return re.sub(r"\s+", " ", heading).strip().casefold()


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


def run(
    book_slug: str,
    pdf_path: Path,
    first_page: int,
    last_page: int,
    ocr_langs: str = config.OCR_LANGS,
) -> ExtractResult:
    """Extract a page range. Overwrites previous output for the same book."""
    book_dir = config.WORK_DIR / book_slug
    (book_dir / "figures").mkdir(parents=True, exist_ok=True)

    ocr_pages = pages_needing_ocr(pdf_path, first_page, last_page)
    log.event(
        "extract",
        "starting",
        book=book_slug,
        pages=[first_page, last_page],
        ocr_pages=len(ocr_pages),
    )

    document = _convert(pdf_path, first_page, last_page, ocr_langs, bool(ocr_pages))
    markdown = document.export_to_markdown()

    chapter_files = _write_chapters(book_dir, markdown, first_page, last_page)
    figures = _write_figures(book_dir, pdf_path, document)
    (book_dir / FIGURES_JSON).write_text(
        json.dumps(
            [asdict(figure) for figure in figures], ensure_ascii=False, indent=2
        ),
        encoding="utf-8",
    )

    log.event(
        "extract",
        "done",
        book=book_slug,
        chapters=len(chapter_files),
        figures=len(figures),
    )
    return ExtractResult(book_dir, chapter_files, figures, ocr_pages)


def preview(
    pdf_path: Path,
    first_page: int,
    ocr_langs: str = config.OCR_LANGS,
    pages: int = config.PREVIEW_PAGES,
) -> str:
    """Markdown of a few pages, for the UI's pre-flight check."""
    last_page = min(first_page + pages - 1, pdf.page_count(pdf_path))
    needs_ocr = bool(pages_needing_ocr(pdf_path, first_page, last_page))
    document = _convert(pdf_path, first_page, last_page, ocr_langs, needs_ocr)
    return document.export_to_markdown()


def _convert(
    pdf_path: Path, first_page: int, last_page: int, ocr_langs: str, do_ocr: bool
):
    """The only place that talks to docling. Keep version churn contained here."""
    from docling.datamodel.accelerator_options import (
        AcceleratorDevice,
        AcceleratorOptions,
    )
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TesseractCliOcrOptions,
    )
    from docling.document_converter import DocumentConverter, PdfFormatOption

    options = PdfPipelineOptions()
    if config.DOCLING_MODELS.is_dir():
        options.artifacts_path = config.DOCLING_MODELS
    options.accelerator_options = AcceleratorOptions(
        device=AcceleratorDevice.CPU, num_threads=config.DOCLING_THREADS
    )
    options.do_ocr = do_ocr
    options.do_table_structure = True
    options.generate_picture_images = False
    if do_ocr:
        # force_full_page_ocr stays off: pages that do have a text layer keep
        # it, which is both faster and more accurate than OCR.
        options.ocr_options = TesseractCliOcrOptions(lang=ocr_langs.split("+"))

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    result = converter.convert(pdf_path, page_range=(first_page, last_page))
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


def _write_figures(book_dir: Path, pdf_path: Path, document) -> list[Figure]:
    """Crop every picture docling located into ``figures/``."""
    figures: list[Figure] = []
    heading = ""
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
        figure_id = f"fig-{page}-{len(figures) + 1}"
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
    return figures


def _crop(pdf_path: Path, page: int, bbox, out_path: Path) -> None:
    image = pdf.render_page(pdf_path, page)
    box = bbox_to_pixels(
        (bbox.l, bbox.t, bbox.r, bbox.b),
        pdf.page_height_pt(pdf_path, page),
        origin_bottom_left=str(bbox.coord_origin).endswith("BOTTOMLEFT"),
    )
    image.crop(box).save(out_path)


def load_figures(book_slug: str) -> list[Figure]:
    path = config.WORK_DIR / book_slug / FIGURES_JSON
    if not path.exists():
        return []
    records = json.loads(path.read_text(encoding="utf-8"))
    return [Figure(**{**record, "bbox": tuple(record["bbox"])}) for record in records]
