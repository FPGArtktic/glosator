# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The contract the rest of the tree relies on.

Paths, the fixed Ollama options, and the model names the launcher reads back
out of this module rather than keeping its own copy of.
"""

from __future__ import annotations

import importlib
import os
import subprocess
from pathlib import Path

import pytest

from app import config

LAUNCHER = Path(__file__).resolve().parent.parent / "bin" / "glosator"


def _reload(monkeypatch: pytest.MonkeyPatch, **environment: str):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    return importlib.reload(config)


@pytest.fixture(autouse=True)
def _restore_module():
    yield
    importlib.reload(config)


def test_every_path_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reloaded = _reload(
        monkeypatch,
        GLOSATOR_IN=str(tmp_path / "books"),
        GLOSATOR_OUT=str(tmp_path / "notes"),
        GLOSATOR_WORK=str(tmp_path / "work"),
        GLOSATOR_STATE=str(tmp_path / "state"),
    )
    expected = {
        "IN_DIR": tmp_path / "books",
        "OUT_DIR": tmp_path / "notes",
        "DB_PATH": tmp_path / "state" / "glosator.db",
        "LOG_DIR": tmp_path / "state" / "logs",
    }
    actual = {name: getattr(reloaded, name) for name in expected}
    assert actual == expected


def test_a_leading_tilde_is_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    reloaded = _reload(monkeypatch, GLOSATOR_OUT="~/study-notes")
    assert reloaded.OUT_DIR.is_absolute()
    assert "~" not in str(reloaded.OUT_DIR)


def test_ensure_dirs_creates_what_we_write_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reloaded = _reload(
        monkeypatch,
        GLOSATOR_IN=str(tmp_path / "books"),
        GLOSATOR_WORK=str(tmp_path / "work"),
        GLOSATOR_STATE=str(tmp_path / "state"),
    )
    reloaded.ensure_dirs()

    assert reloaded.WORK_DIR.is_dir()
    assert reloaded.LOG_DIR.is_dir()
    # The books folder is mounted read-only; creating it would hide a typo in
    # the path behind an empty directory.
    assert not reloaded.IN_DIR.exists()


def test_ensure_dirs_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    reloaded = _reload(
        monkeypatch,
        GLOSATOR_WORK=str(tmp_path / "work"),
        GLOSATOR_STATE=str(tmp_path / "state"),
    )
    reloaded.ensure_dirs()
    reloaded.ensure_dirs()


def test_the_ollama_options_are_the_ones_claude_md_fixes() -> None:
    # Changing these is a decision, not a tweak: they are sized for 4 GB of
    # VRAM and a 6k-token chunk. See CLAUDE.md and docs/DECISIONS.md.
    assert config.NUM_CTX == 12288
    assert config.TEMPERATURE == 0.25
    assert config.NUM_PREDICT == 2048


def test_the_chunk_budget_fits_inside_the_context_window() -> None:
    prompt_and_answer = config.CHUNK_MAX_TOKENS + config.NUM_PREDICT
    assert prompt_and_answer < config.NUM_CTX


def _launcher_models(environment: dict[str, str] | None = None) -> list[str]:
    """Run the launcher's own ``models()`` against the real app/config.py.

    The function is lifted out of the script rather than reimplemented here:
    a copy of it in the test would pass while the script itself was wrong,
    which is precisely the failure this test exists to catch.
    """
    script = (
        f"eval \"$(sed -n '/^models()/,/^}}/p' {LAUNCHER})\"\n"
        f"REPO={LAUNCHER.parent.parent}\n"
        "models\n"
    )
    result = subprocess.run(
        ["sh", "-c", script],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **(environment or {})},
    )
    return result.stdout.split()


def test_the_launcher_keeps_no_model_name_of_its_own() -> None:
    # A second copy of the default went stale when config.py changed, and the
    # launcher then unloaded a model the app had never loaded while still
    # reporting a free GPU. The names have one home: app/config.py.
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "gemma3" not in text
    assert "qwen" not in text


def test_the_launcher_unloads_the_models_config_names() -> None:
    assert _launcher_models() == [config.TEXT_MODEL, config.VISION_MODEL]


def test_the_launcher_honours_a_model_chosen_in_the_environment() -> None:
    models = _launcher_models({"GLOSATOR_TEXT_MODEL": "chosen-by-hand:latest"})
    assert models[0] == "chosen-by-hand:latest"
