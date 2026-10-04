# Pilot

## Measured on 2026-10-04 — one subsection, end to end

Book: an electronics textbook of 1041 pages, text layer throughout, so OCR
was never needed. Its outline is unusable, so page ranges drive the chunking.
The book is not named here, and no passage of it is quoted: this file records
what the pipeline did, not what the source said.

Subject: one three-page subsection of chapter 2, PDF pages 18-20. The offset
between printed and PDF page numbers is 48 in this file.

### Extraction

| | |
|---|---|
| docling | 2.133.0, tesseract backend unused (text layer present) |
| 3 pages | **7 s** on the CPU |
| figures found | **4 of 4**, captions complete and correctly attributed |
| crops | inspected by eye: axis labels and values inside the box, nothing clipped |

**The GPU costs figures.** With Ollama resident (3.1 GB of 3.73 GB), docling's
layout model died with `torch.OutOfMemoryError`, logged `Stage layout failed`
and carried on, yielding **2 figures instead of 4** — the section's main
schematic of the subsection was among the lost. docling is now pinned to the CPU
(docs/DECISIONS.md). A silent half-result is worse than a crash; watch for
that log line.

### Generation — same chunk, both models

| | `qwen2.5:7b` | `gemma3:12b-it-qat` |
|---|---|---|
| time | 64 s | **197-239 s** |
| words | ~650 | 799-864 |
| `Z_out` | `1/(h_fe+1)` — not an impedance | `Z_source/(h_fe+1)` ✅ / `R_L/(h_fe+1)` ❌ |
| `Z_in` | absent | `(h_fe+1)R_L` ✅ |
| 0.6 V drop | called a "phase shift" ❌ | correct ✅ |
| `## Formulas` | "None in this section." ❌ | three formulas with purposes ✅ |
| Pitfalls | generic | four, all from the source ✅ |

**Throughput: ~4 minutes per chunk** at 2105 tokens in, ~800 words out. For
~300 chunks of this book that is **about 20 hours**, inside the 25-30 h the
hardware note predicts.

### The model comparison, measured by review rather than by reading

Six notes were reviewed against their source chunks: three independent lenses
each, every finding then handed to a sceptic whose job was to refute it. 38
findings were refuted, 115 survived, 60 of those errors — roughly 23 distinct
defects over six notes. The mechanics were faultless: 75 figure embeds all
resolving, an unbroken navigation chain, a 58-term merged glossary, every note
inside the length target. The content was not usable.

The same chunk was then regenerated with `qwen2.5:32b` and put through the
identical reviewers:

| on the same note | `gemma3:12b-it-qat` | `qwen2.5:32b` |
|---|---|---|
| confirmed findings | 30 | 9 |
| of them errors | 19 | 5 |
| time | ~4 min | 17 min |

What the 12B model got wrong was fundamental: the signal entering a follower at
the emitter, an invented "common cathode amplifier", the impedance roles
reversed, a comparator said to work in its linear region, two renderings of
Ebers-Moll both wrong, a Darlington placed in a figure that has none, two
formulas in a section whose source contains no equation. What the 32B model
got wrong was a biasing criterion stated backwards and 750k written where the
source divides it by ten.

One of those two is extraction's fault, not the model's: OCR dropped the
displayed inequality, leaving "In this case," followed by nothing.

### Two findings that change how the book should be run

**1. The glossary needs the prompt to be blunt.** gemma3's first glossary held
no Polish at all: it listed symbols with English definitions, several of them
OCR debris for Greek letters rather than terms. One line of instruction lost
against the rest of the prompt. After rewriting that section with three worked
examples, a ban on symbols and a `(brak odpowiednika)` escape, the same chunk
produced eleven proper term pairs, each an English technical term with its
established Polish equivalent.

**2. The same model contradicts itself between runs.** On the first run
gemma3 wrote `Z_out = Z_source/(h_fe+1)`, which is right. On the second, from
the identical chunk, `Z_out = R_L/(h_fe+1)`, which is wrong. No code changed
between them that touches formulas. A formula being right once is not
evidence; every note still has to be read against the book, and a wrong
formula is the failure mode to look for.

