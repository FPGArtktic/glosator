# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""SQLite schema and state queries.

One row per (book, chunk, stage, model) in ``stage_runs`` is what makes the
pipeline resumable: a stage that finds its row with status ``done`` skips the
work unless the caller forces a rerun.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app import config

# Applied in order; the list index is the schema version. Append only, never
# edit an existing entry (see docs/DECISIONS.md).
_MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE books (
        id         INTEGER PRIMARY KEY,
        slug       TEXT NOT NULL UNIQUE,
        title      TEXT NOT NULL,
        pdf_path   TEXT NOT NULL,
        created    TEXT NOT NULL
    );

    CREATE TABLE chunks (
        id          INTEGER PRIMARY KEY,
        book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        ord         INTEGER NOT NULL,
        chapter     INTEGER,
        section     TEXT NOT NULL,
        title       TEXT NOT NULL,
        page_start  INTEGER NOT NULL,
        page_end    INTEGER NOT NULL,
        text_path   TEXT NOT NULL,
        UNIQUE (book_id, section)
    );

    CREATE TABLE stage_runs (
        id          INTEGER PRIMARY KEY,
        book_id     INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        chunk_id    INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
        stage       TEXT NOT NULL,
        model       TEXT NOT NULL,
        status      TEXT NOT NULL,
        started     TEXT,
        finished    TEXT,
        output_path TEXT,
        error       TEXT
    );

    -- chunk_id is NULL for book-wide stages and SQLite treats NULLs as
    -- distinct, so the identity of a run is indexed over IFNULL(chunk_id, -1).
    CREATE UNIQUE INDEX idx_stage_runs_key
        ON stage_runs (book_id, IFNULL(chunk_id, -1), stage, model);

    CREATE TABLE jobs (
        id        INTEGER PRIMARY KEY,
        book_id   INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
        stage     TEXT NOT NULL,
        model     TEXT NOT NULL,
        params    TEXT NOT NULL,
        status    TEXT NOT NULL,
        stop      INTEGER NOT NULL DEFAULT 0,
        total     INTEGER NOT NULL DEFAULT 0,
        done      INTEGER NOT NULL DEFAULT 0,
        created   TEXT NOT NULL,
        started   TEXT,
        finished  TEXT,
        error     TEXT
    );

    CREATE INDEX idx_jobs_status ON jobs(status, id);
    """,
    """
    -- The output folder is chosen per book: notes may go to an Obsidian vault,
    -- or to any other directory, and the choice must survive a restart.
    ALTER TABLE books ADD COLUMN out_dir TEXT;
    """,
    """
    -- The field a book belongs to: electronics, mathematics, history. It
    -- reaches the prompts and the first tag of every note.
    ALTER TABLE books ADD COLUMN domain TEXT;
    """,
)

# Stand-in for a NULL chunk_id in lookups and in the unique index. Rows still
# store NULL, so the foreign key to chunks stays intact.
_NULL_CHUNK = -1


def _key(chunk_id: int | None) -> int:
    return _NULL_CHUNK if chunk_id is None else chunk_id


DONE = "done"
FAILED = "failed"
RUNNING = "running"
QUEUED = "queued"
STOPPED = "stopped"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread is off because Gradio serves each request on its own
    # thread; writes are short and WAL handles the concurrency.
    conn = sqlite3.connect(
        path, timeout=30.0, isolation_level=None, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    init(conn)
    return conn


def init(conn: sqlite3.Connection) -> None:
    """Bring an open database up to the current schema version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index in range(version, len(_MIGRATIONS)):
        # BEGIN and COMMIT belong inside the script: executescript commits any
        # transaction opened around it, so an outer BEGIN would be lost.
        conn.executescript(
            f"BEGIN;\n{_MIGRATIONS[index]}\nPRAGMA user_version = {index + 1};\nCOMMIT;"
        )


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def upsert_book(
    conn: sqlite3.Connection,
    slug: str,
    title: str,
    pdf_path: Path,
    out_dir: Path | None = None,
    domain: str | None = None,
) -> int:
    conn.execute(
        """
        INSERT INTO books (slug, title, pdf_path, out_dir, domain, created)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (slug) DO UPDATE SET title = excluded.title,
                                         pdf_path = excluded.pdf_path,
                                         out_dir = excluded.out_dir,
                                         domain = excluded.domain
        """,
        (
            slug,
            title,
            str(pdf_path),
            str(out_dir) if out_dir else None,
            domain,
            _now(),
        ),
    )
    return int(
        conn.execute("SELECT id FROM books WHERE slug = ?", (slug,)).fetchone()[0]
    )


