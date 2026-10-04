# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The UI is wiring, not logic. These tests guard the parts that break silently."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

gradio = pytest.importorskip("gradio", reason="gradio is not installed")

from app import config, ui  # noqa: E402


def test_launch_options_are_accepted_by_the_installed_gradio() -> None:
    # gradio 6 dropped show_api, and the container died on startup with a
    # TypeError that no test saw, because nothing ever called launch().
    accepted = inspect.signature(gradio.Blocks.launch).parameters
    unknown = [name for name in ui.LAUNCH_OPTIONS if name not in accepted]
    assert unknown == []


def test_the_blocks_tree_builds() -> None:
    blocks = ui.build()
    assert len(blocks.blocks) > 0


def test_pdf_choices_lists_only_pdfs(tmp_path: Path) -> None:
    (tmp_path / "book.pdf").write_bytes(b"%PDF-1.7\n")
    (tmp_path / "notes.txt").write_text("not a book")
    assert ui.pdf_choices(tmp_path) == ["book.pdf"]


def test_pdf_choices_of_a_missing_folder(tmp_path: Path) -> None:
    assert ui.pdf_choices(tmp_path / "gone") == []


def test_resolve_out_dir_refuses_a_folder_that_does_not_exist(tmp_path: Path) -> None:
    with pytest.raises(gradio.Error):
        ui.resolve_out_dir(str(tmp_path / "typo"))


def test_resolve_out_dir_returns_an_absolute_path(tmp_path: Path) -> None:
    assert ui.resolve_out_dir(str(tmp_path)) == tmp_path.resolve()


def test_label_to_title_strips_the_page_number() -> None:
    assert ui.label_to_title("    2.3 Followers  (p. 74)") == "2.3 Followers"
    assert ui.label_to_title("Appendix A") == "Appendix A"


def test_last_note_ignores_files_glosator_did_not_write(tmp_path: Path) -> None:
    (tmp_path / "theirs.md").write_text("hand-written", encoding="utf-8")
    assert ui.last_note(tmp_path) == "_no notes yet_"
    (tmp_path / "ours.md").write_text(
        f"---\ngenerator: {ui.generate.GENERATOR}\n---\n# note\n", encoding="utf-8"
    )
    assert "# note" in ui.last_note(tmp_path)


def test_last_note_of_a_missing_folder(tmp_path: Path) -> None:
    assert ui.last_note(tmp_path / "gone") == "_notes folder not found_"


def test_job_table_has_a_row_per_job() -> None:
    from app import db

    conn = db.connect()
    book = db.upsert_book(conn, "bk1", "Example Textbook", Path("/in/a.pdf"))
    db.enqueue(conn, book, "generate", config.TEXT_MODEL)
    rows = ui.job_table(conn)
    conn.close()

    assert len(rows) == 1
    assert rows[0][1] == "generate"
    assert rows[0][2] == db.QUEUED
