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

### The hardened rules, same model, same chunk

The hard rules were written against the failures the review found, naming each
one. The chunk was then regenerated with `qwen2.5:32b` under them and read
against its source, with the two findings the 32B had left checked one by one.

| on the same note | 32B, earlier prompt | 32B, hard rules |
|---|---|---|
| time | 17 min | 16 min |
| words | ~800 | 770 |
| the biasing criterion | stated backwards | the right way round |
| the carried value | a number attached to the wrong quantity | gone: the ratio is given instead of the number |
| a second name for the circuit | — | **added one the source never uses** |

Both named failures are gone, and the rules cost nothing in time. A third rule
was broken instead: the model supplied a textbook synonym for the circuit that
does not appear in the chunk at all. A rule narrows a failure mode; it does
not close it, and the one it narrows is the one you thought to write down.

**The glossary is now the weakest part of the note.** It returned six pairs
where the prompt asks for five to fifteen, and four of the six are wrong on
the Polish side rather than the technical one: `collector current` rendered
with the word for a person who collects things instead of the established
term, `quiescent point` translated as though "quiescent" meant "quiet",
`high-pass filter` as two contradictory filter names run together, and one
term simply misspelled. None of these is obscure; they are the first entries
in any Polish electronics vocabulary.

So the model writes sound English prose and unreliable Polish terminology.
That is the measurement that decides the note language: see
`docs/DECISIONS.md`.

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

---

## Measured on 2026-11-01 — RTX 5070 Ti, "Design Your Own Video Game Console"

The laptop is gone. Machine: RTX 5070 Ti 16 GB (the desktop holds ~1.3 GB),
Ryzen 7 7800X3D, 30 GB RAM. Ollama 0.40.13 on the host with
`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`,
`OLLAMA_MAX_LOADED_MODELS=1`. Options as always: `num_ctx` 12288, temperature
0.25, `num_predict` 2048, `think: false`.

Book: 919 pages, English, text layer throughout. The outline names only the
eleven chapters; each chapter repeats the book's front matter and opens with
its own contents. Chunked by page range, one range per chapter body.

### Extraction

| | card | CPU |
|---|---|---|
| 20 pages (79-98) | **43 s**, peak 4.7 GB | 124 s |
| figures found | 17 | 17 |
| whole book, 911 pages, 23 batches | **925 s**, peak 5.6 GB, no fallback | — |

Formulas: docling's formula model kept the exponents the text layer drops
("P = V^{2}/R" where the text layer has the 2 on a line of its own), but it
reads this book's `*` multiplication into the exponent ("I^{2*}R") and now and
then a whole formula is garbage ("\sqrt" in a product-over-sum, "sin" for Vin).

915 pictures, of which 163 are the black callout tiles ("WARNING!", "TIP",
"NOTE", "INTERESTING FACT"); they are now dropped (no caption, ≤ 80 pt wide).
One pin table on page 751 came out at 36 kB of padding around 5 kB of
content; table padding is now stripped.

### Text — five chunks, two models

First cut (chunks up to the budget, not aligned to sections). Each pair of
notes was reviewed claim by claim against its chunk, one reviewer per chunk.

| chunk | 31b s | 26b s | 31b errors | 26b errors | 31b bad glossary | 26b bad glossary |
|---|---|---|---|---|---|---|
| 1.7 discrete components | 126 | 30 | 2 | 2 | 2/12 | 0/15 |
| 2.3 voltage dividers | 176 | 13 | 6, and 7 unreadable formulas | 0 | 1/10 | 1/15 |
| 4.1 logic symbols | 152 | 19 | 1 | 0 | 5/12 | 2/18 |
| 8.3 assembly language | 84 | 11 | 1 | 1 | 2/13 | 4/14 |
| 9.4 6502 system | 87 | 15 | 0 | 4 | 1/13 | 3/14 |
| **total** | **625** | **88** | **10** | **7** | **11/60** | **10/76** |

Speed: 31b 9.6-11.6 tok/s output, 26b 92-107 tok/s, both at ~15.6 GB on the
card. The prompt for chunk 9.4, code and pin tables, was 9488 tokens for a
chunk estimated at 5922: such text runs under three characters a token.

What the counts hide:

- **Eight of 31b's ten errors are formulas copied from the recognised LaTeX**
  as it stood: a square root in the parallel-resistor law, "sin/2" for Vin/2,
  "V = 1·R", and ".707" written as 707. The prompt told it to copy formulas
  and never reconstruct them, and it obeyed. 26b rewrote the same garbled
  lines correctly — and elsewhere added facts the source does not state (a
  cause for the 6502's reset vector, "TTL is faster", ceramic capacitors as
  non-polarised).
