# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Structured logging."""

from __future__ import annotations

import json

from app import log


def test_event_writes_one_json_line_per_call() -> None:
    log.event("generate", "note written", section="2.3.1", words=620)
    log.event("generate", "note written", section="2.3.2", words=480)

    lines = log.log_path().read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record["stage"] == "generate"
    assert record["section"] == "2.3.1"
    assert "ts" in record and "pid" in record


def test_tail_is_human_readable() -> None:
    log.event("chunk", "planned", chunks=42)
    tail = log.tail()
    assert "[chunk] planned" in tail
    assert "42" in tail


def test_tail_without_a_log_file() -> None:
    assert log.tail() == ""