### Vision pass — `qwen3-vl:8b` on the four figures of the subsection

| figure | time | result |
|---|---|---|
| schematic | 61 s | correct: supply, input and output nodes and the component between them, all named |
| block diagram | 36 s | correct: both blocks, the two labelled impedances, the ground returns |
| small waveform | 246 s | **failed: empty response from the model** |
| plotted waveform | 56 s | correct: the clipping level and the offset at the positive peak |

The descriptions name components, labels and connections rather than
restating the caption, which is what the pass is for. One failure in four is
not a fluke to ignore: a 6.1 GB model on a 3.7 GB card thrashes, and an empty
response after four minutes is what that looks like.

**A failed figure costs nothing but time.** `stage_runs` holds it as `failed`,
so re-running the vision stage *without* `--force` retries exactly the
failures and skips the work already done. The note kept its
`description pending` line for that one figure and nothing else changed.

Not yet done: the protocol asks for ten schematics described by both
`gemma3:12b-it-qat` and `qwen3-vl:8b` before the keep-or-drop decision. This
is four figures and one model.

### Still untested

- OCR path (`pol+eng`): this book has a text layer on every page.
- The Gradio UI in a browser: `build()` constructs its 46 components against
  gradio 6.29.1, but no server was started.
- The ten-schematic model comparison the vision decision needs.

### Container

`podman build` succeeds and the image is **5.18 GB** with CPU-only torch. The
test suite runs inside it offline:

    podman run --rm --network none -v .:/src:ro -w /src glosator:latest pytest
    142 passed

Two defects the image exposed, both fixed, both in docs/DECISIONS.md: docling's
weights were unreadable under `--userns=keep-id`, and the CUDA wheels were
nine gigabytes of ballast.

---

## Protocol

The checklists below are the protocol from `CLAUDE.md`, for the full run.

## 1. Extraction — chapter 2

```bash
glosator add "/in/<book>.pdf" --title "<title>" --slug bk1 --out /out
glosator extract --book bk1 --pages <first>-<last> --ocr pol+eng
glosator worker        # or let the container's worker pick the job up
```

Check and record:

- [ ] Two-column pages: does the reading order survive, or do columns interleave?
- [ ] Formulas: inline maths kept, or mangled into prose?
- [ ] Tables: `do_table_structure` output usable?
- [ ] Figure crops in `work/bk1/figures/`: do the bounding boxes include the
      axis labels and the caption? If they clip, raise `FIGURE_PAD_PT`.
- [ ] `figures.json`: is `heading` the owning section?
- [ ] Pages that went through OCR (logged as `ocr_pages`): is `pol+eng` right,
      or does a single language do better?

## 2. Generation — chapter 2

```bash
glosator chunk --book bk1
glosator generate --book bk1
```

Read five notes against the book and record:

- [ ] Hallucinations: any claim not in the chunk.
- [ ] Component values and part numbers copied exactly.
- [ ] Glossary: are the Polish equivalents the terms actually used in Polish
      electronics usage?
- [ ] Length: inside 400-900 words?
- [ ] Only new files in the output folder: `git status` it, or diff a copy
      taken before the run. Nothing else there may change.
- [ ] Chunk sizes from `work/bk1/chunks.json` — anything over
      `CHUNK_MAX_TOKENS`, anything trivially short?
- [ ] Throughput: minutes per chunk, from the job's ETA column.
      Expectation to beat: 8-12 min per section.

## 3. Vision — 10 schematics

Pick 10 figures of varying density, describe each with `gemma3:12b-it-qat` and
with `qwen3-vl:8b`, and record both. Only one model fits in VRAM at a time, so
run them as two passes:

```bash
glosator vision --book bk1 --model gemma3:12b-it-qat
glosator vision --book bk1 --model qwen3-vl:8b --force
```

| figure | density | gemma3 | qwen3-vl | usable? |
|---|---|---|---|---|
| | | | | |

## 4. Decision

Keep or drop the vision pass. Record the outcome in `docs/DECISIONS.md`.