- **Coverage was poor for both**: a twelve-page chunk of several sections in a
  note of at most 700 words leaves most of it out — worked examples, pin
  numbers, threshold voltages, datasheet parameters.
- Few notes had a Pitfalls section even where the source warns plainly.

Changes made from this: the prompt now forbids copying a garbled formula and
asks for the formula the surrounding text states; chunks end where a numbered
section starts once they hold the minimum budget (77 → 87 chunks).

### Vision — ten figures, three models

`figure.md` prompt, one call per figure.

| model | per figure | result |
|---|---|---|
| `qwen3-vl:8b` | 3-9 s | most detail; ".1uF" read as "1uF" twice, "R/W" as "R/D", a pull-up put in series |
| `gemma4:26b` | 2-3 s | less detail, no wrong value seen; timing-diagram buses described as single lines |
| `gemma4:31b` | 10-25 s | one empty answer, one CUDA OOM encoding the image; out |

Decision: `gemma4:26b` (docs/DECISIONS.md).

### Text — after the formula rule and section-aligned chunks

`gemma4:31b` only, the same four subjects on the new chunk boundaries, the
same review.

| chunk | s | content errors | formulas wrong / artefacts only | bad glossary |
|---|---|---|---|---|
| 1.7 | 126 | 0 | 0 / 6 of 11 | 1/15 |
| 2.3 | 84 | 0 | 0 / 5 of 6 | 0/8 |
| 4.1 | 106 | 0 | 0 / 0 of 26 | 3/10 |
| 9.4 | 107 | 1 | 0 / 0 of 3 | 2/10 |
| **total** | **423** | **1 in ~140 claims** | **0 / 11 of 46** | **6/43** |

From ten content errors on these subjects to one: an invented cause, the
6502's reset vectors put at the top of memory "because it is little endian".
No formula carries a wrong meaning any more; eleven still carry recognition
artefacts that render legibly (`R1^{*}` for R1·R, `|` for I, digits spaced
out, which LaTeX ignores). Two formulas are wrong in the book itself (the
product-over-sum law for n resistors, a NAND chip select) and were copied
without comment; no rule asks the model to correct its source, and none
should.

Still weak: worked numbers, tables and practical warnings are left out, and
digital-logic glossary terms are calqued ("suma produktów" for sum of
products).

## Measured on 2026-11-02 — RTX 5070 Ti, four Polish C and C++ textbooks

Samples of 8–16 pages from each of four Polish programming books (an ANSI C
classic, a C++ reference, a C course and a book on pointers), `gemma4:31b`,
`--domain programming`. No text from the books is reproduced here.

**Before** (the pipeline of 2026-11-01): every code block reached the model
as one line, so a `//` comment swallowed the rest of its program and
preprocessor directives ran together; `&&` arrived as `&amp;&amp;`,
identifiers with underscores as `a\_b`, and a per-copy watermark digest sat
in the middle of sentences. Formula recognition turned code fragments into
LaTeX with a changed meaning (`<=` became an arrow). The note on the C
classic's first sixteen pages showed none of its nine programs and listed
four fake formulas.

**After** (listings rebuilt from the text layer, a `Code` section):

| Book | Pages | Notes | Listings in notes | Listing faults |
|---|---|---|---|---|
| ANSI C classic | 16 | 2 | 20 | 2 shifted six columns (prose line in docling's box; fixed since) |
| pointers | 13 | 1 | 23 | 0 |
| C course | 8 | 1 | 9 | 0 |
| C++ reference | 10 | 2 | 23 | 0 after the word-space fixes |

Listings split by a page break were joined by the model in every case seen,
program output went into separate `text` blocks, and no listing was
corrected, completed or invented. Two errors that are in the Polish editions
themselves (an assignment where a comparison is meant, a legal `sizeof`
marked illegal) were copied as printed, which is what the prompt asks.

Rebuilding the listings on the C++ sample first lost word spaces in the
comments, which are set in a proportional italic: gaps of 0.9–2.1 pt
against a 4.26 pt cell, and one of 0.22 pt where an italic "j" tucks under
the letter before it. A threshold of 0.15 cell plus the text layer's own
space characters restore all of them. That book also sets `->` with a
minus sign, U+2212, now written as ASCII.

The ten-page C++ chunk (about 5,600 tokens, half of it code) ran past
`num_predict` 3072. With the programming budget (2–4k-token chunks,
`num_predict` 6144, `num_ctx` 16384) it became two chunks, written in 4.9
and 2.3 minutes, with the model still on the card.

Unanswered exercises (the C classic gives no answers) were each filled with
"Answer: (no answer provided in source)"; the prompt now keeps them as bare
tasks.
