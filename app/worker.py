# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Queue consumer. Runs in its own process so the UI can come and go.

Every unit of work is guarded by a ``stage_runs`` row, so a job that is
re-queued after a crash picks up where it stopped.
"""

from __future__ import annotations

import json
import signal
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app import chunk as chunk_module
from app import config, db, export, extract, generate, index, log, ollama, vision

_running = True

Params = dict[str, Any]


def main() -> None:
    config.ensure_dirs()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    conn = db.connect()
    db.reset_running_jobs(conn)
    log.event("worker", "started")

    while _running:
        job = db.claim_job(conn)
        if job is None:
            time.sleep(config.WORKER_POLL_S)
            continue
        _run_job(conn, job)

    log.event("worker", "stopped")


def _stop(_signum: int, _frame: object) -> None:
    global _running
    _running = False


def _run_job(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    stage = job["stage"]
    handlers: dict[str, Callable[[sqlite3.Connection, sqlite3.Row], None]] = {
        "extract": _do_extract,
        "chunk": _do_chunk,
        "generate": _do_generate,
        "vision": _do_vision,
        "index": _do_index,
        "export": _do_export,
    }
    handler = handlers.get(stage)
    if handler is None:
        db.finish_job(conn, job["id"], db.FAILED, f"unknown stage {stage}")
        return

    log.event(
        "worker", "job started", job=job["id"], job_stage=stage, model=job["model"]
    )
    try:
        handler(conn, job)
    except Exception as error:  # a failed job must not take the worker down
        db.finish_job(conn, job["id"], db.FAILED, repr(error))
        log.event(
            "worker", "job failed", job=job["id"], job_stage=stage, error=repr(error)
        )
        _release_vram(stage, job["model"])
        return

    status = db.STOPPED if db.stop_requested(conn, job["id"]) else db.DONE
    db.finish_job(conn, job["id"], status)
    log.event("worker", "job finished", job=job["id"], job_stage=stage, status=status)
    _release_vram(stage, job["model"])


# Stages that load a model into VRAM. The rest never touch the GPU.
_MODEL_STAGES = frozenset({"generate", "vision"})


def _release_vram(stage: str, model: str) -> None:
    """Hand the card back when a job ends.

    A model stays resident between the chunks of one job, because reloading
    eight gigabytes per chunk would dominate the run. Between jobs it must
    not: this machine runs other local models and glosator is a batch job,
    not a service.
    """
    if stage in _MODEL_STAGES:
        ollama.unload(model)


def _params(job: sqlite3.Row) -> Params:
    return json.loads(job["params"])


def _book(conn: sqlite3.Connection, job: sqlite3.Row) -> sqlite3.Row:
    return db.book_row(conn, job["book_id"])


def _domain(book: sqlite3.Row) -> str:
    """The field this book belongs to, for the prompts and the note tags."""
    return book["domain"] or config.DEFAULT_DOMAIN


def _out_dir(book: sqlite3.Row) -> Path:
    """Where this book's notes go. Falls back to the configured mount."""
    return Path(book["out_dir"]) if book["out_dir"] else config.OUT_DIR


