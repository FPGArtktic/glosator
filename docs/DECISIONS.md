# Decisions

Append-only. Each entry records a decision that the code assumes and that a
reader of `CLAUDE.md` would otherwise have to guess.

## 2026-10-04 — `/vault` is the book folder, not the vault root

**Superseded on 2026-10-04 by "the output folder is any directory" below.**

`CLAUDE.md` describes note paths as `/vault/<Book>/<NN-chapter>/<note>.md` but
the Podman mount is `<VAULT>/<Book>:/vault`. Both cannot hold. The mount wins:
`config.VAULT_DIR` points at the book folder and notes land in
`/vault/<NN-chapter>/<note>.md`. Changing the mount instead would give the
container write access to the whole vault, which is a bigger hole than a
shorter path is a gain.

## 2026-10-04 — Note file names are `<section> <Title>.md`

The output contract shows `<NN.MM-title>.md` as a file name but
`[[2.3 Previous section]]` as a wikilink. Obsidian resolves a wikilink by file
stem, so the two forms cannot both be right. File names follow the links:
`2.3.1 Section title.md`.

## 2026-10-04 — Four modules beyond the layout in `CLAUDE.md`

- `app/ollama.py` — both model passes need the same client, timeout and
  options. Duplicating them in `generate.py` and `vision.py` would let the two
  drift apart.
- `app/pdf.py` — page count, raw text and bookmarks are needed by extraction
  and by chunking. pypdfium2 (BSD/Apache) answers them without docling.
- `app/log.py` — JSON-lines logging is required by `CLAUDE.md` and used by
  every stage.
- `app/cli.py` — the pilot protocol needs to run stages without a browser.
  It only enqueues jobs, so the UI and the CLI run the same code path.

## 2026-10-04 — The model writes prose, the code writes structure

Frontmatter, the heading, the section order and the figure embeds are
assembled in `generate.assemble`, not asked of the model. A note's
machine-readable parts are part of the output contract; a 12B model
occasionally reorders or renames a heading, and a regression there is treated
as a broken vault.

The generator rejects output that lacks `## In short` or `## Explanation`; the
chunk is recorded as failed and retried on the next run rather than written
half-formed.

## 2026-10-04 — Vision state is keyed per figure

`stage_runs` holds `vision:<figure id>` as the stage name for the figure pass,
so a book with 400 figures resumes figure by figure instead of chunk by chunk.
`db.clear_stage(book, "vision")` clears the colon-suffixed rows too.

## 2026-10-04 — OCR decision is per page range, not per page

`extract.pages_needing_ocr` counts extractable characters per page and
docling's OCR is switched on for the run when any page is below the threshold;
docling then OCRs the regions that need it rather than every page
(`force_full_page_ocr` stays off). Per-page control of the docling pipeline
would mean one conversion call per page, which costs far more than it saves.

## 2026-10-04 — Schema migrations are an append-only list

`db._MIGRATIONS` is indexed by schema version and applied against
`PRAGMA user_version`. Editing an existing entry would silently skip the
change on an existing database; add a new entry instead.

## 2026-10-04 — docling models are baked into the image

The container has no network at run time (`Internal=true` on the Quadlet
network), so `Containerfile` runs `docling-tools models download` at build time
with `HF_HOME=/opt/models`, then sets `HF_HUB_OFFLINE=1` and
`TRANSFORMERS_OFFLINE=1`. A model that is missing then fails the run loudly
instead of trying to fetch itself on the first page.

## 2026-10-04 — Tests run as `pytest`, not `uv run pytest`

`CLAUDE.md` documents `uv run pytest` inside the container. `uv run` resyncs
the environment, which needs the network the container does not have. The
image installs the `dev` extra instead, so the command is:

    podman run --rm -v .:/src -w /src glosator:latest pytest

## 2026-10-04 — The output folder is any directory, and is guarded

The notes folder is chosen by the user and is not assumed to be an Obsidian
vault: `config.OUT_DIR` (`/out` in the container, `GLOSATOR_OUT` on the host,
or per book in `books.out_dir`). An existing note collection must survive a
bad run, so three rules hold in code, not in documentation:

- Every generated file carries `generator: glosator` in its frontmatter.
  `generate.check_writable` refuses to overwrite a file that does not, so a
  hand-written note at a path glosator wants is left alone and the chunk is
  recorded as failed.
- `generate.check_inside` resolves every target path and refuses anything that
  leaves the output folder. A section title of `../../..` cannot escape.
- Directories glosator creates inside the output folder are stamped with a
  `.glosator` file. `generate.claim_dir` refuses a non-empty directory without
  the stamp, which is what protects an existing `attachments/` folder.

