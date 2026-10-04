# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Worker behaviour that the whole design rests on: resume, isolate, stop."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import chunk as chunk_module
from app import config, db, worker
from app.chunk import Chunk

MODEL = "gemma3:12b-it-qat"


def _plan(slug: str = "bk1") -> list[Chunk]:
    book_dir = config.WORK_DIR / slug
    (book_dir / "chunks").mkdir(parents=True, exist_ok=True)
    chunks = []
    for order, section in enumerate(("2.1", "2.2"), start=1):
        text_path = book_dir / "chunks" / f"{order:03d}-{section}.md"
        text_path.write_text("source\n", encoding="utf-8")
        chunks.append(
            Chunk(
                order,
                2,
                section,
                f"Section {section}",
                70 + order,
                70 + order,
                text_path,
            )
        )
    (book_dir / chunk_module.CHUNKS_JSON).write_text(
        json.dumps(
            [
                {
                    "ord": chunk.ord,
                    "chapter": chunk.chapter,
                    "section": chunk.section,
                    "title": chunk.title,
                    "pages": [chunk.page_start, chunk.page_end],
                    "text_path": str(chunk.text_path),
                }
                for chunk in chunks
            ]
        ),
        encoding="utf-8",
    )
    return chunks


@pytest.fixture
def queued():
    conn = db.connect()
    chunks = _plan()
    book_id = db.upsert_book(conn, "bk1", "Book", Path("/in/book.pdf"))
    db.replace_chunks(conn, book_id, chunks)
    db.enqueue(conn, book_id, "generate", MODEL, json.dumps({}))
    job = db.claim_job(conn)
    yield conn, book_id, job
    conn.close()


def test_generate_job_runs_every_chunk_once(queued, monkeypatch) -> None:
    conn, _book_id, job = queued
    seen: list[str] = []

    def fake_run(chunk, **kwargs):
        seen.append(chunk.section)
        return config.OUT_DIR / f"{chunk.section}.md"

    monkeypatch.setattr(worker.generate, "run", fake_run)
    worker._run_job(conn, job)

    assert seen == ["2.1", "2.2"]
    assert db.recent_jobs(conn)[0]["status"] == db.DONE
    assert db.recent_jobs(conn)[0]["done"] == 2


def test_generate_job_skips_chunks_already_done(queued, monkeypatch) -> None:
    conn, book_id, job = queued
    first = db.list_chunks(conn, book_id)[0]["id"]
    db.stage_start(conn, book_id, first, "generate", MODEL)
    db.stage_finish(conn, book_id, first, "generate", MODEL, db.DONE)

    seen: list[str] = []
    monkeypatch.setattr(
        worker.generate, "run", lambda chunk, **_k: seen.append(chunk.section)
    )
    worker._run_job(conn, job)

    assert seen == ["2.2"]


def test_force_regenerates_a_finished_chunk(queued, monkeypatch) -> None:
    conn, book_id, job = queued
    conn.execute(
        "UPDATE jobs SET params = ? WHERE id = ?",
        (json.dumps({"force": True}), job["id"]),
    )
    job = db.recent_jobs(conn)[0]
    first = db.list_chunks(conn, book_id)[0]["id"]
    db.stage_start(conn, book_id, first, "generate", MODEL)
    db.stage_finish(conn, book_id, first, "generate", MODEL, db.DONE)

    seen: list[str] = []
    monkeypatch.setattr(
        worker.generate, "run", lambda chunk, **_k: seen.append(chunk.section)
    )
    worker._run_job(conn, job)

    assert seen == ["2.1", "2.2"]


def test_one_failing_chunk_does_not_stop_the_job(queued, monkeypatch) -> None:
    conn, book_id, job = queued

    def fake_run(chunk, **_kwargs):
        if chunk.section == "2.1":
            raise ValueError("model omitted In short")
        return config.OUT_DIR / "ok.md"

    monkeypatch.setattr(worker.generate, "run", fake_run)
    worker._run_job(conn, job)

    rows = {row["chunk_id"]: row for row in db.stage_rows(conn, book_id, "generate")}
    statuses = sorted(row["status"] for row in rows.values())
    assert statuses == [db.DONE, db.FAILED]
    assert db.recent_jobs(conn)[0]["status"] == db.DONE


def test_stop_request_ends_the_job_without_the_remaining_chunks(
    queued, monkeypatch
) -> None:
    conn, _book_id, job = queued
    seen: list[str] = []

    def fake_run(chunk, **_kwargs):
        seen.append(chunk.section)
        db.request_stop(conn, job["id"])
        return config.OUT_DIR / "ok.md"

    monkeypatch.setattr(worker.generate, "run", fake_run)
    worker._run_job(conn, job)

    assert seen == ["2.1"]
    assert db.recent_jobs(conn)[0]["status"] == db.STOPPED


