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
TEXT_MODEL: str = os.environ.get("GLOSATOR_TEXT_MODEL", "gemma4:31b")
# Seven times faster than TEXT_MODEL for about two more errors per hundred
# claims (docs/DECISIONS.md, 2026-11-01): for a book that matters less.
FAST_TEXT_MODEL: str = os.environ.get("GLOSATOR_FAST_MODEL", "gemma4:26b")
VISION_MODEL: str = os.environ.get("GLOSATOR_VISION_MODEL", "gemma4:26b")

# Ollama request options, applied to every call (see CLAUDE.md).
NUM_CTX: int = 12288
TEMPERATURE: float = 0.25
NUM_PREDICT: int = 3072

# A model partly offloaded to the CPU generates at a few tokens per second, so
# a single chunk can legitimately take twenty minutes. Fail only on a real hang.
OLLAMA_TIMEOUT_S: int = 2700

# Keep the model resident between chunks; reloading 20 GB of weights per call
# would dominate the run time.
OLLAMA_KEEP_ALIVE: str = "30m"

# Chunk size budget in tokens of source text. Below MIN a section is merged
# with its following sibling; above MAX no further merging happens. A single
# section is never split, even when it exceeds MAX.
CHUNK_MIN_TOKENS: int = 3000
CHUNK_MAX_TOKENS: int = 6000
# A chunk of a deep outline with less source than this is a title page or a
# bare contents, not a section, and is left out of the plan.
CHUNK_SKIP_TOKENS: int = 150

# A programming book's note copies its listings verbatim, so the answer grows
# with the source: a ten-page C++ chunk ran past NUM_PREDICT on the pilot.
# Its chunks are smaller, which keeps a note close to one section, and its
# answer has twice the room, with the window widened to hold it.
LISTING_CHUNK_MIN_TOKENS: int = 2000
LISTING_CHUNK_MAX_TOKENS: int = 4000
LISTING_NUM_PREDICT: int = 6144
LISTING_NUM_CTX: int = 16384

# The same budget for the export stage, which writes files for a model that
# is not this machine's. Nothing has to fit in 4 GB of VRAM there, so the
# files are longer: fewer of them to hand over, and more of a chapter in
# front of the reader at once. Overridable because the right size depends on
# whose window they are going into.
EXPORT_MIN_TOKENS: int = int(os.environ.get("GLOSATOR_EXPORT_MIN_TOKENS", "12000"))
EXPORT_MAX_TOKENS: int = int(os.environ.get("GLOSATOR_EXPORT_MAX_TOKENS", "20000"))

# A page with this many lines ending in leader dots and a page number is a
# table of contents. Its entries are headings with no text under them, so it
# is left out of what the model reads. Index pages and part lists rarely
# carry more than a couple of dotted lines.
CONTENTS_PAGE_MIN_LINES: int = 5
# The last page of a contents often holds only one or two entries under the
# running head. It is still a contents page when its dotted lines are at least
# this share of its characters.
CONTENTS_PAGE_MIN_SHARE: float = 0.5

# Rough token estimate for English and Polish technical prose. Only used to
# decide merging, never to size a request exactly.
CHARS_PER_TOKEN: int = 4

# The subject of a book, used in the prompts and as the first tag of every
# note. Books come from different fields, so this is per book; the value here
# is only what an unset book falls back to.
DEFAULT_DOMAIN: str = os.environ.get("GLOSATOR_DOMAIN", "general")

# A book with no language set gets notes in the language its text is in.
# Polish prose has about seven of every hundred letters in ą ć ę ł ń ó ś ź ż,
# English has none, so a share of 2 % tells them apart with room for an
# English book quoting Polish names or a Polish one full of code.
POLISH_LETTER_MIN_SHARE: float = 0.02
# How much of the chunks' text the language is judged from.
LANGUAGE_SAMPLE_CHARS: int = 200_000

# An EPUB has no pages; extraction cuts one about this long, at the end of a
# paragraph, so that chunking can read it like a PDF. A printed page of the
# Helion books measured holds 2,500 to 3,000 characters.
EPUB_PAGE_CHARS: int = 3000
OCR_LANGS: str = os.environ.get("GLOSATOR_OCR_LANGS", "pol+eng")

