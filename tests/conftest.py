# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Shared fixtures: every test runs against a throwaway /work, /state, /vault."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config


@pytest.fixture(autouse=True)
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, relative in (
        ("IN_DIR", "in"),
        ("WORK_DIR", "work"),
        ("STATE_DIR", "state"),
        ("OUT_DIR", "notes"),
        ("LOG_DIR", "state/logs"),
    ):
        path = tmp_path / relative
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(config, name, path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "state" / "glosator.db")
    return tmp_path
