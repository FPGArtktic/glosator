# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Optional figure pass: one vision call per crop, inserted into its note.

Runs as its own pass over the whole book. Only one model fits in 4 GB of VRAM,
so text and vision calls must never interleave per chunk.
"""

from __future__ import annotations

import re
from pathlib import Path

from app import config, generate, log, ollama
from app.extract import Figure

# Characters of surrounding source text handed to the vision model. Enough to
# name the circuit, small enough to leave room for the image tokens.
CONTEXT_CHARS = 1200


def insert_description(note_text: str, figure_file: str, description: str) -> str:
    """Replace the placeholder caption under one embed.

    Keeps the printed caption that precedes the em dash, so a second vision
    run overwrites the description and nothing else.
    """
    embed = re.compile(
        r"(!\[\[attachments/[^\]]*/" + re.escape(figure_file) + r"\]\]\n)(\*.*\*\n?)?"
    )
    match = embed.search(note_text)
    if match is None:
        return note_text

    previous = (match.group(2) or "").strip().strip("*")
    printed_caption = previous.split(" — ")[0].strip() if previous else ""
    caption = (
        f"*{printed_caption} — {description}*"
        if printed_caption
        else f"*{description}*"
    )
    return (
        note_text[: match.start()]
        + match.group(1)
        + caption
        + "\n"
        + note_text[match.end() :]
    )


def context_for(chunk_text: str, figure: Figure) -> str:
    """Source text near the figure, by caption match, else the chunk's start."""
    if figure.caption:
        position = chunk_text.find(figure.caption[:40])
        if position >= 0:
            start = max(0, position - CONTEXT_CHARS // 2)
            return chunk_text[start : start + CONTEXT_CHARS]
    return chunk_text[:CONTEXT_CHARS]


def describe(
    figure: Figure,
    book_slug: str,
    context: str,
    model: str = config.VISION_MODEL,
    domain: str = config.DEFAULT_DOMAIN,
) -> str:
    image = config.WORK_DIR / book_slug / figure.path
    if not image.exists():
        raise FileNotFoundError(f"missing crop {image}")
    prompt = generate.render(
        generate.load_prompt("figure.md"),
        heading=figure.heading or "unknown",
        caption=figure.caption or "none printed",
        context=context,
        domain=domain,
    )
    return " ".join(ollama.generate(model, prompt, images=[image]).split())


def run(
    figure: Figure,
    note_path: Path,
    *,
    book_slug: str,
    chunk_text: str,
    model: str = config.VISION_MODEL,
    out_dir: Path | str | None = None,
    domain: str = config.DEFAULT_DOMAIN,
) -> Path:
    """Describe one figure and write the description into its note."""
    description = describe(
        figure, book_slug, context_for(chunk_text, figure), model, domain
    )
    note_text = note_path.read_text(encoding="utf-8")
    updated = insert_description(note_text, Path(figure.path).name, description)
    if updated == note_text:
        raise ValueError(f"{note_path.name}: no embed for {figure.id}")
    generate.write_note(note_path, updated, out_dir)
    log.event("vision", "figure described", figure=figure.id, note=str(note_path))
    return note_path
