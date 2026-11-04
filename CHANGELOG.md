# Changelog

Notable changes to glosator, newest first. Versions follow
[semantic versioning](https://semver.org/); each one is a tag on `master`.
The reasons behind the larger decisions are in
[docs/DECISIONS.md](docs/DECISIONS.md).

## [0.7.3] — 2026-11-04

### Changed
- An answer that fails the checks is asked for again with the listing
  lines and table rows it left out named at the end of the prompt, at
  most 60 of them.

## [0.7.2] — 2026-11-03

### Fixed
- `verify` finds a listing that docling laid out as a table in the note's
  code: a row counts when every word of it is in the code and at least
  two of them are not numbers.

## [0.7.1] — 2026-11-03

### Fixed
- A slide template's title bar (a logo and the slide's title) is not a
  figure. An uncaptioned picture with the same left edge, top and bottom
  on five pages or more is left out.

## [0.7.0] — 2026-11-03

### Changed
- A chunk under 150 tokens joins the chunk before it in its chapter. Only
  one with nothing to join and under 50 tokens (a part's divider, a title
  page) is left out; before, everything under 150 was, a chapter's
  summary and a training's last lab with it.

### Fixed
- The sections of a deep outline are cut at their titles. Sections that
  share a page each read the whole page, so a chunk of several sections
  held it several times: 38-58% of a lab book's text were repeats.
- A section title is found on a page that prints it without the number
  glosator gave it, or with a number of its own ("0.13 Memory split").

## [0.6.11] — 2026-11-03

### Fixed
- `verify` compares a table row without the empty cells that close it, so
  a note that adds an empty last column still matches its source.

## [0.6.10] — 2026-11-03

### Fixed
- `verify` flags a 32-character digest as a watermark only when the source
  does not print it. A checksum in a Yocto recipe is the book's own text.
- `verify` reads an escaped ruling (`&#124;`) that OCR left in a table cell
  as a space, so the row matches the note's.

## [0.6.9] — 2026-11-03

### Fixed
- A section cut at a title inside a listing keeps its code fences paired.
  The listing is reopened at the start of the part and closed at its end,
  so code and prose no longer swap places for the model and for `verify`.

## [0.6.8] — 2026-11-03

### Fixed
- A publisher's front and back matter bookmarked page by page (cover,
  title page, copyright, dedication, contributors, "About Packt", "Other
  Books You May Enjoy") is left out of the plan. The preface stays.

## [0.6.7] — 2026-11-03

### Fixed
- A bookmark whose title differs from its page's heading by a space between
  two letters ("Stał e" for "Stałe") takes the page's spelling, so the
  note's title and file name are spelled right.

## [0.6.6] — 2026-11-03

### Fixed
- `verify` reads LaTeX arrows (`\leftarrow`, `\Rightarrow`, …) and logic
  symbols (`\neg`, `\land`, `\equiv`, …) in table cells as the characters
  they stand for. Before, an instruction table written as
  `$A \leftarrow B$` counted as lost and the note was generated twice.

## [0.6.5] — 2026-11-03

### Fixed
- `verify` compares a table cell without its `$` delimiters, reading common
  LaTeX symbols (`\infty`, `\neq`, `\times`, …) as characters.
- `verify` finds a source row under a cell spanned over several rows when
  the note repeats the spanned cell. A full row still has to match whole,
  so the rows of a truth table are not found inside each other.

## [0.6.4] — 2026-11-03

### Fixed
- A section whose title starts with "Bibliografia" or "Bibliography" is
  left out of the plan even when it has a section number and a longer
  title, such as "13.2 Bibliografia w porządku alfabetycznym".

## [0.6.3] — 2026-11-02

### Fixed
- An answer cut off at the length limit is asked for once more with the
  wider window a programming book gets, instead of failing the chunk.
  Exercises sections, whose note copies every task, ran past it.

## [0.6.2] — 2026-11-02

### Fixed
- A section with nothing to hold says so in the note's language ("Brak w
  tej sekcji."). Polish notes used to copy the prompt's English sentence.

## [0.6.1] — 2026-11-02

### Changed
- Books in the "embedded Linux" field keep their listings verbatim, as
  programming books do.

## [0.6.0] — 2026-11-02

### Added
- Slide decks: a PDF whose pages are mostly landscape is read as training
  slides and gets a prompt of its own (`prompts/slides.md`).
- An outline without section numbers is numbered: top-level bookmarks
  become chapters, their children sections.
- Page furniture (a footer or header repeated on most pages) is left out of
  the text the model reads.

## [0.5.3] — 2026-11-02

### Changed
- The next part of a section cut in two is marked "(continued)".

## [0.5.2] — 2026-11-02

### Fixed
- `verify` matches a table row whose code the note sets in backticks.

## [0.5.1] — 2026-11-02

### Fixed
- A chapter's map has a name of its own ("— chapter map" or "— mapa
  rozdziału"). The index stage used to overwrite the chapter's note with it.

## [0.5.0] — 2026-11-02