The index stage only links notes that carry the marker; foreign files at note
paths are counted in the log and skipped.

Nothing is ever deleted from the output folder, by any stage.

## 2026-10-04 — An outline that cannot be trusted is reported, not repaired

`chunk.outline_problems` names what is wrong with a PDF's bookmarks
(no outline, destinations pointing backwards, no numbered sections) and the UI
shows it under the TOC. Chunking still runs: the code cannot know which of two
contradictory destinations is right, and guessing would produce notes about
the wrong pages without saying so.

The first book tested is a case in point: 62 bookmarks, chapter level only,
three of them pointing at the printed contents pages. For that book, chunking
has to be driven by page ranges.

A span ends at the next bookmark that does not point backwards, so one broken
destination cannot collapse a whole chapter into a single page.

## 2026-10-04 — A page range is a boundary, and is cut to fit

**Amended the same day, after the first real use.** A range the operator draws
says where a part of the book begins and ends; it does not say how much a
model can read at once. Pressing "run everything" on pages 13-56 produced one
chunk of 28607 tokens, nearly five times `CHUNK_MAX_TOKENS` and twice
`num_ctx`, which the generate stage refused — correctly, but the only way
forward was to type eight ranges by hand.

`chunk.split_to_budget` now cuts a range into consecutive slices that fit,
packing whole pages greedily. Ranges are still never merged across, and a
single page over the budget stays whole and is refused, because splitting a
page would cut a sentence.

## 2026-10-04 — An oversized chunk fails instead of being truncated

A chunk can still exceed the budget: one enormous page, or a bookmarked
section longer than the window. Ollama would silently drop the
overflow and the note would describe half a section without saying so.
`chunk.plan` logs every chunk over budget and `generate.run` refuses it before
calling the model, so the chunk is recorded as failed and the page range can
be split.

## 2026-10-04 — A chunk without a numbered bookmark is named by the running head

The first target book's outline is unusable, so chunks come from page ranges
and carry no section number. `chunk.running_head` reads the head the book
prints on every page ("4.07 Limits of the sampling method 214") and takes the
number seen most often in the chunk, earliest wins a tie. A numbered bookmark
still wins outright; when neither exists the chunk is numbered by position.

This is read off the page, not inferred: the alternative was typing eighty
section titles by hand, or parsing the printed contents and guessing the
offset between printed and PDF page numbers.

## 2026-10-04 — An unnamed chapter's folder is its number

`chapter_titles` only names a chapter when a chunk *is* that chapter. Calling
chapter 3's folder `03-limitations-of-fet-switches` because that is its first
section would be worse than `03`.

## 2026-10-04 — LaTeX delimiters are normalised, not merely requested

The prompt asks for `$...$`, and the model writes `\[ ... \]` anyway; Obsidian
renders neither of the LaTeX forms. `generate.normalise_math` rewrites them
before the note is assembled. Asking a 7B model twice is not a fix.

## 2026-10-04 — docling runs on the CPU, always

Measured, not assumed: with `qwen2.5:7b` resident in Ollama (3.03 GB of the
3.73 GB the RTX 3050 Mobile reports), docling's layout model died with
`torch.OutOfMemoryError: Tried to allocate 50.00 MiB ... 66.44 MiB is free`.
The extraction completed, because docling logs `Stage layout failed` and
carries on, which is worse than failing: the output is silently degraded.

`extract._convert` pins `AcceleratorOptions(device=CPU)`. The GPU belongs to
Ollama. Extraction costs seconds per page on the CPU against hours of
generation, so there is nothing to win by sharing the card.

This is the same constraint `CLAUDE.md` states for the text and vision passes,
and docling is a third model that nobody counted.

## 2026-10-04 — docling's weights are baked to an explicit, world-readable path

`docling-tools models download` ignores `HF_HOME` and writes to
`$HOME/.cache/docling`. With `--userns=keep-id` the container's `$HOME` is not
the one that existed at build time, so the 1.4 GB of weights baked as root sat
behind a permission error:

    podman run --user 1000:1000 ... ls /root/.cache/docling
    ls: cannot access '/root/.cache/docling': Permission denied

With `HF_HUB_OFFLINE=1` on top, the first extraction in the deployed container
would have failed on its first page. The image now downloads to
`/opt/models/docling`, runs `chmod -R a+rX`, exports
`DOCLING_ARTIFACTS_PATH`, and `extract._convert` passes `artifacts_path`
explicitly rather than trusting docling's default.

Testing the image as root would never have shown this.

