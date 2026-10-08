# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Paths, model names and tunables. The only place that reads the environment."""

from __future__ import annotations

import os
from pathlib import Path


def _path(env_name: str, default: str) -> Path:
    return Path(os.environ.get(env_name, default)).expanduser()


# Container mount points. Overridable so the test suite and host runs do not
# need /in and /out to exist.
#
# IN_DIR is the folder the books are read from, mounted read-only.
# OUT_DIR is the folder the notes are written to. It is an ordinary directory:
# an Obsidian vault works, so does an empty folder somewhere safe. Nothing
# outside OUT_DIR is ever written, and nothing inside it is ever deleted.
IN_DIR: Path = _path("GLOSATOR_IN", "/in")
OUT_DIR: Path = _path("GLOSATOR_OUT", "/out")
WORK_DIR: Path = _path("GLOSATOR_WORK", "/work")
STATE_DIR: Path = _path("GLOSATOR_STATE", "/state")

LOG_DIR: Path = STATE_DIR / "logs"
DB_PATH: Path = STATE_DIR / "glosator.db"
PROMPT_DIR: Path = Path(__file__).parent / "prompts"

OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://ollama:11434")
TEXT_MODEL: str = os.environ.get("GLOSATOR_TEXT_MODEL", "qwen2.5:32b")
VISION_MODEL: str = os.environ.get("GLOSATOR_VISION_MODEL", "qwen3-vl:8b")

# Ollama request options, applied to every call (see CLAUDE.md).
NUM_CTX: int = 12288
TEMPERATURE: float = 0.25
NUM_PREDICT: int = 2048

# A 12B model offloaded to CPU generates at a few tokens per second, so a
# single chunk can legitimately take twenty minutes. Fail only on a real hang.
OLLAMA_TIMEOUT_S: int = 2700

# Keep the model resident between chunks; reloading 8 GB of weights per call
# would dominate the run time.
OLLAMA_KEEP_ALIVE: str = "30m"

# Chunk size budget in tokens of source text. Below MIN a section is merged
# with its following sibling; above MAX no further merging happens. A single
# section is never split, even when it exceeds MAX.
CHUNK_MIN_TOKENS: int = 3000
CHUNK_MAX_TOKENS: int = 6000

# The same budget for the export stage, which writes files for a model that
# is not this machine's. Nothing has to fit in 4 GB of VRAM there, so the
# files are longer: fewer of them to hand over, and more of a chapter in
# front of the reader at once. Overridable because the right size depends on
# whose window they are going into.
EXPORT_MIN_TOKENS: int = int(os.environ.get("GLOSATOR_EXPORT_MIN_TOKENS", "12000"))
EXPORT_MAX_TOKENS: int = int(os.environ.get("GLOSATOR_EXPORT_MAX_TOKENS", "20000"))

# Rough token estimate for English and Polish technical prose. Only used to
# decide merging, never to size a request exactly.
CHARS_PER_TOKEN: int = 4

# The subject of a book, used in the prompts and as the first tag of every
# note. Books come from different fields, so this is per book; the value here
# is only what an unset book falls back to.
DEFAULT_DOMAIN: str = os.environ.get("GLOSATOR_DOMAIN", "general")

OCR_LANGS: str = os.environ.get("GLOSATOR_OCR_LANGS", "pol+eng")

# docling runs on the CPU. The GPU holds one model at a time and that model is
# Ollama's: a layout pass that competes with it dies of CUDA OOM, and the
# extraction stage is minutes against the generation stage's hours.
DOCLING_THREADS: int = int(os.environ.get("GLOSATOR_DOCLING_THREADS", "8"))

# Where the image bakes docling's weights. Passing the path explicitly is what
# makes the offline container work: docling's own default lives under $HOME,
# which changes with --userns=keep-id.
DOCLING_MODELS: Path = _path("DOCLING_ARTIFACTS_PATH", "/opt/models/docling")

# A page with fewer extractable characters than this is treated as a scan and
# handed to OCR. Running heads and page numbers alone stay well under it.
TEXT_LAYER_MIN_CHARS: int = 180

# Figure crops: rendered at this resolution and padded, because docling
# bounding boxes sit tight against axis labels.
FIGURE_DPI: int = 200
FIGURE_PAD_PT: float = 6.0

# Pages rendered by the extraction preview in the UI.
PREVIEW_PAGES: int = 3

# How often the worker re-reads the job queue when it is empty.
WORKER_POLL_S: float = 2.0


def ensure_dirs() -> None:
    """Create the directories glosator writes to. IN_DIR is read-only."""
    for directory in (WORK_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
