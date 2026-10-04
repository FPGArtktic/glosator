# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Gradio front end on :7860.

The UI only queues jobs and reads state. The worker runs in its own process,
so closing the browser cannot kill a running job.

Two folders are picked here and nowhere else: the folder the books are read
from and the folder the notes are written to. Both are plain directories.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import gradio as gr

from app import chunk as chunk_module
from app import config, db, extract, generate, log, ollama, pdf

WORKER_RESTART_S = 5.0
JOB_COLUMNS = ["id", "stage", "status", "progress", "eta", "model", "error"]


def pdf_choices(books_dir: str | Path) -> list[str]:
    directory = Path(books_dir).expanduser()
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.glob("*.pdf"))


def resolve_pdf(
    books_dir: str | Path, choice: str | None, uploaded: str | None
) -> Path:
    if uploaded:
        destination = config.WORK_DIR / "uploads" / Path(uploaded).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if Path(uploaded) != destination:
            destination.write_bytes(Path(uploaded).read_bytes())
        return destination
    if choice:
        return Path(books_dir).expanduser() / choice
    raise gr.Error("pick a book from the books folder, or upload one")


def resolve_out_dir(notes_dir: str) -> Path:
    """The notes folder must exist: creating it blindly invites a typo."""
    path = Path(notes_dir.strip()).expanduser()
    if not path.is_dir():
        raise gr.Error(f"notes folder does not exist: {path}")
    return path.resolve()


def toc_labels(pdf_path: Path) -> list[str]:
    """Indented bookmark titles. The indent shows the tree; the value is the title."""
    return [
        f"{'    ' * mark.level}{mark.title}  (p. {mark.page})"
        for mark in pdf.read_toc(pdf_path)
    ]


def label_to_title(label: str) -> str:
    return label.strip().rsplit("  (p. ", 1)[0].strip()


def job_table(conn) -> list[list[str]]:
    rows = []
    for job in db.recent_jobs(conn):
        rows.append(
            [
                str(job["id"]),
                job["stage"],
                "stopping"
                if job["stop"] and job["status"] == db.RUNNING
                else job["status"],
                f"{job['done']}/{job['total']}",
                _eta(job),
                job["model"],
                (job["error"] or "")[:120],
            ]
        )
    return rows


def _eta(job) -> str:
    if job["status"] != db.RUNNING or not job["started"] or job["done"] < 1:
        return "-"
    started = datetime.fromisoformat(job["started"])
    elapsed = (datetime.now(UTC) - started).total_seconds()
    per_unit = elapsed / job["done"]
    remaining = max(0, job["total"] - job["done"]) * per_unit
    return f"{remaining / 60:.0f} min"