## 2026-10-04 — The image installs CPU-only torch

docling is pinned to the CPU, so the CUDA wheels were several gigabytes that
nothing could ever use. Installing torch and torchvision from
`download.pytorch.org/whl/cpu` before the project took the image from
**14.7 GB to 5.18 GB**.

## 2026-10-04 — glosator is started on demand and holds the GPU only while working

The machine runs other local AI tools every day and has 4 GB of VRAM, so a
service that sits resident is the wrong shape. Two consequences in code:

- The Quadlet unit has no `[Install]` section and `Restart=no`. Nothing starts
  at login and nothing resurrects itself. `bin/glosator` drives the unit:
  `install`, `build`, `start` (waits for the port, opens the browser), `stop`
  (also unloads the models), `status`, `logs`, and `cli ...` into the running
  container.
- The worker unloads the model from Ollama when a job ends, with
  `keep_alive: 0`. Within a job the model stays resident, because reloading
  eight gigabytes per chunk would dominate a twenty-hour run; between jobs it
  must not. A failed unload is logged, never fatal: the job is already done
  and Ollama frees the card on its own eventually.

`bin/` is a directory `CLAUDE.md` does not list. The launcher only drives the
Quadlet unit, so there is still one source of run configuration.

## 2026-10-04 — The subject of a book is per book, not electronics

The first target book is an electronics textbook and the prompts said so, as
did the first tag of every note. Books will come from other fields, so the
subject is a column on `books`, reaches `note.md`, `figure.md` and `moc.md`
through the `{{domain}}` placeholder, and becomes the first tag, slugified:
`tags: [mathematical-statistics, stat1, chapter-02]`.

The glossary examples in `note.md` deliberately span three fields and say so.
They are there to show the form — `term — polski odpowiednik` — and three
electronics examples in the prompt for an anatomy book would pull the model
toward the wrong vocabulary.

## 2026-10-04 — The container reaches Ollama through the host's loopback

Ollama listens on `127.0.0.1:11434`. Measured, a container cannot reach that
on any ordinary network: the shared internal network gives
`Network is unreachable`, and the default rootless network and a plain bridge
both give `Connection refused`, because `host.containers.internal` points at
the host's external address, not its loopback.

The unit therefore runs with `Network=pasta:--map-host-loopback,169.254.1.2`
and `OLLAMA_URL=http://host.containers.internal:11434`. That is the narrowest
door that works: the container sees the host's loopback and nothing else of
the host. Nothing has to change on the Ollama side, which matters because the
same Ollama serves the user's other tools.

`quadlet/glosator.network` is gone with it. An internal network is only right
when Ollama runs as a container on it, and then `OLLAMA_URL` names that
container; the unit's comments say so.

## 2026-10-04 — The launcher validates before systemd does

A missing mount makes podman fail with `statfs ...: no such file or directory`
and systemd report `status=125`, which says nothing about what to do.
`bin/glosator install` takes the two folders as arguments and writes them into
the unit, and `start` checks every mounted path first, warns when no Ollama
answers, and refuses with the command that fixes it. `uninstall` removes the
unit and deletes nothing else, printing where the notes, the database, the
image and the models remain.

The published port is checked on `127.0.0.1`, not `localhost`: pasta publishes
on IPv4 only and `localhost` resolves to `::1` first, so the readiness check
reported a dead server that was in fact running.

## 2026-10-04 — The prompt forbids what the model actually got wrong

Six notes were reviewed against their source chunks by eighteen independent
readers, each finding adversarially checked by a sceptic; 38 findings were
refuted and 115 survived, 60 of them errors. The mechanics were clean — every
figure embed resolved, the navigation chain held, the merged glossary was
exact — and the content was not usable: the signal was said to enter a
follower at the emitter, the impedance roles were reversed, a comparator was
said to work in its linear region, two renderings of the Ebers-Moll equation
were wrong, a Darlington was placed in a figure that has none, and two
formulas appeared in a section whose source contains no equation at all.

The prompt's hard rules now name those failure modes one by one, because a
general instruction to be faithful prevented none of them. The glossary
instruction had already shown this: one line asking for Polish produced none,
and three worked examples produced eleven correct term pairs.

A larger model is the other half of the answer; the rules are the half that
costs nothing per note.

## 2026-10-04 — The text model is qwen2.5:32b, which supersedes the table in CLAUDE.md

`CLAUDE.md` fixes the text model at `gemma3:12b-it-qat`, chosen for fitting
4 GB of VRAM with CPU offload. Measured against the review, it does not earn
the row. Both models were given the identical chunk, the identical prompt and
the identical reviewers — three independent lenses, every finding handed to a
sceptic who tried to refute it:

