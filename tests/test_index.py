# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Index stage: glossary merge, navigation footers, chapter MOCs."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config, generate, index
from app.chunk import Chunk

NOTE = """---
section: "2.3.1"
generator: glosator
---
# 2.3.1 Emitter follower

## Glossary

- emitter follower — wtórnik emiterowy
- bias - polaryzacja

## Pitfalls

none
"""


def test_parse_glossary_accepts_dash_and_em_dash() -> None:
    assert index.parse_glossary(NOTE) == [
        ("emitter follower", "wtórnik emiterowy"),
        ("bias", "polaryzacja"),
    ]


def test_parse_glossary_of_a_note_without_one() -> None:
    assert index.parse_glossary("# title\n\n## In short\n\nx\n") == []


def test_merge_glossary_keeps_sources_and_drops_duplicates() -> None:
    merged = index.merge_glossary(
        [
            ("2.3.1 Emitter follower", ("bias", "polaryzacja")),
            ("2.3.2 Current source", ("Bias", "polaryzacja")),
            ("2.3.2 Current source", ("gain", "wzmocnienie")),
        ]
    )
    assert [entry[0] for entry in merged] == ["bias", "gain"]
    assert merged[0][2] == ["2.3.1 Emitter follower", "2.3.2 Current source"]


def test_glossary_note_links_back_to_the_notes() -> None:
    text = index.glossary_note(
        [("bias", "polaryzacja", ["2.3.1 X"])], "Book", "bk1", "electronics"
    )
    assert "- **bias** — polaryzacja" in text
    assert "[[2.3.1 X]]" in text
    assert "tags: [electronics, bk1, glossary]" in text


def test_apply_nav_is_idempotent() -> None:
    once = index.apply_nav("body\n", "2.3 Prev", "2.3.2 Next")
    twice = index.apply_nav(once, "2.3 Prev", "2.3.2 Next")
    assert once == twice
    assert once.endswith("[[2.3 Prev]] · [[2.3.2 Next]]\n")


def test_apply_nav_replaces_stale_links() -> None:
    stale = index.apply_nav("body\n", "old", "older")
    fresh = index.apply_nav(stale, "2.1 A", None)
    assert "old" not in fresh
    assert fresh.endswith("[[2.1 A]]\n")


def test_apply_nav_without_neighbours_removes_the_footer() -> None:
    stale = index.apply_nav("body\n", "a", "b")
    assert index.apply_nav(stale, None, None).strip() == "body"


def _chunk(order: int, section: str, title: str, page: int) -> Chunk:
    return Chunk(order, 2, section, title, page, page, Path("x.md"))


def test_run_links_notes_writes_moc_and_glossary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunks = [
        _chunk(1, "2.3.1", "Emitter follower", 71),
        _chunk(2, "2.3.2", "Current source", 75),
    ]
    titles = {2: "Transistors"}
    for chunk in chunks:
        generate.write_atomic(generate.note_path(chunk, titles[2]), NOTE)

    written = index.run(chunks, titles, book_title="Book", book_tag="bk1")

    first = generate.note_path(chunks[0], titles[2]).read_text(encoding="utf-8")
    assert first.rstrip().endswith("[[2.3.2 Current source]]")
    moc = (config.OUT_DIR / "02-transistors" / "02 Transistors.md").read_text(
        encoding="utf-8"
    )
    assert "[[2.3.1 Emitter follower]]" in moc
    assert "chapter: 2" in moc
    glossary = (config.OUT_DIR / index.GLOSSARY_NOTE).read_text(encoding="utf-8")
    assert "wtórnik emiterowy" in glossary
    assert len(written) == 4


def test_run_skips_chunks_without_a_note() -> None:
    chunks = [_chunk(1, "2.3.1", "Emitter follower", 71)]
    written = index.run(chunks, {2: "Transistors"}, book_title="Book", book_tag="bk1")
    assert written == [config.OUT_DIR / index.GLOSSARY_NOTE]


def test_run_leaves_a_foreign_file_at_a_note_path_alone() -> None:
    chunks = [
        _chunk(1, "2.3.1", "Emitter follower", 71),
        _chunk(2, "2.3.2", "Current source", 75),
    ]
    titles = {2: "Transistors"}
    mine = generate.note_path(chunks[0], titles[2])
    mine.parent.mkdir(parents=True, exist_ok=True)
    mine.write_text("hand-written, not glosator's\n", encoding="utf-8")
    generate.write_atomic(generate.note_path(chunks[1], titles[2]), NOTE)

    index.run(chunks, titles, book_title="Book", book_tag="bk1")

    assert mine.read_text(encoding="utf-8") == "hand-written, not glosator's\n"
    other = generate.note_path(chunks[1], titles[2]).read_text(encoding="utf-8")
    assert "[[2.3.1 Emitter follower]]" not in other


def test_run_writes_into_the_given_output_folder(tmp_path: Path) -> None:
    elsewhere = tmp_path / "notes-elsewhere"
    elsewhere.mkdir()
    chunks = [_chunk(1, "2.3.1", "Emitter follower", 71)]
    titles = {2: "Transistors"}
    generate.write_note(
        generate.note_path(chunks[0], titles[2], elsewhere), NOTE, elsewhere
    )

    written = index.run(
        chunks, titles, book_title="Book", book_tag="bk1", out_dir=elsewhere
    )

    assert all(path.is_relative_to(elsewhere) for path in written)
    assert (elsewhere / index.GLOSSARY_NOTE).exists()
    assert not (config.OUT_DIR / index.GLOSSARY_NOTE).exists()


def test_moc_of_an_unnamed_chapter_is_named_by_its_number() -> None:
    chunks = [
        Chunk(1, 4, "4.07", "Limits of the sampling method", 99, 102, Path("x.md"))
    ]
    generate.write_note(generate.note_path(chunks[0], ""), NOTE)

    index.run(chunks, {4: ""}, book_title="Book", book_tag="isp2")

    assert (config.OUT_DIR / "04" / "04.md").exists()
    assert not (config.OUT_DIR / "04" / "04 .md").exists()
