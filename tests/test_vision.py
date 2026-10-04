# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Figure pass: description insertion and context selection."""

from __future__ import annotations

import pytest

from app import config, generate, vision
from app.extract import Figure

NOTE = """---
section: "2.3.1"
generator: glosator
---
# 2.3.1 Emitter follower

## Figures

![[attachments/bk1/fig-71-1.png]]
*Fig 2.10 — description pending.*

## Glossary

- bias — polaryzacja
"""


def _figure(caption: str = "Fig 2.10 — follower") -> Figure:
    return Figure(
        "fig-71-1", 71, (0, 0, 1, 1), caption, "2.3.1", "figures/fig-71-1.png"
    )


def test_insert_description_keeps_the_printed_caption() -> None:
    updated = vision.insert_description(
        NOTE, "fig-71-1.png", "A BJT with the load in series."
    )
    assert "*Fig 2.10 — A BJT with the load in series.*" in updated
    assert "description pending" not in updated
    assert "## Glossary" in updated


def test_insert_description_is_rerunnable() -> None:
    once = vision.insert_description(NOTE, "fig-71-1.png", "first")
    twice = vision.insert_description(once, "fig-71-1.png", "second")
    assert "first" not in twice
    assert "*Fig 2.10 — second*" in twice


def test_insert_description_without_a_matching_embed() -> None:
    assert vision.insert_description(NOTE, "fig-99-9.png", "x") == NOTE


def test_insert_description_when_there_is_no_caption_line() -> None:
    note = "![[attachments/bk1/fig-71-1.png]]\n\n## Glossary\n"
    updated = vision.insert_description(note, "fig-71-1.png", "plain")
    assert "*plain*" in updated


def test_context_for_centres_on_the_caption() -> None:
    chunk_text = "a" * 2000 + "Fig 2.10 — follower circuit" + "b" * 2000
    context = vision.context_for(chunk_text, _figure())
    assert "Fig 2.10 — follower circuit" in context
    assert len(context) <= vision.CONTEXT_CHARS


def test_context_for_falls_back_to_the_start() -> None:
    assert vision.context_for("short text", _figure("")) == "short text"


def test_run_writes_the_description_into_the_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crop = config.WORK_DIR / "bk1" / "figures" / "fig-71-1.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"png")
    note_path = config.OUT_DIR / "note.md"
    generate.write_atomic(note_path, NOTE)
    monkeypatch.setattr(vision.ollama, "generate", lambda *_a, **_k: "Two resistors.")

    vision.run(_figure(), note_path, book_slug="bk1", chunk_text="text")

    assert "Two resistors." in note_path.read_text(encoding="utf-8")


def test_run_fails_loudly_on_a_missing_crop() -> None:
    note_path = config.OUT_DIR / "note.md"
    generate.write_atomic(note_path, NOTE)
    with pytest.raises(FileNotFoundError):
        vision.run(_figure(), note_path, book_slug="bk1", chunk_text="text")


def test_run_fails_when_the_note_has_no_embed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crop = config.WORK_DIR / "bk1" / "figures" / "fig-71-1.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"png")
    note_path = config.OUT_DIR / "note.md"
    generate.write_atomic(note_path, "---\ngenerator: glosator\n---\n# note\n")
    monkeypatch.setattr(vision.ollama, "generate", lambda *_a, **_k: "text")
    with pytest.raises(ValueError, match="no embed"):
        vision.run(_figure(), note_path, book_slug="bk1", chunk_text="text")
