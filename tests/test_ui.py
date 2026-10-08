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


def test_stop_without_an_id_stops_everything_pending() -> None:
    # What pressing Stop with an empty field used to do: raise "give a job id"
    # at someone who was watching a job go wrong.
    from app import db

    conn = db.connect()
    book = db.upsert_book(conn, "bk1", "Example Textbook", Path("/in/a.pdf"))
    first = db.enqueue(conn, book, "extract", "none")
    second = db.enqueue(conn, book, "generate", config.TEXT_MODEL)
    db.claim_job(conn)

    message = ui.stop_jobs(conn, None)

    assert str(first) in message and str(second) in message
    assert db.stop_requested(conn, first)
    assert db.stop_requested(conn, second)
    conn.close()


def test_stop_with_an_id_stops_only_that_job() -> None:
    from app import db

    conn = db.connect()
    book = db.upsert_book(conn, "bk1", "Example Textbook", Path("/in/a.pdf"))
    first = db.enqueue(conn, book, "extract", "none")
    second = db.enqueue(conn, book, "generate", config.TEXT_MODEL)

    ui.stop_jobs(conn, second)

    assert not db.stop_requested(conn, first)
    assert db.stop_requested(conn, second)
    conn.close()


def test_stop_when_there_is_nothing_to_stop() -> None:
    from app import db

    conn = db.connect()
    assert "Nothing to stop" in ui.stop_jobs(conn, None)
    conn.close()


def test_the_table_shows_a_pending_stop_as_stopping() -> None:
    # A running job that has been asked to stop looked exactly like one that
    # had not, so pressing stop appeared to do nothing for several minutes.
    from app import db

    conn = db.connect()
    book = db.upsert_book(conn, "bk1", "Example Textbook", Path("/in/a.pdf"))
    job = db.enqueue(conn, book, "generate", config.TEXT_MODEL)
    db.claim_job(conn)
    db.request_stop(conn, job)

    assert ui.job_table(conn)[0][2] == "stopping"
    conn.close()


def test_a_hard_stop_without_a_worker_falls_back_to_the_graceful_one() -> None:
    from app import db

    conn = db.connect()
    book = db.upsert_book(conn, "bk1", "Example Textbook", Path("/in/a.pdf"))
    db.enqueue(conn, book, "generate", config.TEXT_MODEL)

    message = ui.stop_jobs(conn, None, hard=True)

    assert "finishes the chunk it is on first" in message
    conn.close()


def test_clearing_finished_jobs_leaves_the_running_one() -> None:
    from app import db

    conn = db.connect()
    book = db.upsert_book(conn, "bk1", "Example Textbook", Path("/in/a.pdf"))
    old = db.enqueue(conn, book, "index", "none")
    db.claim_job(conn)
    db.finish_job(conn, old, db.FAILED, "an hour ago")
    db.enqueue(conn, book, "generate", config.TEXT_MODEL)
    db.claim_job(conn)

    db.clear_finished(conn)

    rows = ui.job_table(conn)
    assert [row[1] for row in rows] == ["generate"]
    conn.close()


def test_last_note_ignores_the_export_tree(tmp_path: Path) -> None:
    """The export files carry the same marker but nothing wrote them."""
    exported = tmp_path / ui.export.EXPORT_DIRNAME / "bk1" / "02"
    exported.mkdir(parents=True)
    (exported / "2.1 Basics.md").write_text(
        f"---\ngenerator: {ui.generate.GENERATOR}\nstage: export\n---\n# source\n",
        encoding="utf-8",
    )
    assert ui.last_note(tmp_path) == "_no notes yet_"