def book_row(conn: sqlite3.Connection, book_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM books WHERE id = ?", (book_id,)).fetchone()
    if row is None:
        raise KeyError(f"no book with id {book_id}")
    return row


def replace_chunks(conn: sqlite3.Connection, book_id: int, chunks: Iterable) -> None:
    """Store the chunk plan, dropping any previous plan for the book.

    Chunk rows carry the note identity, so re-planning deletes the stage rows
    that pointed at the old chunks and the next run regenerates them.
    """
    rows = [
        (
            book_id,
            chunk.ord,
            chunk.chapter,
            chunk.section,
            chunk.title,
            chunk.page_start,
            chunk.page_end,
            str(chunk.text_path),
        )
        for chunk in chunks
    ]
    with transaction(conn):
        conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
        conn.executemany(
            """
            INSERT INTO chunks
                (book_id, ord, chapter, section, title, page_start, page_end, text_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def list_chunks(conn: sqlite3.Connection, book_id: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM chunks WHERE book_id = ? ORDER BY ord", (book_id,)
        ).fetchall()
    )


def stage_done(
    conn: sqlite3.Connection,
    book_id: int,
    chunk_id: int | None,
    stage: str,
    model: str,
) -> bool:
    row = conn.execute(
        """
        SELECT status FROM stage_runs
         WHERE book_id = ? AND IFNULL(chunk_id, -1) = ? AND stage = ? AND model = ?
        """,
        (book_id, _key(chunk_id), stage, model),
    ).fetchone()
    return row is not None and row["status"] == DONE


def stage_start(
    conn: sqlite3.Connection,
    book_id: int,
    chunk_id: int | None,
    stage: str,
    model: str,
) -> None:
    conn.execute(
        """
        INSERT INTO stage_runs
            (book_id, chunk_id, stage, model, status, started)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (book_id, IFNULL(chunk_id, -1), stage, model) DO UPDATE
            SET status = excluded.status,
                started = excluded.started,
                finished = NULL,
                error = NULL
        """,
        (book_id, chunk_id, stage, model, RUNNING, _now()),
    )


def stage_finish(
    conn: sqlite3.Connection,
    book_id: int,
    chunk_id: int | None,
    stage: str,
    model: str,
    status: str,
    output_path: Path | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE stage_runs
           SET status = ?, finished = ?, output_path = ?, error = ?
         WHERE book_id = ? AND IFNULL(chunk_id, -1) = ? AND stage = ? AND model = ?
        """,
        (
            status,
            _now(),
            str(output_path) if output_path else None,
            error,
            book_id,
            _key(chunk_id),
            stage,
            model,
        ),
    )


def clear_stage(
    conn: sqlite3.Connection, book_id: int, stage: str, model: str | None = None
) -> int:
    """Forget a stage's results so ``--force`` reruns it."""
    # The vision stage stores one row per figure as "vision:<figure id>", so a
    # stage name also matches its colon-suffixed variants.
    like = f"{stage}:%"
    if model is None:
        cursor = conn.execute(
            """
            DELETE FROM stage_runs
             WHERE book_id = ? AND (stage = ? OR stage LIKE ?)
            """,
            (book_id, stage, like),
        )
    else:
        cursor = conn.execute(
            """
            DELETE FROM stage_runs
             WHERE book_id = ? AND (stage = ? OR stage LIKE ?) AND model = ?
            """,
            (book_id, stage, like, model),
        )
    return cursor.rowcount


def stage_rows(conn: sqlite3.Connection, book_id: int, stage: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT * FROM stage_runs WHERE book_id = ? AND stage = ? ORDER BY id",
            (book_id, stage),
        ).fetchall()
    )


def enqueue(
    conn: sqlite3.Connection,
    book_id: int,
    stage: str,
    model: str,
    params: str = "{}",
    total: int = 0,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO jobs (book_id, stage, model, params, status, total, created)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (book_id, stage, model, params, QUEUED, total, _now()),
    )
    return int(cursor.lastrowid)


def claim_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Take the oldest queued job. Safe against a second worker process."""
    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY id LIMIT 1", (QUEUED,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE jobs SET status = ?, started = ? WHERE id = ?",
            (RUNNING, _now(), row["id"]),
        )
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()


def job_progress(conn: sqlite3.Connection, job_id: int, done: int, total: int) -> None:
    conn.execute(
        "UPDATE jobs SET done = ?, total = ? WHERE id = ?", (done, total, job_id)
    )


def finish_job(
    conn: sqlite3.Connection, job_id: int, status: str, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE jobs SET status = ?, finished = ?, error = ? WHERE id = ?",
        (status, _now(), error, job_id),
    )


def request_stop(conn: sqlite3.Connection, job_id: int) -> None:
    """Ask a running job to stop after the chunk it is on."""
    conn.execute("UPDATE jobs SET stop = 1 WHERE id = ?", (job_id,))
    conn.execute(
        "UPDATE jobs SET status = ?, finished = ? WHERE id = ? AND status = ?",
        (STOPPED, _now(), job_id, QUEUED),
    )


def stop_all(conn: sqlite3.Connection) -> list[int]:
    """Ask every unfinished job to stop. Returns the ids it asked.

    Stopping only the running job would be no use: the stages of one book are
    queued together, so the next would start a second later.
    """
    rows = conn.execute(
        "SELECT id FROM jobs WHERE status IN (?, ?) ORDER BY id", (QUEUED, RUNNING)
    ).fetchall()
    for row in rows:
        request_stop(conn, row["id"])
    return [int(row["id"]) for row in rows]


def stop_requested(conn: sqlite3.Connection, job_id: int) -> bool:
    row = conn.execute("SELECT stop FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return row is not None and bool(row["stop"])


def clear_finished(conn: sqlite3.Connection) -> int:
    """Forget jobs that are over, so the table shows only live work.

    A failure from an hour ago sitting under a running job reads as a current
    problem. Only the queue rows go; what each stage completed is recorded in
    stage_runs and is what makes a rerun skip finished work.
    """
    cursor = conn.execute(
        "DELETE FROM jobs WHERE status IN (?, ?, ?)", (DONE, FAILED, STOPPED)
    )
    return cursor.rowcount


def recent_jobs(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return list(
        conn.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    )


def reset_running_jobs(conn: sqlite3.Connection) -> None:
    """Settle the jobs a killed worker left marked running.

    One that was asked to stop is finished as stopped: the kill is how the
    stop was carried out, and re-queueing it would start the work again.
    """
    conn.execute(
        "UPDATE jobs SET status = ?, started = NULL WHERE status = ? AND stop = 0",
        (QUEUED, RUNNING),
    )
    conn.execute(
        "UPDATE jobs SET status = ?, finished = ? WHERE status = ? AND stop = 1",
        (STOPPED, _now(), RUNNING),
    )
