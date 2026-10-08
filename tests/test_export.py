# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The export stage: the book's own text, written out without a model."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config, export, generate
from app.chunk import Chunk
from app.extract import Figure

SOURCE = "## 2.3.1 Emitter follower\n\nThe emitter follows the base.\n"


@pytest.fixture
def chunk(tmp_path: Path) -> Chunk:
    text_path = tmp_path / "chunk.md"
    text_path.write_text(SOURCE, encoding="utf-8")
    return Chunk(1, 2, "2.3.1", "Emitter follower", 71, 74, text_path)


def _export(chunk: Chunk, **kwargs: object) -> Path:
    defaults: dict[str, object] = {
        "book_slug": "bk1",
        "book_title": "Book",
        "book_tag": "bk1",
        "figures": [],
        "domain": "electronics",
    }
    return export.run(chunk, "Transistors", **(defaults | kwargs))  # type: ignore[arg-type]


def test_the_export_tree_mirrors_the_notes_tree(chunk: Chunk) -> None:
    path = _export(chunk)
    assert path == (
        config.OUT_DIR
        / "_source"
        / "bk1"
        / "02-transistors"
        / "2.3.1 Emitter follower.md"
    )


def test_a_chunk_without_a_chapter_lands_in_unsorted(tmp_path: Path) -> None:
    text_path = tmp_path / "preface.md"
    text_path.write_text("front matter\n", encoding="utf-8")
    unnumbered = Chunk(1, None, "001", "Preface", 1, 2, text_path)
    assert _export(unnumbered).parent.name == "00-unsorted"


def test_the_source_text_is_copied_through_untouched(chunk: Chunk) -> None:
    text = _export(chunk).read_text(encoding="utf-8")
    assert "## Source text" in text
    assert SOURCE.strip() in text


def test_the_frontmatter_says_what_the_file_is(chunk: Chunk) -> None:
    text = _export(chunk).read_text(encoding="utf-8")
    assert 'source: "Book"' in text
    assert 'section: "2.3.1"' in text
    assert "pages: [71, 74]" in text
    assert "stage: export" in text
    assert "tags: [electronics, bk1, chapter-02]" in text
    # No model ran, so no note claims one did.
    assert "model:" not in text


def test_the_ownership_marker_lets_a_rerun_replace_its_own_files(
    chunk: Chunk,
) -> None:
    text = _export(chunk).read_text(encoding="utf-8")
    assert generate.is_ours_text(text)


def test_a_second_run_writes_the_same_bytes(chunk: Chunk) -> None:
    first = _export(chunk).read_bytes()
    assert _export(chunk).read_bytes() == first


def test_a_foreign_file_at_an_export_path_is_not_overwritten(chunk: Chunk) -> None:
    path = export.file_path(chunk, "Transistors", "bk1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# someone else's file\n", encoding="utf-8")

    with pytest.raises(PermissionError):
        _export(chunk)
    assert path.read_text(encoding="utf-8") == "# someone else's file\n"


def test_only_the_figures_on_the_chunks_pages_are_exported(chunk: Chunk) -> None:
    inside = Figure("a", 72, (0, 0, 1, 1), "Fig 2.10", "", "figures/a.png")
    outside = Figure("b", 90, (0, 0, 1, 1), "Fig 2.40", "", "figures/b.png")

    text = _export(chunk, figures=[inside, outside]).read_text(encoding="utf-8")

    assert "![a.png](../figures/a.png)" in text
    assert "*Fig 2.10*" in text
    assert "b.png" not in text


def test_the_crops_are_copied_into_one_flat_folder(chunk: Chunk) -> None:
    crop = config.WORK_DIR / "bk1" / "figures" / "a.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"not really a png")
    figure = Figure("a", 72, (0, 0, 1, 1), "Fig 2.10", "", "figures/a.png")

    _export(chunk, figures=[figure])

    figures_dir = export.export_root("bk1") / export.FIGURE_DIRNAME
    assert (figures_dir / "a.png").read_bytes() == b"not really a png"
    assert (figures_dir / generate.OWNER_STAMP).exists()


def test_a_section_with_no_figures_has_no_figures_heading(chunk: Chunk) -> None:
    text = _export(chunk).read_text(encoding="utf-8")
    assert "## Figures" not in text
    assert not (export.export_root("bk1") / export.FIGURE_DIRNAME).exists()


def test_the_prompt_is_written_once_beside_the_files() -> None:
    path = export.write_prompt("Book", "bk1", 7, domain="electronics")
    assert path == export.export_root("bk1") / export.PROMPT_FILE

    text = path.read_text(encoding="utf-8")
    assert "7 section(s)" in text
    assert "*Book*" in text
    assert "tags: [electronics, bk1, prompt]" in text
    assert generate.is_ours_text(text)


def test_the_prompt_has_no_leftover_placeholders() -> None:
    text = export.write_prompt("Book", "bk1", 1).read_text(encoding="utf-8")
    assert "{{" not in text


def test_the_prompt_is_rewritable() -> None:
    export.write_prompt("Book", "bk1", 1)
    assert "9 section(s)" in export.write_prompt("Book", "bk1", 9).read_text(
        encoding="utf-8"
    )


def test_an_export_cannot_escape_the_output_folder(tmp_path: Path) -> None:
    with pytest.raises(PermissionError):
        generate.check_writable(export.export_root("../../etc") / "passwd.md")
