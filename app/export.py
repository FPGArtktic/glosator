# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Export pass: the extracted source, one file per section, no model call.

Writing a book's notes on this machine costs roughly 85 GPU-hours
(docs/DECISIONS.md). Extraction and chunking are the cheap half and the half
this machine is good at: seconds per page, on the CPU. This stage stops after
them and writes the sections out as plain markdown, so they can be handed to a
model somewhere else instead.

It imports no model client. That absence is the whole point of the stage.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from app import config, extract, generate, log
from app.chunk import Chunk
from app.extract import Figure

# Under the notes folder, not beside the notes: these files are the book's own
# text, not notes about it, and a leading underscore keeps them out of the way
# of the ones that are.
EXPORT_DIRNAME = "_source"
FIGURE_DIRNAME = "figures"
PROMPT_FILE = "_PROMPT.md"


def export_root(book_tag: str, out_dir: Path | str | None = None) -> Path:
    """``<out>/_source/<tag>/`` — one self-contained folder per book."""
    return generate.out_root(out_dir) / EXPORT_DIRNAME / book_tag


def file_path(
    chunk: Chunk,
    chapter_title: str,
    book_tag: str,
    out_dir: Path | str | None = None,
) -> Path:
    """``<out>/_source/<tag>/<NN-chapter>/<section> <Title>.md``.

    The chapter folders mirror the notes tree, so a section is in the same
    place in both.
    """
    name = f"{chunk.section} {chunk.title}".strip()
    folder = generate.chapter_folder(chunk, chapter_title)
    return export_root(book_tag, out_dir) / folder / f"{name}.md"


def frontmatter(
    chunk: Chunk,
    book_title: str,
    book_tag: str,
    domain: str = config.DEFAULT_DOMAIN,
) -> str:
    """Like a note's, minus the model: nothing here was generated.

    ``generator: glosator`` is what lets a rerun replace these files and
    nothing else; ``stage: export`` is what tells them apart from a note.
    """
    chapter = chunk.chapter if chunk.chapter is not None else "null"
    tag_chapter = (
        f"chapter-{chunk.chapter:02d}" if chunk.chapter is not None else "chapter-na"
    )
    return "\n".join(
        [
            "---",
            f'source: "{book_title}"',
            f"chapter: {chapter}",
            f'section: "{chunk.section}"',
            f"pages: [{chunk.page_start}, {chunk.page_end}]",
            "stage: export",
            f"generator: {generate.GENERATOR}",
            f"tags: [{extract.slugify(domain)}, {book_tag}, {tag_chapter}]",
            "---",
        ]
    )


def figures_block(figures: Sequence[Figure]) -> str:
    """Relative links into the book's ``figures/`` folder.

    Plain markdown rather than Obsidian embeds: the notes folder is an
    ordinary directory and need not be a vault, and a relative path is honest
    in either.
    """
    lines: list[str] = []
    for figure in figures:
        name = Path(figure.path).name
        lines.append(f"![{name}](../{FIGURE_DIRNAME}/{name})")
        lines.append(f"*{figure.caption or figure.id}*")
        lines.append("")
    return "\n".join(lines).strip()


def assemble(
    chunk: Chunk,
    source_text: str,
    figures_md: str,
    book_title: str,
    book_tag: str,
    domain: str = config.DEFAULT_DOMAIN,
) -> str:
    """One export file. The source text is copied through untouched."""
    body = [
        frontmatter(chunk, book_title, book_tag, domain),
        f"# {chunk.section} {chunk.title}".strip(),
    ]
    if figures_md:
        body.append(f"## Figures\n\n{figures_md}")
    body.append(f"## Source text\n\n{source_text.strip()}")
    return "\n\n".join(body) + "\n"


def copy_figures(
    figures: Sequence[Figure],
    book_slug: str,
    book_tag: str,
    out_dir: Path | str | None = None,
) -> None:
    """Put the crops where the export's links point.

    Flat, in one folder per book, so the images a section needs can be picked
    out and attached without walking the tree.
    """
    if not figures:
        return
    destination = generate.claim_dir(
        export_root(book_tag, out_dir) / FIGURE_DIRNAME, out_dir
    )
    for figure in figures:
        source = config.WORK_DIR / book_slug / figure.path
        if source.exists():
            shutil.copy2(source, destination / Path(figure.path).name)


def write_prompt(
    book_title: str,
    book_tag: str,
    count: int,
    out_dir: Path | str | None = None,
    domain: str = config.DEFAULT_DOMAIN,
) -> Path:
    """The instructions, once per book, beside the files they apply to."""
    text = generate.render(
        generate.load_prompt("export.md"),
        source=book_title,
        book_tag=book_tag,
        domain=extract.slugify(domain),
        count=count,
    )
    return generate.write_note(
        export_root(book_tag, out_dir) / PROMPT_FILE, text, out_dir
    )


def run(
    chunk: Chunk,
    chapter_title: str,
    *,
    book_slug: str,
    book_title: str,
    book_tag: str,
    figures: Sequence[Figure] | None = None,
    out_dir: Path | str | None = None,
    domain: str = config.DEFAULT_DOMAIN,
) -> Path:
    """Export one chunk. No token budget applies: nothing has to read it here."""
    source_text = chunk.text_path.read_text(encoding="utf-8")
    chunk_figures = generate.figures_for(
        figures if figures is not None else extract.load_figures(book_slug), chunk
    )
    copy_figures(chunk_figures, book_slug, book_tag, out_dir)
    text = assemble(
        chunk,
        source_text,
        figures_block(chunk_figures),
        book_title,
        book_tag,
        domain,
    )
    path = generate.write_note(
        file_path(chunk, chapter_title, book_tag, out_dir), text, out_dir
    )
    log.event(
        "export",
        "section written",
        section=chunk.section,
        path=str(path),
        words=len(source_text.split()),
        figures=len(chunk_figures),
    )
    return path