# Where docling runs: "auto" puts it on the card when nvml reports at least
# EXTRACT_MIN_FREE_MB free, which it does only while Ollama holds no model;
# "cpu" and "cuda" force the choice. The stages run one after another, so the
# card is the extraction stage's while it runs and Ollama's afterwards.
DOCLING_DEVICE: str = os.environ.get("GLOSATOR_DOCLING_DEVICE", "auto")
# Layout, table and formula models together, with headroom. A layout pass
# that ran short of memory once dropped half the figures without failing
# (docs/PILOT.md), so the bar is set well above what they need.
EXTRACT_MIN_FREE_MB: int = int(os.environ.get("GLOSATOR_EXTRACT_MIN_FREE_MB", "6000"))
DOCLING_THREADS: int = int(os.environ.get("GLOSATOR_DOCLING_THREADS", "8"))

# Recognise displayed formulas and write them as LaTeX. The text layer loses
# them: "In this case," followed by nothing (docs/PILOT.md).
DOCLING_FORMULAS: bool = os.environ.get("GLOSATOR_FORMULAS", "1") != "0"

# Pages per docling run. Each batch is a child process that exits when done,
# which is what returns its memory to the system and its VRAM to the card, and
# a finished batch is kept, so a stopped extraction resumes where it was.
EXTRACT_BATCH_PAGES: int = 40
# One batch on the CPU with OCR is minutes per page at worst. An hour without
# an answer is a hang.
EXTRACT_BATCH_TIMEOUT_S: int = 3600

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

# An uncaptioned picture at most this wide is a margin icon, not a figure.
# The callout tiles of the second book are 40-79 pt wide; the narrowest
# uncaptioned pictures worth keeping there, photos of parts, are 95 pt.
DECORATION_MAX_WIDTH_PT: float = 80.0

# An uncaptioned picture that comes back on this many pages is part of the
# page, not of the text: the LPI materials print their logo at the top of
# every lesson, 55 of the 58 pictures docling found in one book.
REPEATED_FIGURE_MIN_PAGES: int = 3
# ... and spread across the book: its first and last page at least this far
# apart. Datasheet drawings of related chips (two pinouts, two gate diagrams)
# hash alike too, but sit together on a few neighbouring pages.
REPEATED_FIGURE_MIN_SPAN_PAGES: int = 20
# Two crops are the same picture when their 8x8 average hashes differ in at
# most this many of 64 bits. Crops of the LPI logo differ by up to 2, a cover
# reprinted at each chapter by 0.
REPEATED_FIGURE_MAX_BITS: int = 4
# ... and the same size, within this many points each way.
REPEATED_FIGURE_SIZE_TOLERANCE_PT: float = 2.0

# Pages rendered by the extraction preview in the UI.
PREVIEW_PAGES: int = 3

# Books whose code listings are rebuilt from the text layer and copied into
# the notes. The domain is the one given to "glosator add --domain".
LISTING_DOMAINS: frozenset[str] = frozenset({"programming"})
# How far outside docling's box around a listing a character may sit and
# still belong to it, in points: the box is drawn around ink, not glyph cells.
LISTING_BOX_MARGIN_PT: float = 2.0
# Two characters share a line when their middles are this close, as a share of
# a character's height. Punctuation sits lower than letters, by less than this.
LISTING_LINE_TOLERANCE: float = 0.5
# A gap narrower than one character cell but wider than this share of one is
# a word space. Comments in a proportional font have spaces that narrow: on
# two of the pilot books 0.9-2.1 pt against a 3.75-4.26 pt cell, while the
# gaps between letters stayed under 0.1 pt.
LISTING_WORD_GAP: float = 0.15
# A line is in the listing's monospaced font when this share of its glyphs is
# one cell wide, within this share of a cell. Only such lines set the left
# edge: docling's box sometimes takes in a line of prose, which starts at the
# text margin, left of an indented listing, and shifted every line of it.
LISTING_MONOSPACED_SHARE: float = 0.8
LISTING_CELL_TOLERANCE: float = 0.05

# A bought ebook can carry a per-copy watermark: one hex digest in the footer
# of every page, which docling merges into the text. A digest is taken for a
# watermark only when it repeats on this many pages of a batch, so a hash a
# book prints as an example, once, stays.
WATERMARK_MIN_PAGES: int = 3

# How often the worker re-reads the job queue when it is empty.
WORKER_POLL_S: float = 2.0


def ensure_dirs() -> None:
    """Create the directories glosator writes to. IN_DIR is read-only."""
    for directory in (WORK_DIR, STATE_DIR, LOG_DIR):
        directory.mkdir(parents=True, exist_ok=True)