### Changed
- Note files are named with padded section numbers (`01.02` sorts before
  `01.10`), and a chapter's own note by its number (`01 Introduction`).

## [0.4.1] — 2026-11-02

### Changed
- A one-line fragment the book displays (a cast, a prototype) goes into the
  Code section.
- `verify` counts code quoted in the text or in a table as found.

## [0.4.0] — 2026-11-02

### Added
- An answer that fails the `verify` checks is asked for again
  (`GENERATE_RETRIES`), and the better of the two is kept.

## [0.3.3] — 2026-11-02

### Added
- `bin/text-model`: builds a Q3 text-only model that fits a 16 GB card.

## [0.3.2] — 2026-11-02

### Added
- Tables in the source are copied into the note whole, and `verify` checks
  that they arrived.

### Fixed
- `verify` finds a listing line that the book quotes without its comment.

## [0.3.1] — 2026-11-02

### Fixed
- The note of a merged chunk covers all of its sections.

## [0.3.0] — 2026-11-02

### Added
- `glosator verify`: checks a book's notes against their source without a
  model (listing lines, table rows, watermark and stray mail addresses,
  notes too short for their source).

## [0.2.2] — 2026-11-02

### Changed
- An EPUB's chunks are named after its table of contents.
- A chapter ends at an appendix on the chapter's own level.
- Bibliographies are left out of the plan.

## [0.2.1] — 2026-11-02

### Changed
- The contents and the index are left out of the plan.

## [0.2.0] — 2026-11-02

### Added
- EPUB books, read from their markup. No OCR and no model are involved.

## [0.1.1] — 2026-11-02

### Fixed
- A bookmark's text comes from its pages, not from heading slices.
- A blank page is read as blank, not as its footer.

## [0.1.0] — 2026-11-02

The first release: from a PDF to study notes in an Obsidian vault.

### Added
- The pipeline: extract (docling, on the card when it is free) → chunk (by
  bookmarks or page ranges) → generate (Ollama) → vision (optional) →
  index (chapter maps, glossary, prev/next links).
- An export stage that writes the sections out for a model on another
  machine, with no local LLM.
- A resumable SQLite job queue and a worker in its own process.
- A Gradio UI and a CLI.
- Podman Quadlet units, started and stopped on demand.
- Notes in the book's language, with a glossary in the other language.
- Programming books: listings are rebuilt from the text layer and copied
  into the note verbatim, with smaller chunks and more room for the
  answer.
- An optional Exercises section. An answer is copied from the book, never
  completed or corrected.
- A watermark digest the shop prints on every page is dropped.

[0.7.3]: https://github.com/FPGArtktic/glosator/compare/v0.7.2...v0.7.3
[0.7.2]: https://github.com/FPGArtktic/glosator/compare/v0.7.1...v0.7.2
[0.7.1]: https://github.com/FPGArtktic/glosator/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/FPGArtktic/glosator/compare/v0.6.11...v0.7.0
[0.6.11]: https://github.com/FPGArtktic/glosator/compare/v0.6.10...v0.6.11
[0.6.10]: https://github.com/FPGArtktic/glosator/compare/v0.6.9...v0.6.10
[0.6.9]: https://github.com/FPGArtktic/glosator/compare/v0.6.8...v0.6.9
[0.6.8]: https://github.com/FPGArtktic/glosator/compare/v0.6.7...v0.6.8
[0.6.7]: https://github.com/FPGArtktic/glosator/compare/v0.6.6...v0.6.7
[0.6.6]: https://github.com/FPGArtktic/glosator/compare/v0.6.5...v0.6.6
[0.6.5]: https://github.com/FPGArtktic/glosator/compare/v0.6.4...v0.6.5
[0.6.4]: https://github.com/FPGArtktic/glosator/compare/v0.6.3...v0.6.4
[0.6.3]: https://github.com/FPGArtktic/glosator/compare/v0.6.2...v0.6.3
[0.6.2]: https://github.com/FPGArtktic/glosator/compare/v0.6.1...v0.6.2
[0.6.1]: https://github.com/FPGArtktic/glosator/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/FPGArtktic/glosator/compare/v0.5.3...v0.6.0
[0.5.3]: https://github.com/FPGArtktic/glosator/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/FPGArtktic/glosator/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/FPGArtktic/glosator/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/FPGArtktic/glosator/compare/v0.4.1...v0.5.0
[0.4.1]: https://github.com/FPGArtktic/glosator/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/FPGArtktic/glosator/compare/v0.3.3...v0.4.0
[0.3.3]: https://github.com/FPGArtktic/glosator/compare/v0.3.2...v0.3.3
[0.3.2]: https://github.com/FPGArtktic/glosator/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/FPGArtktic/glosator/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/FPGArtktic/glosator/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/FPGArtktic/glosator/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/FPGArtktic/glosator/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/FPGArtktic/glosator/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/FPGArtktic/glosator/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/FPGArtktic/glosator/releases/tag/v0.1.0
