# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""State: migrations, stage bookkeeping and the job queue."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import db
from app.chunk import Chunk


@pytest.fixture
def conn():
    connection = db.connect()
    yield connection
    connection.close()


def _chunks() -> list[Chunk]:
    return [
        Chunk(1, 2, "2.1", "Basics", 71, 74, Path("/work/bk1/chunks/001-2-1.md")),
        Chunk(2, 2, "2.2", "More", 75, 80, Path("/work/bk1/chunks/002-2-2.md")),
    ]


def test_init_is_idempotent(conn) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    db.init(conn)
    db.init(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == version


def test_upsert_book_updates_in_place(conn) -> None:
    first = db.upsert_book(conn, "bk1", "Old title", Path("/in/a.pdf"))
    second = db.upsert_book(conn, "bk1", "New title", Path("/in/b.pdf"))
    assert first == second
    assert db.book_row(conn, first)["title"] == "New title"
    with pytest.raises(KeyError):
        db.book_row(conn, 999)


def test_replace_chunks_overwrites_the_plan(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    db.replace_chunks(conn, book, _chunks())
    db.replace_chunks(conn, book, _chunks()[:1])
    rows = db.list_chunks(conn, book)
    assert [row["section"] for row in rows] == ["2.1"]


def test_stage_round_trip_for_a_chunk(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    db.replace_chunks(conn, book, _chunks())
    chunk_id = db.list_chunks(conn, book)[0]["id"]

    assert not db.stage_done(conn, book, chunk_id, "generate", "gemma3")
    db.stage_start(conn, book, chunk_id, "generate", "gemma3")
    assert not db.stage_done(conn, book, chunk_id, "generate", "gemma3")
    db.stage_finish(
        conn, book, chunk_id, "generate", "gemma3", db.DONE, Path("/vault/n.md")
    )
    assert db.stage_done(conn, book, chunk_id, "generate", "gemma3")
    # A different model is a different row: switching models regenerates.
    assert not db.stage_done(conn, book, chunk_id, "generate", "qwen")


def test_stage_round_trip_for_the_whole_book(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    db.stage_start(conn, book, None, "extract", "none")
    db.stage_finish(conn, book, None, "extract", "none", db.DONE)
    assert db.stage_done(conn, book, None, "extract", "none")
    db.stage_start(conn, book, None, "extract", "none")
    assert not db.stage_done(conn, book, None, "extract", "none")
    assert len(db.stage_rows(conn, book, "extract")) == 1


def test_stage_finish_records_the_error(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    db.stage_start(conn, book, None, "index", "none")
    db.stage_finish(conn, book, None, "index", "none", db.FAILED, error="boom")
    row = db.stage_rows(conn, book, "index")[0]
    assert row["status"] == db.FAILED
    assert row["error"] == "boom"


def test_clear_stage_also_clears_per_figure_rows(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    for stage in ("vision", "vision:fig-2-1", "generate"):
        db.stage_start(conn, book, None, stage, "qwen")
        db.stage_finish(conn, book, None, stage, "qwen", db.DONE)
    assert db.clear_stage(conn, book, "vision") == 2
    assert db.stage_done(conn, book, None, "generate", "qwen")


def test_job_queue_claim_and_finish(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    first = db.enqueue(conn, book, "generate", "gemma3", "{}", total=10)
    second = db.enqueue(conn, book, "index", "none")

    claimed = db.claim_job(conn)
    assert claimed["id"] == first
    assert claimed["status"] == db.RUNNING
    assert db.claim_job(conn)["id"] == second
    assert db.claim_job(conn) is None

    db.job_progress(conn, first, 3, 10)
    db.finish_job(conn, first, db.DONE)
    rows = {job["id"]: job for job in db.recent_jobs(conn)}
    assert rows[first]["done"] == 3
    assert rows[first]["status"] == db.DONE


def test_stop_request_marks_a_queued_job_stopped(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    job = db.enqueue(conn, book, "generate", "gemma3")
    db.request_stop(conn, job)
    assert db.stop_requested(conn, job)
    assert db.recent_jobs(conn)[0]["status"] == db.STOPPED
    assert db.claim_job(conn) is None


def test_stop_request_leaves_a_running_job_to_finish_its_chunk(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    job = db.enqueue(conn, book, "generate", "gemma3")
    db.claim_job(conn)
    db.request_stop(conn, job)
    assert db.recent_jobs(conn)[0]["status"] == db.RUNNING
    assert db.stop_requested(conn, job)


def test_reset_running_jobs_requeues_after_a_crash(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    job = db.enqueue(conn, book, "generate", "gemma3")
    db.claim_job(conn)
    db.reset_running_jobs(conn)
    assert db.claim_job(conn)["id"] == job


def test_reset_running_jobs_leaves_stopped_jobs_alone(conn) -> None:
    book = db.upsert_book(conn, "bk1", "Book", Path("/in/a.pdf"))
    job = db.enqueue(conn, book, "generate", "gemma3")
    db.claim_job(conn)
    db.request_stop(conn, job)
    db.reset_running_jobs(conn)
    assert db.claim_job(conn) is None


def test_a_killed_job_that_was_asked_to_stop_is_not_restarted(conn) -> None:
    # Killing the worker is how a hard stop is carried out; re-queueing the
    # job afterwards would start the work the user just stopped.
    book = db.upsert_book(conn, "bk1", "Example Textbook", Path("/in/a.pdf"))
    job = db.enqueue(conn, book, "generate", "gemma3")
    db.claim_job(conn)
    db.request_stop(conn, job)

    db.reset_running_jobs(conn)

    assert db.recent_jobs(conn)[0]["status"] == db.STOPPED
    assert db.claim_job(conn) is None


def test_clear_finished_keeps_live_jobs_and_the_stage_record(conn) -> None:
    # An hour-old failure under a running job reads as a current problem.
    book = db.upsert_book(conn, "bk1", "Example Textbook", Path("/in/a.pdf"))
    done = db.enqueue(conn, book, "extract", "none")
    running = db.enqueue(conn, book, "generate", "gemma3")
    waiting = db.enqueue(conn, book, "index", "none")
    db.claim_job(conn)
    db.finish_job(conn, done, db.FAILED, "boom")
    db.claim_job(conn)
    db.stage_start(conn, book, None, "extract", "none")
    db.stage_finish(conn, book, None, "extract", "none", db.DONE)

    assert db.clear_finished(conn) == 1

    assert sorted(job["id"] for job in db.recent_jobs(conn)) == [running, waiting]
    assert db.stage_done(conn, book, None, "extract", "none")