def last_note(notes_dir: str | Path) -> str:
    """Most recently written note, for a look at what the model produced."""
    directory = Path(notes_dir).expanduser()
    if not directory.is_dir():
        return "_notes folder not found_"
    notes = sorted(
        (path for path in directory.rglob("*.md") if generate.is_ours(path)),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not notes:
        return "_no notes yet_"
    return notes[0].read_text(encoding="utf-8")


def stop_jobs(conn, job_id: float | int | None, hard: bool = False) -> str:
    """Stop one job by id, or everything still pending when none is given.

    Having to read an id out of the table and type it in before anything can
    be stopped is not a reasonable thing to ask of someone watching a job go
    wrong.
    """
    if job_id:
        db.request_stop(conn, int(job_id))
        return f"Stop requested for job {int(job_id)}."
    stopped = db.stop_all(conn)
    if not stopped:
        return "Nothing to stop: no job is running or waiting."
    listed = ", ".join(str(job) for job in stopped)
    if hard and kill_worker():
        return (
            f"Stopped {len(stopped)} job(s): {listed}. The model call was cut "
            "off; the chunk it was on will be generated again if you rerun."
        )
    return (
        f"Stop requested for {len(stopped)} job(s): {listed}. A running stage "
        "finishes the chunk it is on first, which can take a few minutes; the "
        "table shows it as stopping until then."
    )


_worker: subprocess.Popen | None = None


def supervise_worker() -> None:
    """Keep one worker process alive next to the UI.

    Restarting here rather than in a shell wrapper keeps the container to a
    single entrypoint while the worker stays a separate process. The handle is
    kept so that a stop can be carried out by killing it.
    """

    def loop() -> None:
        global _worker
        while True:
            _worker = subprocess.Popen([sys.executable, "-m", "app.worker"])
            code = _worker.wait()
            _worker = None
            log.event("ui", "worker exited", code=code)
            time.sleep(WORKER_RESTART_S)

    threading.Thread(target=loop, name="worker-supervisor", daemon=True).start()


def kill_worker() -> bool:
    """End the current model call now, instead of after the chunk.

    Safe by construction: a note is written through a temporary file and
    renamed, the stage row of an unfinished chunk stays unfinished, and the
    supervisor starts a fresh worker a few seconds later.
    """
    process = _worker
    if process is None or process.poll() is not None:
        return False
    process.terminate()
    log.event("ui", "worker killed to carry out a stop")
    return True


def build() -> gr.Blocks:
    config.ensure_dirs()
    conn = db.connect()

    with gr.Blocks(title="glosator") as blocks:
        gr.Markdown("# glosator\nPDF textbook to study notes, locally.")

        with gr.Row():
            books_dir = gr.Textbox(
                label="Books folder (read-only)", value=str(config.IN_DIR)
            )
            notes_dir = gr.Textbox(
                label="Notes folder (written to)", value=str(config.OUT_DIR)
            )
        gr.Markdown(
            "Nothing outside the notes folder is written, nothing in it is "
            "deleted, and a file glosator did not write is never overwritten."
        )

        with gr.Row():
            with gr.Column(scale=1):
                source = gr.Dropdown(
                    pdf_choices(config.IN_DIR), label="Book", interactive=True
                )
                refresh_pdfs = gr.Button("Refresh book list", size="sm")
                upload = gr.File(label="or upload a PDF", file_types=[".pdf"])
                title = gr.Textbox(
                    label="Book title", placeholder="the title on the cover"
                )
                slug = gr.Textbox(
                    label="Slug (note tag, subfolder for figures)",
                    placeholder="short, e.g. bk1",
                )
                domain = gr.Textbox(
                    label="Field (first tag, and what the prompts say the book is)",
                    placeholder="electronics, calculus, anatomy, ...",
                )
                ocr = gr.Radio(
                    ["pol", "eng", "pol+eng"],
                    value=config.OCR_LANGS,
                    label="OCR language",
                )
            with gr.Column(scale=2):
                load_toc = gr.Button("Load table of contents")
                sections = gr.CheckboxGroup([], label="Sections to process")
                pages = gr.Textbox(
                    label="or page ranges (e.g. 71-96, 100-104)", placeholder="71-96"
                )
                with gr.Row():
                    model = gr.Dropdown(
                        [config.TEXT_MODEL], value=config.TEXT_MODEL, label="Text model"
                    )
                    vision_model = gr.Dropdown(
                        [config.VISION_MODEL],
                        value=config.VISION_MODEL,
                        label="Vision model",
                    )
                    refresh_models = gr.Button("Refresh models", size="sm")

        with gr.Row():
            run_all = gr.Button(
                "Run everything  (extract → chunk → generate → index)",
                variant="primary",
                scale=2,
            )
            preview_button = gr.Button("Preview extraction (3 pages)")
        with gr.Row():
            gr.Markdown("Or one stage at a time, in this order:")
            queue_extract = gr.Button("1. extract", size="sm")
            queue_chunk = gr.Button("2. chunk", size="sm")
            queue_generate = gr.Button("3. generate", size="sm")
            queue_index = gr.Button("4. index", size="sm")
            queue_vision = gr.Button("figures (optional)", size="sm")

        status = gr.Markdown()
        preview_output = gr.Markdown(label="Extraction preview")

        gr.Markdown("## Jobs")
        jobs = gr.Dataframe(headers=JOB_COLUMNS, value=job_table(conn), wrap=True)
        with gr.Row():
            stop_button = gr.Button("Stop after this chunk", variant="stop")
            kill_button = gr.Button("Stop now", variant="stop")
            clear_button = gr.Button("Clear finished", size="sm")
            stop_id = gr.Number(
                label="or one job id, if you want to stop only that one",
                precision=0,
            )

        with gr.Row():
            logs = gr.Textbox(label="Log", lines=14, max_lines=14, value=log.tail())
            note_preview = gr.Markdown(label="Last note")

        timer = gr.Timer(5.0)

        def _book_id(
            books, notes, title_value, slug_value, domain_value, choice, uploaded
        ) -> int:
            path = resolve_pdf(books, choice, uploaded)
            if not title_value.strip() or not slug_value.strip():
                raise gr.Error("give the book a title and a slug")
            return db.upsert_book(
                conn,
                slug_value.strip(),
                title_value.strip(),
                path,
                resolve_out_dir(notes),
                domain_value.strip() or config.DEFAULT_DOMAIN,
            )

        def _selected_pages(books, choice, uploaded, pages_value, section_labels):
            path = resolve_pdf(books, choice, uploaded)
            if pages_value.strip():
                try:
                    ranges = chunk_module.parse_page_ranges(pages_value)
                except ValueError as error:
                    # The field is next to several others; say which one is
                    # wrong and what belongs in it, not what the parser hit.
                    raise gr.Error(
                        f"Page ranges: {error}. The field takes numbers only, "
                        "like 13-56 or 13-56, 70-72. Did the book title end "
                        "up there?"
                    ) from error
                return path, ranges[0][0], ranges[-1][1], ranges
            titles = [label_to_title(label) for label in section_labels or []]
            if not titles:
                raise gr.Error("select sections or give page ranges")
            spans = chunk_module.spans_from_bookmarks(
                pdf.read_toc(path), pdf.page_count(path), titles
            )
            return (
                path,
                min(span.page_start for span in spans),
                max(span.page_end for span in spans),
                None,
            )

        def on_refresh_pdfs(books):
            return gr.update(choices=pdf_choices(books))

        def on_refresh_models():
            try:
                models = ollama.list_models()
            except ollama.OllamaUnavailable as error:
                raise gr.Error(str(error)) from error
            return gr.update(choices=models), gr.update(choices=models)

        def on_load_toc(books, choice, uploaded):
            path = resolve_pdf(books, choice, uploaded)
            bookmarks = pdf.read_toc(path)
            problems = chunk_module.outline_problems(bookmarks)
            message = f"{len(bookmarks)} bookmarks loaded."
            if problems:
                listed = "\n".join(f"- {problem}" for problem in problems)
                message = f"{message}\n\n**This outline is unreliable:**\n{listed}"
            return gr.update(choices=toc_labels(path)), message

        def on_preview(books, choice, uploaded, pages_value, section_labels, ocr_value):
            path, first, _last, _ranges = _selected_pages(
                books, choice, uploaded, pages_value, section_labels
            )
            return extract.preview(path, first, ocr_value)

        def on_queue_extract(
            books,
            notes,
            title_value,
            slug_value,
            domain_value,
            choice,
            uploaded,
            pages_value,
            section_labels,
            ocr_value,
        ):
            book_id = _book_id(
                books, notes, title_value, slug_value, domain_value, choice, uploaded
            )
            _path, first, last, _ranges = _selected_pages(
                books, choice, uploaded, pages_value, section_labels
            )
            params = json.dumps(
                {"first_page": first, "last_page": last, "ocr_langs": ocr_value}
            )
            job = db.enqueue(conn, book_id, "extract", "none", params)
            return f"Queued extract as job {job} (pages {first}-{last}).", job_table(
                conn
            )

        def on_queue_chunk(
            books,
            notes,
            title_value,
            slug_value,
            domain_value,
            choice,
            uploaded,
            pages_value,
            section_labels,
        ):
            book_id = _book_id(
                books, notes, title_value, slug_value, domain_value, choice, uploaded
            )
            _path, _first, _last, ranges = _selected_pages(
                books, choice, uploaded, pages_value, section_labels
            )
            params = {
                "page_ranges": ranges,
                "sections": [label_to_title(label) for label in section_labels or []],
            }
            job = db.enqueue(conn, book_id, "chunk", "none", json.dumps(params))
            return f"Queued chunk as job {job}.", job_table(conn)

        def _queue_simple(
            stage,
            model_value,
            books,
            notes,
            title_value,
            slug_value,
            domain_value,
            choice,
            uploaded,
        ):
            book_id = _book_id(
                books, notes, title_value, slug_value, domain_value, choice, uploaded
            )
            job = db.enqueue(conn, book_id, stage, model_value, json.dumps({}))
            return (
                f"Queued {stage} as job {job}; notes go to {resolve_out_dir(notes)}.",
                job_table(conn),
            )

        def on_run_all(
            books,
            notes,
            title_value,
            slug_value,
            domain_value,
            choice,
            uploaded,
            pages_value,
            section_labels,
            ocr_value,
            model_value,
        ):
            """Queue the whole book in one press.

            The worker takes one job at a time in the order they were queued,
            so each stage finds the previous one's output waiting for it.
            """
            log.event(
                "ui",
                "run everything pressed",
                title=title_value,
                slug=slug_value,
                domain=domain_value,
                pages=pages_value,
                sections=len(section_labels or []),
                model=model_value,
            )
            book_id = _book_id(
                books, notes, title_value, slug_value, domain_value, choice, uploaded
            )
            _path, first, last, ranges = _selected_pages(
                books, choice, uploaded, pages_value, section_labels
            )
            sections_chosen = [label_to_title(label) for label in section_labels or []]
            queued = [
                db.enqueue(
                    conn,
                    book_id,
                    "extract",
                    "none",
                    json.dumps(
                        {
                            "first_page": first,
                            "last_page": last,
                            "ocr_langs": ocr_value,
                        }
                    ),
                ),
                db.enqueue(
                    conn,
                    book_id,
                    "chunk",
                    "none",
                    json.dumps({"page_ranges": ranges, "sections": sections_chosen}),
                ),
                db.enqueue(conn, book_id, "generate", model_value, json.dumps({})),
                db.enqueue(conn, book_id, "index", "none", json.dumps({})),
            ]
            return (
                f"Queued jobs {queued[0]}-{queued[-1]} for pages {first}-{last}. "
                "Watch the table below; notes appear one by one in "
                f"{resolve_out_dir(notes)}.",
                job_table(conn),
            )

        def on_stop(job_id):
            return stop_jobs(conn, job_id), job_table(conn)

        def on_kill(job_id):
            return stop_jobs(conn, job_id, hard=True), job_table(conn)

        def on_clear():
            removed = db.clear_finished(conn)
            return f"Cleared {removed} finished job(s).", job_table(conn)

        def on_tick(notes):
            return job_table(conn), log.tail(), last_note(notes)

        refresh_pdfs.click(on_refresh_pdfs, books_dir, source)
        refresh_models.click(on_refresh_models, outputs=[model, vision_model])
        load_toc.click(on_load_toc, [books_dir, source, upload], [sections, status])
        preview_button.click(
            on_preview,
            [books_dir, source, upload, pages, sections, ocr],
            preview_output,
        )
        queue_extract.click(
            on_queue_extract,
            [
                books_dir,
                notes_dir,
                title,
                slug,
                domain,
                source,
                upload,
                pages,
                sections,
                ocr,
            ],
            [status, jobs],
        )
        queue_chunk.click(
            on_queue_chunk,
            [
                books_dir,
                notes_dir,
                title,
                slug,
                domain,
                source,
                upload,
                pages,
                sections,
            ],
            [status, jobs],
        )
        queue_generate.click(
            lambda m, b, n, t, s, d, c, u: _queue_simple(
                "generate", m, b, n, t, s, d, c, u
            ),
            [model, books_dir, notes_dir, title, slug, domain, source, upload],
            [status, jobs],
        )
        queue_vision.click(
            lambda m, b, n, t, s, d, c, u: _queue_simple(
                "vision", m, b, n, t, s, d, c, u
            ),
            [vision_model, books_dir, notes_dir, title, slug, domain, source, upload],
            [status, jobs],
        )
        queue_index.click(
            lambda b, n, t, s, d, c, u: _queue_simple(
                "index", "none", b, n, t, s, d, c, u
            ),
            [books_dir, notes_dir, title, slug, domain, source, upload],
            [status, jobs],
        )
        run_all.click(
            on_run_all,
            [
                books_dir,
                notes_dir,
                title,
                slug,
                domain,
                source,
                upload,
                pages,
                sections,
                ocr,
                model,
            ],
            [status, jobs],
        )
        stop_button.click(on_stop, stop_id, [status, jobs])
        kill_button.click(on_kill, stop_id, [status, jobs])
        clear_button.click(on_clear, outputs=[status, jobs])
        timer.tick(on_tick, notes_dir, [jobs, logs, note_preview])

    return blocks


# Keyword arguments passed to Blocks.launch. Kept as data so a test can check
# the installed gradio still accepts them: the UI is the one module no unit
# test exercises end to end, and a renamed argument only shows up at startup.
LAUNCH_OPTIONS = {"server_name": "0.0.0.0", "server_port": 7860, "share": False}


def main() -> None:
    supervise_worker()
    build().queue().launch(**LAUNCH_OPTIONS)


if __name__ == "__main__":
    main()
