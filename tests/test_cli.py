# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The CLI only registers books and queues jobs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import cli, config, db


def _jobs() -> list:
    conn = db.connect()
    try:
        return db.recent_jobs(conn)
    finally:
        conn.close()


def test_add_then_queue_extract() -> None:
    assert cli.main(["add", "/in/book.pdf", "--title", "Example Textbook"]) == 0
    assert (
        cli.main(["extract", "--book", "example-textbook", "--pages", "71-96,100-104"])
        == 0
    )

    job = _jobs()[0]
    assert job["stage"] == "extract"
    assert job["status"] == db.QUEUED
    params = json.loads(job["params"])
    assert params["first_page"] == 71
    assert params["last_page"] == 104
    assert params["ocr_langs"] == config.OCR_LANGS


def test_queue_generate_uses_the_configured_text_model() -> None:
    cli.main(["add", "/in/book.pdf", "--title", "Book", "--slug", "bk1"])
    cli.main(["generate", "--book", "bk1"])
    assert _jobs()[0]["model"] == config.TEXT_MODEL


def test_queue_vision_uses_the_configured_vision_model() -> None:
    cli.main(["add", "/in/book.pdf", "--title", "Book", "--slug", "bk1"])
    cli.main(["vision", "--book", "bk1"])
    assert _jobs()[0]["model"] == config.VISION_MODEL


def test_force_clears_previous_stage_rows() -> None:
    cli.main(["add", "/in/book.pdf", "--title", "Book", "--slug", "bk1"])
    conn = db.connect()
    book_id = conn.execute("SELECT id FROM books WHERE slug = 'bk1'").fetchone()[0]
    db.stage_start(conn, book_id, None, "generate", config.TEXT_MODEL)
    db.stage_finish(conn, book_id, None, "generate", config.TEXT_MODEL, db.DONE)
    conn.close()

    cli.main(["generate", "--book", "bk1", "--force"])

    conn = db.connect()
    assert db.stage_rows(conn, book_id, "generate") == []
    assert json.loads(db.recent_jobs(conn)[0]["params"])["force"] is True
    conn.close()


def test_chunk_with_page_ranges() -> None:
    cli.main(["add", "/in/book.pdf", "--title", "Book", "--slug", "bk1"])
    cli.main(["chunk", "--book", "bk1", "--pages", "71-96"])
    assert json.loads(_jobs()[0]["params"])["page_ranges"] == [[71, 96]]


def test_unknown_book_is_refused() -> None:
    with pytest.raises(SystemExit):
        cli.main(["generate", "--book", "nope"])


def test_add_stores_the_resolved_pdf_path(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"%PDF-1.7\n")
    cli.main(["add", str(pdf), "--title", "Book", "--slug", "bk1"])
    conn = db.connect()
    assert conn.execute("SELECT pdf_path FROM books").fetchone()[0] == str(pdf)
    conn.close()


def test_add_records_the_output_folder(tmp_path: Path) -> None:
    notes = tmp_path / "my notes"
    notes.mkdir()
    cli.main(
        [
            "add",
            "/in/book.pdf",
            "--title",
            "Book",
            "--slug",
            "bk1",
            "--out",
            str(notes),
        ]
    )
    conn = db.connect()
    assert conn.execute("SELECT out_dir FROM books").fetchone()[0] == str(notes)
    conn.close()


def test_add_without_an_output_folder_leaves_it_unset() -> None:
    cli.main(["add", "/in/book.pdf", "--title", "Book", "--slug", "bk1"])
    conn = db.connect()
    assert conn.execute("SELECT out_dir FROM books").fetchone()[0] is None
    conn.close()


def test_add_records_the_field_the_book_belongs_to() -> None:
    cli.main(
        [
            "add",
            "/in/calculus.pdf",
            "--title",
            "Example Textbook",
            "--slug",
            "calc1",
            "--domain",
            "calculus",
        ]
    )
    conn = db.connect()
    assert conn.execute("SELECT domain FROM books").fetchone()[0] == "calculus"
    conn.close()
