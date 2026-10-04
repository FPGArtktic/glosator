# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Chapter maps of content, the global glossary and prev/next links.

Deterministic: no model is involved, so this stage can be rerun after any
regeneration without changing anything else in the output folder.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from app import config, generate, log
from app.chunk import Chunk

GLOSSARY_LINE_RE = re.compile(r"^\s*[-*]\s+(.+?)\s+[—-]\s+(.+?)\s*$")
# The footer is the trailing "---" line plus the one link line under it.
NAV_RE = re.compile(r"\n---\n[^\n]*\[\[[^\n]*\n?\s*$")
GLOSSARY_NOTE = "_Glossary.md"


def note_name(chunk: Chunk) -> str:
    """Wikilink target of a chunk's note: the file stem."""
    return f"{chunk.section} {chunk.title}".strip()


def parse_glossary(note_text: str) -> list[tuple[str, str]]:
    """``- emitter follower — wtórnik emiterowy`` pairs from one note."""
    sections = generate.split_sections(note_text)
    entries: list[tuple[str, str]] = []
    for line in sections.get("Glossary", "").splitlines():
        match = GLOSSARY_LINE_RE.match(line)
        if match:
            entries.append((match.group(1).strip(), match.group(2).strip()))
    return entries


def merge_glossary(
    per_note: Sequence[tuple[str, tuple[str, str]]],
) -> list[tuple[str, str, list[str]]]:
    """Collapse duplicates across notes, keeping where each term was defined."""
    merged: dict[str, tuple[str, str, list[str]]] = {}
    for source, (term, translation) in per_note:
        key = term.casefold()
        if key not in merged:
            merged[key] = (term, translation, [source])
        elif source not in merged[key][2]:
            merged[key][2].append(source)
    return sorted(merged.values(), key=lambda entry: entry[0].casefold())


def glossary_note(
    entries: Sequence[tuple[str, str, list[str]]],
    book_title: str,
    book_tag: str,
    domain: str = config.DEFAULT_DOMAIN,
) -> str:
    lines = [
        "---",
        f'source: "{book_title}"',
        "type: glossary",
        f"generator: {generate.GENERATOR}",
        f"tags: [{generate.extract.slugify(domain)}, {book_tag}, glossary]",
        "---",
        "# Glossary",
        "",
    ]
    for term, translation, sources in entries:
        links = " ".join(f"[[{source}]]" for source in sources)
        lines.append(f"- **{term}** — {translation}  {links}")
    return "\n".join(lines) + "\n"


def nav_footer(previous: str | None, following: str | None) -> str:
    links = [
        f"[[{previous}]]" if previous else "",
        f"[[{following}]]" if following else "",
    ]
    return "\n---\n" + " · ".join(link for link in links if link) + "\n"


def apply_nav(note_text: str, previous: str | None, following: str | None) -> str:
    """Replace the note's footer, or add one. Idempotent."""
    body = NAV_RE.sub("", note_text.rstrip()) + "\n"
    if not previous and not following:
        return body
    return body.rstrip() + "\n" + nav_footer(previous, following)


def chapter_moc(
    chapter: int,
    title: str,
    chunks: Sequence[Chunk],
    book_title: str,
    book_tag: str,
    domain: str = config.DEFAULT_DOMAIN,
) -> str:
    entries = "\n".join(
        f"- [[{note_name(chunk)}]] — pages {chunk.page_start}-{chunk.page_end}"
        for chunk in chunks
    )
    return generate.render(
        generate.load_prompt("moc.md"),
        source=book_title,
        chapter=chapter,
        chapter_pad=f"{chapter:02d}",
        title=title,
        book_tag=book_tag,
        domain=domain,
        entries=entries,
    )


def run(
    chunks: Sequence[Chunk],
    chapter_titles: dict[int, str],
    *,
    book_title: str,
    book_tag: str,
    out_dir: Path | str | None = None,
    domain: str = config.DEFAULT_DOMAIN,
) -> list[Path]:
    """Write MOCs and the glossary, and link every note to its neighbours.

    Only notes glosator wrote take part. A file sitting at a note's path that
    carries no generator marker is skipped, not rewritten.
    """
    written: list[Path] = []
    existing = [
        (
            chunk,
            generate.note_path(
                chunk, chapter_titles.get(chunk.chapter or 0, ""), out_dir
            ),
        )
        for chunk in chunks
    ]
    present = [
        (chunk, path)
        for chunk, path in existing
        if path.exists() and generate.is_ours(path)
    ]
    skipped = [path for _chunk, path in existing if path.exists()]

    for position, (_chunk, path) in enumerate(present):
        previous = note_name(present[position - 1][0]) if position else None
        following = (
            note_name(present[position + 1][0]) if position + 1 < len(present) else None
        )
        text = path.read_text(encoding="utf-8")
        updated = apply_nav(text, previous, following)
        if updated != text:
            generate.write_note(path, updated, out_dir)
        written.append(path)

    for chapter in sorted({chunk.chapter for chunk, _ in present if chunk.chapter}):
        in_chapter = [chunk for chunk, _ in present if chunk.chapter == chapter]
        title = chapter_titles.get(chapter, "")
        moc_name = f"{chapter:02d} {title}".strip()
        moc_path = (
            generate.note_path(in_chapter[0], title, out_dir).parent / f"{moc_name}.md"
        )
        generate.write_note(
            moc_path,
            chapter_moc(chapter, title, in_chapter, book_title, book_tag, domain),
            out_dir,
        )
        written.append(moc_path)

    pairs = [
        (note_name(chunk), entry)
        for chunk, path in present
        for entry in parse_glossary(path.read_text(encoding="utf-8"))
    ]
    glossary_path = generate.out_root(out_dir) / GLOSSARY_NOTE
    generate.write_note(
        glossary_path,
        glossary_note(merge_glossary(pairs), book_title, book_tag),
        out_dir,
    )
    written.append(glossary_path)

    log.event(
        "index",
        "index written",
        notes=len(present),
        files=len(written),
        foreign=len(skipped) - len(present),
    )
    return written
