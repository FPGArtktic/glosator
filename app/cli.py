# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Command line front end. Queues work; the worker does it.

Having one execution path means the pilot runs exactly what the UI runs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app import chunk as chunk_module
from app import config, db, extract, worker

STAGES = ("extract", "chunk", "generate", "vision", "index")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    config.ensure_dirs()

    if args.command == "worker":
        worker.main()
        return 0

    conn = db.connect()
    if args.command == "queue":
        _print_queue(conn)
        return 0
    if args.command == "add":
        book_id = _add(conn, args)
        print(f"book {book_id}")
        return 0
    return _queue_stage(conn, args)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="glosator")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="register a PDF and where its notes go")
    add.add_argument("pdf", type=Path)
    add.add_argument("--title", required=True)
    add.add_argument("--slug", help="defaults to a slug of the title")
    add.add_argument(
        "--domain",
        default=None,
        help="the field the book belongs to, e.g. electronics, calculus, "
        f"anatomy; it reaches the prompts and the note tags (default: "
        f"{config.DEFAULT_DOMAIN})",
    )
    add.add_argument(
        "--out",
        type=Path,
        default=None,
        help="folder the notes are written to; any directory, "
        f"not necessarily an Obsidian vault (default: {config.OUT_DIR})",
    )

    for stage in STAGES:
        stage_parser = sub.add_parser(stage, help=f"queue the {stage} stage")
        stage_parser.add_argument("--book", required=True, help="book slug")
        stage_parser.add_argument("--model", default=None)
        stage_parser.add_argument("--force", action="store_true")
        if stage == "extract":
            stage_parser.add_argument("--pages", required=True, help="e.g. 60-120")
            stage_parser.add_argument("--ocr", default=config.OCR_LANGS)
        if stage == "chunk":
            stage_parser.add_argument("--pages", default=None)

    sub.add_parser("queue", help="list jobs")
    sub.add_parser("worker", help="run the queue consumer in the foreground")
    return parser


def _add(conn, args) -> int:
    slug = args.slug or extract.slugify(args.title)
    out_dir = args.out.expanduser().resolve() if args.out else None
    return db.upsert_book(
        conn, slug, args.title, args.pdf.resolve(), out_dir, args.domain
    )


def _queue_stage(conn, args) -> int:
    row = conn.execute("SELECT id FROM books WHERE slug = ?", (args.book,)).fetchone()
    if row is None:
        raise SystemExit(f"unknown book {args.book!r}; run 'glosator add' first")
    book_id = int(row[0])
    model = args.model or _default_model(args.command)

    if args.force:
        db.clear_stage(conn, book_id, args.command)

    params = {"force": args.force}
    if args.command == "extract":
        ranges = chunk_module.parse_page_ranges(args.pages)
        params |= {
            "first_page": ranges[0][0],
            "last_page": ranges[-1][1],
            "ocr_langs": args.ocr,
        }
    if args.command == "chunk" and args.pages:
        params["page_ranges"] = chunk_module.parse_page_ranges(args.pages)

    job_id = db.enqueue(conn, book_id, args.command, model, json.dumps(params))
    print(f"job {job_id} queued: {args.command} on {args.book} with {model}")
    return 0


def _default_model(stage: str) -> str:
    if stage == "generate":
        return config.TEXT_MODEL
    if stage == "vision":
        return config.VISION_MODEL
    return "none"


def _print_queue(conn) -> None:
    for job in db.recent_jobs(conn):
        print(
            f"{job['id']:>4}  {job['stage']:<9} {job['status']:<8} "
            f"{job['done']}/{job['total']}  {job['model']}  {job['error'] or ''}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