def _do_extract(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    book = _book(conn, job)
    params = _params(job)
    db.stage_start(conn, job["book_id"], None, "extract", job["model"])
    result = extract.run(
        book["slug"],
        Path(book["pdf_path"]),
        params["first_page"],
        params["last_page"],
        params.get("ocr_langs", config.OCR_LANGS),
    )
    db.job_progress(conn, job["id"], 1, 1)
    db.stage_finish(
        conn, job["book_id"], None, "extract", job["model"], db.DONE, result.book_dir
    )


def _do_chunk(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    book = _book(conn, job)
    params = _params(job)
    db.stage_start(conn, job["book_id"], None, "chunk", job["model"])
    ranges = [tuple(pair) for pair in params.get("page_ranges") or []]
    chunks = chunk_module.plan(
        book["slug"],
        Path(book["pdf_path"]),
        selected=params.get("sections"),
        page_ranges=ranges or None,
    )
    db.replace_chunks(conn, job["book_id"], chunks)
    db.job_progress(conn, job["id"], len(chunks), len(chunks))
    db.stage_finish(conn, job["book_id"], None, "chunk", job["model"], db.DONE)


def _do_generate(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    book = _book(conn, job)
    model = job["model"]
    force = bool(_params(job).get("force"))
    chunks = chunk_module.load_plan(book["slug"])
    titles = chunk_module.chapter_titles(chunks)
    figures = extract.load_figures(book["slug"])
    rows = {row["section"]: row["id"] for row in db.list_chunks(conn, job["book_id"])}

    db.job_progress(conn, job["id"], 0, len(chunks))
    for position, item in enumerate(chunks, start=1):
        if db.stop_requested(conn, job["id"]):
            return
        chunk_id = rows.get(item.section)
        if not force and db.stage_done(
            conn, job["book_id"], chunk_id, "generate", model
        ):
            db.job_progress(conn, job["id"], position, len(chunks))
            continue
        db.stage_start(conn, job["book_id"], chunk_id, "generate", model)
        # A chunk takes minutes, during which the progress column does not
        # move. Say what is being written, so the log tail shows a pulse.
        log.event(
            "generate",
            "writing note",
            section=item.section,
            title=item.title,
            position=f"{position}/{len(chunks)}",
        )
        try:
            path = generate.run(
                item,
                book_slug=book["slug"],
                book_title=book["title"],
                book_tag=book["slug"],
                chapter_title=titles.get(item.chapter or 0, ""),
                model=model,
                figures=figures,
                out_dir=_out_dir(book),
                domain=_domain(book),
            )
        except Exception as error:
            db.stage_finish(
                conn,
                job["book_id"],
                chunk_id,
                "generate",
                model,
                db.FAILED,
                error=repr(error),
            )
            log.event(
                "generate", "chunk failed", section=item.section, error=repr(error)
            )
        else:
            db.stage_finish(
                conn, job["book_id"], chunk_id, "generate", model, db.DONE, path
            )
        db.job_progress(conn, job["id"], position, len(chunks))


def _do_vision(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    book = _book(conn, job)
    model = job["model"]
    force = bool(_params(job).get("force"))
    chunks = chunk_module.load_plan(book["slug"])
    titles = chunk_module.chapter_titles(chunks)
    figures = extract.load_figures(book["slug"])
    rows = {row["section"]: row["id"] for row in db.list_chunks(conn, job["book_id"])}

    targets = [
        (item, figure)
        for item in chunks
        for figure in generate.figures_for(figures, item)
    ]
    db.job_progress(conn, job["id"], 0, len(targets))

    for position, (item, figure) in enumerate(targets, start=1):
        if db.stop_requested(conn, job["id"]):
            return
        chunk_id = rows.get(item.section)
        stage = f"vision:{figure.id}"
        if not force and db.stage_done(conn, job["book_id"], chunk_id, stage, model):
            db.job_progress(conn, job["id"], position, len(targets))
            continue
        note = generate.note_path(
            item, titles.get(item.chapter or 0, ""), _out_dir(book)
        )
        if not note.exists():
            db.job_progress(conn, job["id"], position, len(targets))
            continue
        db.stage_start(conn, job["book_id"], chunk_id, stage, model)
        try:
            vision.run(
                figure,
                note,
                book_slug=book["slug"],
                chunk_text=item.text_path.read_text(encoding="utf-8"),
                model=model,
                out_dir=_out_dir(book),
                domain=_domain(book),
            )
        except Exception as error:
            db.stage_finish(
                conn,
                job["book_id"],
                chunk_id,
                stage,
                model,
                db.FAILED,
                error=repr(error),
            )
            log.event("vision", "figure failed", figure=figure.id, error=repr(error))
        else:
            db.stage_finish(conn, job["book_id"], chunk_id, stage, model, db.DONE, note)
        db.job_progress(conn, job["id"], position, len(targets))


def _do_index(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    book = _book(conn, job)
    db.stage_start(conn, job["book_id"], None, "index", job["model"])
    chunks = chunk_module.load_plan(book["slug"])
    written = index.run(
        chunks,
        chunk_module.chapter_titles(chunks),
        book_title=book["title"],
        book_tag=book["slug"],
        out_dir=_out_dir(book),
        domain=_domain(book),
    )
    db.job_progress(conn, job["id"], len(written), len(written))
    db.stage_finish(conn, job["book_id"], None, "index", job["model"], db.DONE)


def _do_export(conn: sqlite3.Connection, job: sqlite3.Row) -> None:
    """Write the sections out for a model elsewhere. Never touches the GPU.

    Book-wide rather than per chunk: with no model call there is nothing worth
    resuming, and the plan this stage builds is its own, at its own token
    budget, so it must not be recorded in the chunks the notes are made from.
    """
    book = _book(conn, job)
    params = _params(job)
    stage, model = "export", job["model"]
    db.stage_start(conn, job["book_id"], None, stage, model)

    ranges = [tuple(pair) for pair in params.get("page_ranges") or []]
    chunks = chunk_module.plan(
        book["slug"],
        Path(book["pdf_path"]),
        selected=params.get("sections"),
        page_ranges=ranges or None,
        budget=chunk_module.export_budget(),
    )
    titles = chunk_module.chapter_titles(chunks)
    figures = extract.load_figures(book["slug"])
    root = export.export_root(book["slug"], _out_dir(book))

    db.job_progress(conn, job["id"], 0, len(chunks))
    export.write_prompt(
        book["title"], book["slug"], len(chunks), _out_dir(book), _domain(book)
    )
    for position, item in enumerate(chunks, start=1):
        if db.stop_requested(conn, job["id"]):
            db.stage_finish(conn, job["book_id"], None, stage, model, db.STOPPED)
            return
        export.run(
            item,
            titles.get(item.chapter or 0, ""),
            book_slug=book["slug"],
            book_title=book["title"],
            book_tag=book["slug"],
            figures=figures,
            out_dir=_out_dir(book),
            domain=_domain(book),
        )
        db.job_progress(conn, job["id"], position, len(chunks))

    db.stage_finish(conn, job["book_id"], None, stage, model, db.DONE, root)


if __name__ == "__main__":
    main()
