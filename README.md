# glosator

glosator turns a PDF or EPUB textbook into a set of sequential, linked study
notes. It
runs entirely on the local machine: no cloud API, no telemetry, and no network
access beyond a local Ollama instance.

*Glosator* (Polish) means a glossator: the person who writes glosses, short
explanatory notes on a difficult text. That is the function of this program.

Given a book and a range of pages, it writes one Markdown note per section,
containing a summary, a plain-language explanation, the formulas, the figures
cropped from the page, a bilingual glossary and the pitfalls the source warns
about. The notes are plain files with YAML frontmatter and `[[wikilinks]]`:
Obsidian reads them, and so do ordinary command-line tools.

Writing a book's notes on the reference machine takes on the order of 85
hours. The half before the model call takes minutes, so the pipeline can also
stop there: the `export` stage writes the book's own extracted text out as one
markdown file per section, ready to hand to a model elsewhere. See
[Without a local model](#without-a-local-model).

## Example output

A note has the structure below. Both the book and its content are invented
for this illustration. No passage of any real work is reproduced anywhere in
this repository, including in the test suite.

```markdown
---
source: "Example Textbook, 1st ed."
chapter: 4
section: "4.07"
pages: [212, 215]
model: gemma4:31b
generated: 2026-11-01
generator: glosator
tags: [signal-processing, bk1, chapter-04]
---
# 4.07 Limits of the sampling method

## In short
Sampling a continuous signal at a finite rate discards everything above half
that rate. The discarded content does not vanish quietly: it reappears as a
lower-frequency component that cannot afterwards be separated from the signal
that was wanted.

## Explanation
Plain-language prose, three to seven hundred words, with every symbol it uses
explained. Analogies are allowed but have to be marked as analogies.

## Formulas
$$f_{s} > 2 f_{max}$$
The condition on the sampling rate for the band-limited case.

## Figures
![[attachments/bk1/fig-212-1.png]]
*Figure 4.19. Aliasing of a tone above half the sampling rate. — The figure
plots amplitude against frequency, with the original tone and its alias marked
on either side of the folding frequency.*

## Glossary
- sampling rate — częstotliwość próbkowania
- aliasing — aliasing
- folding frequency — częstotliwość Nyquista

## Pitfalls
- A filter applied after sampling cannot undo aliasing, because the aliased
  component now occupies the same band as the signal.

## Exercises
1. A 30 kHz tone is sampled at 44.1 kHz. At what frequency does it appear?
   Answer: at 14.1 kHz, its alias below half the sampling rate.

---
[[4.06 Previous section]] · [[4.08 Next section]]
```

Notes are written in the language of the book. An English book gets an
English body with Polish equivalents in the glossary; a Polish book gets a
Polish body, Polish headings, and English equivalents in the glossary, so a
subject can be looked up in either language. The language is judged from the
book's text; `add --lang en` or `--lang pl` sets it outright.

The glossary is also the least reliable part of a note. A model that writes
sound prose still renders terms badly across languages: on one measured note,
four of six pairs were wrong on the Polish side while the surrounding
explanation was correct. Read the glossary; do not learn from it.
`docs/DECISIONS.md` records why an English book's notes are not written in
Polish.

## Requirements

- Podman, rootless. Nothing is installed on the host.
- [Ollama](https://ollama.com) with a text model, by default `gemma4:31b`;
  `gemma4:26b` is the fast choice in the interface, seven times faster for a
  few more errors (`docs/DECISIONS.md`). The vision model is optional.
  `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` on the Ollama
  service halve the context's memory, which leaves more of the model on the
  card; `OLLAMA_MAX_LOADED_MODELS=1` keeps it to one model at a time.
  Ollama normally listens on `127.0.0.1`, which a container cannot reach
  through an ordinary network, so the unit runs the container with
  `pasta --map-host-loopback` and points `OLLAMA_URL` at
  `host.containers.internal`. Nothing has to be changed on the Ollama side.
  To use an Ollama container instead, put both on a podman network and set
  `OLLAMA_URL` to that container's name.
- A GPU is not required, but it is used. The reference machine has an
  RTX 5070 Ti with 16 GB. docling runs on the card when nvml reports it free
  and on the CPU otherwise; the text model is larger than the card and runs
  partly on the CPU. The container gets the card through CDI:
  `sudo systemctl enable --now nvidia-cdi-refresh.path nvidia-cdi-refresh.service`.

## Quick start

Build the image, then install the systemd unit for the two folders you want
to use: the folder your books are in, and the folder the notes go to. Both
steps are needed once.

```sh
bin/glosator build
bin/glosator install ~/Documents/books ~/Documents/notes
```

The books folder is mounted read-only. The notes folder is created if it does
not exist and may be any directory; see
[Safeguards for an existing note collection](#safeguards-for-an-existing-note-collection)
before pointing it at notes you already have.

```sh
bin/glosator start
```

This starts the container, waits for the server and opens
`http://127.0.0.1:7860`. In the browser: select a book, choose sections from
the table of contents or enter page ranges, preview the extraction on a few
pages, and queue the stages. Progress, the log and the most recent note are
visible while the job runs; closing the browser does not stop it.

The same work can be done from the command line. Paths are the ones inside
the container, so a book sits in `/in` and the notes go to `/out`.

```sh
bin/glosator cli add "/in/book.pdf" --title "Calculus" --slug calc1 \
    --domain calculus --out /out
bin/glosator cli extract  --book calc1 --pages 71-96
bin/glosator cli chunk    --book calc1
bin/glosator cli generate --book calc1
bin/glosator cli index    --book calc1
bin/glosator cli queue
```

Or, stopping before the model:

```sh
bin/glosator cli extract --book calc1 --pages 71-96
bin/glosator cli export  --book calc1 --pages 71-96
```

When the work is done, stop it. `stop` also unloads the models, so the GPU is
free for whatever else uses it.

```sh
bin/glosator stop
```

`bin/glosator status` says whether it is running and what currently holds the
GPU; `bin/glosator logs` follows the container log. `bin/glosator uninstall`
stops it and removes the systemd unit, and deletes nothing else: your notes,
the work directory, the job database, the image and the Ollama models are all
left where they are, and the command prints where that is.

glosator is not a service. Nothing starts at login, nothing restarts itself,
and the model is unloaded from VRAM when a job ends. Within a single job the
model stays resident, because reloading several gigabytes of weights for
every chunk would dominate the running time.

## How it works

The pipeline has six stages. Extraction and chunking prepare the source;
generation writes the notes; the figure pass and the index are applied
afterwards. The export stage is an alternative to the last three: it stops
where the model would start.

| stage | description |
|---|---|
| extract | docling with a tesseract backend. OCR is applied only to pages whose text layer is too thin to use. Figures are cropped from the page together with their captions. |
| extract (EPUB) | No model: the markup is the text. Listings keep their lines and indentation; figures are left out and their captions kept. The text is cut into pages of about 3,000 characters, each bookmark starting a page of its own, so that the stages after it read an EPUB as they read a PDF. |
| chunk | Splits the book by its bookmarks (a PDF's outline, an EPUB's table of contents), or by page ranges supplied by the operator. A section is never split; a section too small to warrant a note is merged with the sections that follow it. |
| generate | One model call per chunk, producing one note. |
| vision | Optional and separate: one call per figure, with the description inserted beneath the figure in its note. |
| index | Chapter maps, the combined glossary, and previous/next links. No model is involved. |
| export | The extracted sections written out verbatim, one file per section, for a model that is not on this machine. No model is involved. |

Each stage records its completed work in SQLite, keyed on the tuple
`(book, chunk, stage, model)`. The container can be killed at any point: the
next run resumes rather than starting again, a chunk that failed is retried,
and a chunk that succeeded is not rewritten. Re-running the figure pass
retries precisely the figures that failed.

## Checking a book's notes

`glosator verify --book SLUG [--chapter N]` checks the notes written so far
against the text each was written from, at once and without a model, and
prints one line per chapter:

```
chapter 5: 6/6 notes, listings 412/415 lines (409 exact), 0 flagged
```

A note is flagged when a programming book's listings did not reach it (under
90% of the source's listing lines, compared with spacing squeezed; "exact"
counts the lines with their indentation as printed), when a watermark digest
or a mail address the source does not have got in, or when it has fewer
words than a tenth of its source. The exit status is 1 when any note is
flagged, so a run can be checked chapter by chapter while it goes on.

## Without a local model

The **Run without a local LLM** button, and the `export` stage behind it, run
extraction and then write the sections out as they are. No Ollama call is
made and the GPU stays idle.

```
<notes>/
  _source/
    calc1/
      _PROMPT.md                 the instructions, once per book
      04-sampling/
        4.07 Limits of the sampling method.md
      figures/
        fig-212-1.png
```

Each file carries the book, the section number and the page range in its
frontmatter, then the figures of those pages, then the source text. The
instructions are in `_PROMPT.md` rather than at the head of every file,
because they are the same instructions every time: hand that over once, then
a section file per note wanted.

These files are cut larger than the ones the local model is given — 12 to 20
thousand tokens rather than 3 to 6 — because nothing has to fit in the local
model's context window at the other end. `GLOSATOR_EXPORT_MIN_TOKENS` and
`GLOSATOR_EXPORT_MAX_TOKENS` change that.

The exported files carry `generator: glosator`, so the same safeguards below
apply to them: a rerun replaces its own output and nothing else.

## Safeguards for an existing note collection

The output folder may be any directory, including one inside a collection of
notes that already matters to its owner. Three rules are enforced in code:

- Every generated file carries `generator: glosator` in its frontmatter. A
  file without that marker is never overwritten, and the index stage skips it
  rather than rewriting its links.
- Every target path is resolved before use and refused if it falls outside
  the output folder.
- Directories created by glosator are stamped. A non-empty `attachments`
  folder that it did not create is left untouched.

Nothing is deleted at any point. Notes are written to a temporary file and
renamed into place, so an interruption leaves either the previous note or the
new one, never a partial file.

## Books from any field

The subject of a book is recorded per book and reaches both the prompts and
the first tag of every note.

```
--domain "organic chemistry"   ->   tags: [organic-chemistry, chem2, chapter-04]
```

So is the language of its notes, when the text alone should not decide it:

```
--lang pl   ->   ## W skrócie … ## Słowniczek, with "polski termin — English term"
```

A programming book keeps its code. With `--domain programming`, extraction
rebuilds each listing's lines and indentation from the PDF's text layer, and
its notes carry a `Code` section, with the listings copied verbatim, in place
of `Formulas`:

```
--domain programming   ->   ## Explanation … ## Code (```c … ```) … ## Glossary
```

## Measured performance

Measured on the reference machine: RTX 3050 Mobile with 4 GB of VRAM, 64 GB of
system memory.

| measurement | value |
|---|---|
| extraction | approximately 2 seconds per page, on the CPU |
| generation, `qwen2.5:32b` (the default) | approximately 16 minutes per chunk, for 5900 tokens of source and roughly 800 words of output |
| generation, `gemma3:12b-it-qat` | approximately 4 minutes per chunk, for 2100 tokens of source |
| a book of 1000 pages | on the order of 85 hours with the default model, 20 with the smaller one; resumable at any point |
| container image | 5.18 GB |

`docs/PILOT.md` contains the full measurements, including a comparison between
models and the failures observed.

## Status

The pipeline has been run from end to end on a real book and every stage has
produced real output, and the deployed container has been verified serving the
interface and reaching a host Ollama. It has not yet been run across a complete
book, the OCR path has not been exercised on a scanned document, and the
question of whether to keep the figure pass remains open.

One observation should be stated plainly, because it determines how the output
ought to be used. Given the identical chunk twice, the same model produced a
correct output impedance formula in one run and an incorrect one in the next.
The notes must be read against the book. This program makes a long book
tractable; it does not make its output authoritative.

## Configuration

Configuration is confined to `app/config.py` and the environment.

| variable | default | meaning |
|---|---|---|
| `GLOSATOR_IN` | `/in` | folder the books are read from, mounted read-only |
| `GLOSATOR_OUT` | `/out` | folder the notes are written to |
| `OLLAMA_URL` | `http://ollama:11434` | address of the Ollama instance |
| `GLOSATOR_TEXT_MODEL` | `gemma4:31b` | model used for the text pass |
| `GLOSATOR_FAST_MODEL` | `gemma4:26b` | the interface's "fast" choice |
| `GLOSATOR_VISION_MODEL` | `gemma4:26b` | model used for the figure pass |
| `GLOSATOR_OCR_LANGS` | `pol+eng` | tesseract languages |
| `GLOSATOR_DOCLING_DEVICE` | `auto` | `auto`, `cuda` or `cpu` for the extraction |
| `GLOSATOR_EXTRACT_MIN_FREE_MB` | `6000` | free VRAM `auto` needs before using the card |
| `GLOSATOR_FORMULAS` | `1` | `0` turns off formula recognition |
| `GLOSATOR_DOMAIN` | `general` | subject assumed for a book that specifies none |
| `GLOSATOR_EXPORT_MIN_TOKENS` | `12000` | smallest export file, in tokens of source |
| `GLOSATOR_EXPORT_MAX_TOKENS` | `20000` | largest export file, in tokens of source |

## Development

```sh
uv venv && uv pip install --python .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The test suite requires neither docling, nor a GPU, nor a running Ollama. The
container runs the same suite without network access:

```sh
podman run --rm --network none -v .:/src:ro -w /src glosator:latest pytest
```

`docs/DECISIONS.md` records the reasoning behind the design, including the
points at which measurement contradicted the original plan.

## Out of scope

Retrieval-augmented generation, vector databases, embeddings, cloud APIs and
Windows support. This is a batch job, not a retrieval system.

## Copyright: for your own study only

Most textbooks are under copyright, and a note can carry the book's own words:
a quoted definition, an exercise and, for a programming book, its code
listings, copied verbatim on purpose. glosator is meant for one use only:
study notes, for yourself, from a book you own a lawful copy of.

- Run it only on books you have lawfully bought or otherwise lawfully have.
- Keep what it produces for your own private use. Do not publish, upload or
  pass on the notes, the extracted text in `work/` or the `_source` export of
  a book under copyright.
- The author of glosator accepts no responsibility for how anyone uses it,
  and none for notes or extracts that someone else shares. Whoever shares
  them answers for it.

This repository holds no text from any book. The tests use code and text
written for them.

**Po polsku:** robienie notatek z książek chronionych prawem autorskim jest
dozwolone wyłącznie na własny, prywatny użytek, i tylko z książki, którą
posiadasz legalnie. Nie udostępniaj notatek ani wyciągniętego tekstu. Autor
glosatora nie odpowiada za to, że ktoś takie notatki udostępni.

## License

GPL-3.0-or-later; see [LICENSE](LICENSE).

The notes produced by the program are not covered by that license. They belong
to whoever ran it, within the limits set out under "Copyright" above.