|                    | gemma3:12b-it-qat | qwen2.5:32b |
|--------------------|-------------------|-------------|
| confirmed findings | 30                | 9           |
| of them errors     | 19                | 5           |
| time for one note  | ~4 min            | 17 min      |

The kinds changed as much as the counts. The 12B model wrote that the signal
enters an emitter follower at the emitter, invented a "common cathode
amplifier", reversed which impedance is high, and put two formulas in a
section whose source contains no equation. What survives at 32B is subtler: a
biasing criterion stated backwards, and a value carried from the right
quantity to the wrong one.

The cost is four times the wall clock: roughly 85 hours for a whole book
rather than 20. That is the trade, and it is the right way round for notes
someone will study from. The model stays per job: `--model` on the command
line, a dropdown in the interface, and `GLOSATOR_TEXT_MODEL` for the default,
so a long run on a book that matters less can still use the 12B.

One of the 32B model's two remaining errors is not its fault. The source at
that point is damaged: OCR dropped the displayed inequality and left "In this
case," followed by nothing, so the model reconstructed the rule from prose and
reconstructed it backwards. No model reads a formula that extraction lost.

## 2026-10-04 — The note body stays English; the glossary is checked, not trusted

The question was whether to write the notes in Polish now that a larger model
generates them. `qwen2.5:32b` does write Polish, so the question is only
whether it writes Polish worth studying from. On the measured note it does
not: four of six glossary pairs were wrong on the Polish side while the
English prose around them was sound — a literal rendering of "quiescent", the
wrong sense of "collector", two filter names fused into one, a misspelling.
Those are the easy terms. A body in Polish would put that failure rate through
every sentence instead of six lines, where it is far harder to spot, and would
cost roughly 40 percent more output tokens on top of the 85 hours a book
already takes.

The glossary stays as the place where Polish appears, and the README now says
plainly that it is the least reliable part of a note.

This is a measurement about one model, not a conclusion about the language. A
model that knows Polish technical usage would reopen it: the body language is
a prompt line, not an architectural choice, and the hard rules would carry
over unchanged.

## 2026-10-08 — A stage that stops where the model starts

A book costs on the order of 85 hours of this machine's GPU. Extraction and
chunking cost minutes: seconds per page, on the CPU, and they are the part
this machine does well. The output of that cheap half is a book cut into
sections with their page ranges recorded — which is most of what anyone needs
to write notes from it, whoever writes them.

Nothing could read it. The section text sat in `work/<slug>/chunks/` under
names like `001-2-03.md`, with no indication of which book or which pages it
came from, in a directory that exists for the worker's benefit. So the choice
was to generate locally or to get nothing.

The `export` stage writes those sections into the notes folder instead, one
markdown file per section, each with its source, section number and page
range in frontmatter and the figure crops of those pages linked beside it. It
imports no Ollama client. That absence is the stage: a UI button that promises
no GPU has to be a path on which no GPU call is reachable, not one where it
happens not to be made.

Three decisions inside it.

**The files go to `<notes>/_source/<slug>/`, not to `work/`.** The work
directory is the worker's, gitignored and structured for its convenience; the
notes folder is the one the operator already chooses in the interface and
already looks in. The leading underscore keeps the book's own text sorted away
from the notes written about it. They carry `generator: glosator`, so the
existing ownership check covers them unchanged: a rerun replaces its own
output and refuses anything else, exactly as for a note.

**The instructions go in one `_PROMPT.md`, not at the head of every file.**
They are the same instructions every time. Repeating them across eighty files
is eighty copies to keep in step with `prompts/note.md`, and the duplication
is already one copy more than is comfortable — `prompts/export.md` restates
the same contract for a reader that gets one file at a time, and says in its
own text that `note.md` is where the rules are maintained.

**The export is cut larger than the notes pass: 12–20k tokens of source
rather than 3–6k.** The local budget exists because 4 GB of VRAM exists.
Nothing at the other end has that limit, so cutting a chapter into
six-thousand-token pieces would only mean more files to hand over for no
reason. This needed `chunk.plan` to take a budget rather than read one from
`config`, and the two budgets carry their own subfolder and manifest so a
second pass over the same book cannot land on the first one's files.

What this does not do is check the result. A note written elsewhere does not
pass through `generate.assemble`, so its frontmatter, section order and figure
embeds are whatever the model produced, and the `index` stage will treat a
file without the generator marker as someone else's and leave it alone. Notes
brought back from an export are the operator's to place.