def test_an_unknown_stage_fails_the_job(queued) -> None:
    conn, book_id, _job = queued
    db.enqueue(conn, book_id, "nonsense", "none", "{}")
    job = db.recent_jobs(conn)[0]
    worker._run_job(conn, job)
    assert db.recent_jobs(conn)[0]["status"] == db.FAILED


def test_a_broken_stage_fails_the_job_not_the_worker(queued, monkeypatch) -> None:
    conn, _book_id, job = queued

    def boom(_slug):
        raise OSError("disk full")

    monkeypatch.setattr(worker.chunk_module, "load_plan", boom)
    worker._run_job(conn, job)

    row = db.recent_jobs(conn)[0]
    assert row["status"] == db.FAILED
    assert "disk full" in row["error"]


def test_generate_job_uses_the_books_own_output_folder(tmp_path, monkeypatch) -> None:
    conn = db.connect()
    chunks = _plan()
    elsewhere = tmp_path / "notes-elsewhere"
    elsewhere.mkdir()
    book_id = db.upsert_book(conn, "bk1", "Book", Path("/in/book.pdf"), elsewhere)
    db.replace_chunks(conn, book_id, chunks)
    db.enqueue(conn, book_id, "generate", MODEL, json.dumps({}))
    job = db.claim_job(conn)

    seen: list[Path] = []
    monkeypatch.setattr(
        worker.generate,
        "run",
        lambda chunk, **kwargs: seen.append(Path(kwargs["out_dir"])) or Path("x.md"),
    )
    worker._run_job(conn, job)
    conn.close()

    assert seen == [elsewhere, elsewhere]


def test_generate_job_falls_back_to_the_configured_folder(queued, monkeypatch) -> None:
    conn, _book_id, job = queued
    seen: list[Path] = []
    monkeypatch.setattr(
        worker.generate,
        "run",
        lambda chunk, **kwargs: seen.append(Path(kwargs["out_dir"])) or Path("x.md"),
    )
    worker._run_job(conn, job)
    assert seen == [config.OUT_DIR, config.OUT_DIR]


def test_a_model_job_frees_the_gpu_when_it_ends(queued, monkeypatch) -> None:
    conn, _book_id, job = queued
    unloaded: list[str] = []
    monkeypatch.setattr(worker.generate, "run", lambda chunk, **_k: Path("x.md"))
    monkeypatch.setattr(worker.ollama, "unload", lambda model: unloaded.append(model))

    worker._run_job(conn, job)

    assert unloaded == [MODEL]


def test_a_failed_model_job_also_frees_the_gpu(queued, monkeypatch) -> None:
    conn, _book_id, job = queued
    unloaded: list[str] = []

    def boom(_slug):
        raise OSError("disk full")

    monkeypatch.setattr(worker.chunk_module, "load_plan", boom)
    monkeypatch.setattr(worker.ollama, "unload", lambda model: unloaded.append(model))

    worker._run_job(conn, job)

    assert unloaded == [MODEL]


def test_a_stage_without_a_model_does_not_touch_the_gpu(queued, monkeypatch) -> None:
    conn, book_id, _job = queued
    unloaded: list[str] = []
    monkeypatch.setattr(worker.ollama, "unload", lambda model: unloaded.append(model))
    db.enqueue(conn, book_id, "index", "none", "{}")
    index_job = db.recent_jobs(conn)[0]
    monkeypatch.setattr(worker.index, "run", lambda *_a, **_k: [])

    worker._run_job(conn, index_job)

    assert unloaded == []


def test_a_generate_job_passes_the_books_own_field(tmp_path, monkeypatch) -> None:
    conn = db.connect()
    chunks = _plan("anat1")
    book_id = db.upsert_book(
        conn, "anat1", "Example Textbook", Path("/in/a.pdf"), tmp_path, "anatomy"
    )
    db.replace_chunks(conn, book_id, chunks)
    db.enqueue(conn, book_id, "generate", MODEL, json.dumps({}))
    job = db.claim_job(conn)

    seen: list[str] = []
    monkeypatch.setattr(worker.ollama, "unload", lambda _model: None)
    monkeypatch.setattr(
        worker.generate,
        "run",
        lambda chunk, **kwargs: seen.append(kwargs["domain"]) or Path("x.md"),
    )
    worker._run_job(conn, job)
    conn.close()

    assert seen == ["anatomy", "anatomy"]


def test_a_book_without_a_field_falls_back_to_the_configured_one(
    queued, monkeypatch
) -> None:
    conn, _book_id, job = queued
    seen: list[str] = []
    monkeypatch.setattr(worker.ollama, "unload", lambda _model: None)
    monkeypatch.setattr(
        worker.generate,
        "run",
        lambda chunk, **kwargs: seen.append(kwargs["domain"]) or Path("x.md"),
    )
    worker._run_job(conn, job)

    assert seen == [config.DEFAULT_DOMAIN, config.DEFAULT_DOMAIN]
