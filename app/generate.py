# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""Text pass: one chunk in, one note out.

The model writes prose only. Frontmatter, the figure embeds and the section
order are assembled here, so a note's machine-readable parts never depend on
the model behaving.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from app import config, extract, listing, log, ollama, verify
from app.chunk import Chunk, estimate_tokens
from app.extract import Figure
from app.language import ENGLISH, NOTHING_HERE, Language

PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# Models trained on LaTeX emit \[ ... \] and \( ... \) however loudly the
# prompt asks for dollars, and Obsidian renders neither.
MATH_DISPLAY_RE = re.compile(r"\\\[(.+?)\\\]", re.DOTALL)
MATH_INLINE_RE = re.compile(r"\\\((.+?)\\\)", re.DOTALL)
SECTION_RE = re.compile(r"^##\s+(.*\S)\s*$", re.MULTILINE)
SECTION_NUMBER_RE = re.compile(r"\d+")

# A section title becomes a file name and a wikilink target. A slash in it
# ("SSI / MSI Blocks", "TTL/CMOS") would make a directory; the rest are
# refused by Obsidian on Windows or Android, or end a wikilink early.
NAME_SEPARATOR_RE = re.compile(r"\s*[/\\|]\s*")
NAME_FORBIDDEN_RE = re.compile(r'[:*?"<>#^\[\]]')

# Order of the output contract in CLAUDE.md. "Figures" is inserted by this
# module; the rest comes from the model.
# Written into every note's frontmatter and checked before any overwrite: a
# file without it was not produced here and is never touched.
GENERATOR = "glosator"

# Dropped into every directory glosator creates inside the output folder, so a
# later run can tell its own directories from the user's.
OWNER_STAMP = ".glosator"

SECTION_ORDER = (
    "In short",
    "Explanation",
    "Code",
    "Formulas",
    "Figures",
    "Glossary",
    "Pitfalls",
    "Exercises",
)
REQUIRED_SECTIONS = ("In short", "Explanation")


def load_prompt(name: str) -> str:
    return (config.PROMPT_DIR / name).read_text(encoding="utf-8")


def render(template: str, **fields: object) -> str:
    """Replace ``{{name}}`` placeholders. An unknown placeholder is an error."""

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in fields:
            raise KeyError(f"template placeholder {{{{{key}}}}} has no value")
        return str(fields[key])

    return PLACEHOLDER_RE.sub(substitute, template)


def normalise_math(text: str) -> str:
    """Rewrite LaTeX delimiters to the ones Obsidian renders."""
    text = MATH_DISPLAY_RE.sub(lambda m: f"$${m.group(1).strip()}$$", text)
    return MATH_INLINE_RE.sub(lambda m: f"${m.group(1).strip()}$", text)


def split_sections(markdown: str) -> dict[str, str]:
    """``## Heading`` to body text, for reassembly in the contract's order."""
    matches = list(SECTION_RE.finditer(markdown))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[match.group(1)] = markdown[match.end() : end].strip()
    return sections


def missing_sections(sections: dict[str, str]) -> list[str]:
    return [name for name in REQUIRED_SECTIONS if not sections.get(name, "").strip()]


def strip_wrapping(raw: str) -> str:
    """Drop a fenced block or invented frontmatter around the model's answer."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    return re.sub(r"^#\s+.*\n", "", text.strip(), count=1).strip()


def frontmatter(
    chunk: Chunk,
    book_title: str,
    book_tag: str,
    model: str,
    generated: date,
    domain: str = config.DEFAULT_DOMAIN,
) -> str:
    chapter = chunk.chapter if chunk.chapter is not None else "null"
    tag_chapter = (
        f"chapter-{chunk.chapter:02d}" if chunk.chapter is not None else "chapter-na"
    )
    return "\n".join(
        [
            "---",
            f'source: "{book_title}"',
            f"chapter: {chapter}",
            f'section: "{chunk.section}"',
            f"pages: [{chunk.page_start}, {chunk.page_end}]",
            f"model: {model}",
            f"generated: {generated.isoformat()}",
            f"generator: {GENERATOR}",
            f"tags: [{extract.slugify(domain)}, {book_tag}, {tag_chapter}]",
            "---",
        ]
    )


def figures_block(figures: Sequence[Figure], book_tag: str) -> str:
    """Embeds plus a placeholder line per figure, filled by the vision pass."""
    lines: list[str] = []
    for figure in figures:
        name = Path(figure.path).name
        caption = figure.caption or figure.id
        lines.append(f"![[attachments/{book_tag}/{name}]]")
        lines.append(f"*{caption} — description pending.*")
        lines.append("")
    return "\n".join(lines).strip()


def assemble(
    chunk: Chunk,
    sections: dict[str, str],
    figures_md: str,
    book_title: str,
    book_tag: str,
    model: str,
    generated: date | None = None,
    domain: str = config.DEFAULT_DOMAIN,
    language: Language = ENGLISH,
) -> str:
    """Build the note exactly as the output contract specifies."""
    body = [
        frontmatter(
            chunk, book_title, book_tag, model, generated or date.today(), domain
        ),
        f"# {chunk.section} {chunk.title}".strip(),
    ]
    if chunk.parts:
        body.append(f"*{language.sections}: {' · '.join(chunk.parts)}*")
    merged = dict(sections)
    if figures_md:
        merged["Figures"] = figures_md
    for name in SECTION_ORDER:
        text = merged.get(name, "").strip()
        if text == NOTHING_HERE:
            text = language.nothing_here
        if text:
            body.append(f"## {language.heading(name)}\n\n{text}")
    return "\n\n".join(body) + "\n"


def out_root(out_dir: Path | str | None = None) -> Path:
    return Path(out_dir) if out_dir else config.OUT_DIR


def chapter_folder(chunk: Chunk, chapter_title: str) -> str:
    """Subfolder a chunk's output belongs in.

    Shared by every stage that writes a per-chunk file, so the trees they
    build stay parallel and a chapter is found in the same place in each.
    """
    if chunk.chapter is None:
        return "00-unsorted"
    if chapter_title.strip():
        return f"{chunk.chapter:02d}-{extract.slugify(chapter_title)}"
    # The chapter's own title is unknown; its number alone is honest.
    return f"{chunk.chapter:02d}"


def file_stem(text: str) -> str:
    """``text`` made safe as a file name and a wikilink target."""
    name = NAME_FORBIDDEN_RE.sub("", NAME_SEPARATOR_RE.sub("-", text))
    return " ".join(name.split())


def note_stem(chunk: Chunk) -> str:
    """File stem of a chunk's per-chunk outputs: ``<NN.MM> <Title>``.

    Each number of the section is padded to two digits. A file list sorts
    by name, which put 1.10 before 1.2 and 4.11 before 4.2.
    """
    return file_stem(f"{padded_section(chunk.section)} {chunk.title}")


def padded_section(section: str) -> str:
    """``1.2`` as ``01.02``; ``101.1`` as ``101.01``; ``003`` as it is."""
    return SECTION_NUMBER_RE.sub(lambda match: match.group(0).zfill(2), section)


def note_path(
    chunk: Chunk, chapter_title: str, out_dir: Path | str | None = None
) -> Path:
    """``<out>/<NN-chapter>/<section> <Title>.md``.

    The output folder is an ordinary directory chosen by the user; it does not
    have to be an Obsidian vault (see docs/DECISIONS.md).
    """
    folder = chapter_folder(chunk, chapter_title)
    return out_root(out_dir) / folder / f"{note_stem(chunk)}.md"


def is_ours_text(text: str) -> bool:
    """True when a note's frontmatter carries this generator's marker."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        if line.strip() == f"generator: {GENERATOR}":
            return True
    return False


def is_ours(path: Path) -> bool:
    """True when the file at ``path`` is a note glosator wrote.

    Only the head of the file is read: a note is a few kilobytes, but a file
    that happens to sit at the same path may be anything at all.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            head = "".join(next(handle, "") for _ in range(20))
    except OSError:
        return False
    return is_ours_text(head)


def check_inside(path: Path, out_dir: Path | str | None = None) -> Path:
    """Resolve a path and refuse it if it leaves the output folder."""
    root = out_root(out_dir).resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise PermissionError(f"{resolved} is outside the output folder {root}")
    return resolved


def check_writable(path: Path, out_dir: Path | str | None = None) -> Path:
    """Refuse to write outside the output folder or over someone else's file.

    This is the guard that keeps an existing note collection intact: the only
    files glosator may replace are the ones it wrote itself.
    """
    resolved = check_inside(path, out_dir)
    if resolved.is_dir():
        raise PermissionError(f"{resolved} is a directory, not a note")
    if resolved.exists() and not is_ours(resolved):
        raise PermissionError(
            f"{resolved} was not written by glosator; refusing to overwrite it"
        )
    return resolved


def claim_dir(directory: Path, out_dir: Path | str | None = None) -> Path:
    """Create a directory glosator owns, or confirm that it already owns it.

    Images carry no frontmatter, so ownership of the attachment folder is
    marked by a stamp file instead. A non-empty directory without the stamp is
    the user's and is left untouched.
    """
    checked = check_inside(directory, out_dir)
    stamp = checked / OWNER_STAMP
    if checked.exists() and not stamp.exists() and any(checked.iterdir()):
        raise PermissionError(f"{checked} already holds files glosator did not write")
    checked.mkdir(parents=True, exist_ok=True)
    stamp.touch()
    return checked


def write_atomic(path: Path, text: str) -> None:
    """Write via a temporary file in the same directory, then rename.

    A kill in the middle leaves either the old note or the new one, never half
    of either. No ownership check: callers that write into the output folder
    use ``write_note``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_note(path: Path, text: str, out_dir: Path | str | None = None) -> Path:
    """Atomically write a generated file, after the ownership check."""
    checked = check_writable(path, out_dir)
    write_atomic(checked, text)
    return checked


def copy_attachments(
    figures: Sequence[Figure],
    book_slug: str,
    book_tag: str,
    out_dir: Path | str | None = None,
) -> None:
    """Put the crops where the note's embeds point.

    An image that is already there and was not put there by glosator is left
    alone: the note still points at it, and nothing is lost.
    """
    if not figures:
        return
    destination = claim_dir(out_root(out_dir) / "attachments" / book_tag, out_dir)
    for figure in figures:
        source = config.WORK_DIR / book_slug / figure.path
        if source.exists():
            shutil.copy2(source, destination / Path(figure.path).name)


def figures_for(figures: Sequence[Figure], chunk: Chunk) -> list[Figure]:
    return [
        figure
        for figure in figures
        if chunk.page_start <= figure.page <= chunk.page_end
    ]


def note_prompt(
    chunk: Chunk,
    source_text: str,
    book_title: str,
    domain: str = config.DEFAULT_DOMAIN,
    language: Language = ENGLISH,
    *,
    slides: bool = False,
) -> str:
    """The text pass's prompt for one chunk.

    A programming book asks for its listings where any other book asks for
    its formulas: its code is what a reader needs without the book open, and
    its extraction recognises no formulas (docs/DECISIONS.md, 2026-11-02).
    A slide deck's terse lines are explained rather than abridged.
    """
    technical = "code.md" if listing.wanted(domain) else "formulas.md"
    return render(
        load_prompt("note.md"),
        material=f"{domain} training slides" if slides else f"a {domain} textbook",
        slides=load_prompt("slides.md").strip() if slides else "",
        section=chunk.section,
        title=chunk.title,
        source=book_title,
        domain=domain,
        pages=f"{chunk.page_start}-{chunk.page_end}",
        text=source_text,
        language=language.name,
        glossary=load_prompt(language.glossary_prompt).strip(),
        technical=load_prompt(technical).strip(),
        parts=_parts_instruction(chunk),
    )


def _parts_instruction(chunk: Chunk) -> str:
    if not chunk.parts:
        return ""
    return render(
        load_prompt("parts.md"), parts="\n".join(f"- {name}" for name in chunk.parts)
    ).strip()


def _best_answer(
    chunk: Chunk, prompt: str, source_text: str, model: str, domain: str
) -> dict[str, str]:
    """The model's sections, asked for again when the checks find them short.

    At temperature 0.25 the same model on the same chunk copied all of
    K&R's program output in one run and none of it in the next. The checks
    of glosator verify run on every answer; one that fails them is asked
    for again, up to GENERATE_RETRIES times, and the answer that lost the
    fewest listing lines and table rows is kept.
    """
    best: dict[str, str] = {}
    best_lost = -1
    asked = prompt
    for attempt in range(1 + config.GENERATE_RETRIES):
        sections = _answer(chunk, model, asked, domain)
        note = "\n\n".join(sections.values())
        report = verify.Report(chunk, Path())
        verify.check(report, note, source_text, listings=listing.wanted(domain))
        lost = report.code_lines - report.code_found
        lost += report.table_rows - report.table_found
        if best_lost < 0 or lost < best_lost:
            best, best_lost = sections, lost
        if not report.problems:
            break
        log.event(
            "generate",
            "answer failed the checks",
            section=chunk.section,
            attempt=attempt + 1,
            problems=report.problems,
        )
        asked = prompt + _lost_lines_reminder(note, source_text, domain)
    return best


def _lost_lines_reminder(note: str, source_text: str, domain: str) -> str:
    """The lines the answer left out, appended to the prompt asked again.

    Asked the same prompt again, the model summarised the commands of
    Bootlin's devtool lab a second time; it needs to be told which
    lines it dropped.
    """
    lost = verify.missing_table_rows(note, source_text)
    if listing.wanted(domain):
        lost = verify.missing_listing_lines(note, source_text) + lost
    if not lost:
        return ""
    shown = "\n".join(lost[: config.GENERATE_RETRY_MAX_LINES])
    return "\n\n" + render(load_prompt("retry.md"), lines=shown).strip()


def _answer(chunk: Chunk, model: str, prompt: str, domain: str) -> dict[str, str]:
    raw = _complete(model, prompt, domain)
    sections = split_sections(normalise_math(strip_wrapping(raw)))
    missing = missing_sections(sections)
    if missing:
        raise ValueError(f"{chunk.section}: model omitted {', '.join(missing)}")
    return sections


def _complete(model: str, prompt: str, domain: str) -> str:
    """The model's answer, with room for verbatim listings where they belong.

    A chunk of any book can need that room too: an exercises section of
    Silberschatz copies every task into the note and ran past NUM_PREDICT,
    seven chunks of 128. Such an answer is asked for once more with the
    room a programming book gets, rather than failing the chunk.
    """
    wide = {
        "num_ctx": config.LISTING_NUM_CTX,
        "num_predict": config.LISTING_NUM_PREDICT,
    }
    if listing.wanted(domain):
        return ollama.generate(model, prompt, **wide)
    try:
        return ollama.generate(model, prompt)
    except ollama.AnswerTooLong:
        log.event("generate", "answer too long, asking with a wider window")
        return ollama.generate(model, prompt, **wide)


def run(
    chunk: Chunk,
    *,
    book_slug: str,
    book_title: str,
    book_tag: str,
    chapter_title: str,
    model: str = config.TEXT_MODEL,
    figures: Sequence[Figure] | None = None,
    out_dir: Path | str | None = None,
    domain: str = config.DEFAULT_DOMAIN,
    language: Language = ENGLISH,
    slides: bool = False,
) -> Path:
    """Generate one note. Raises when the input or the output is unusable."""
    source_text = chunk.text_path.read_text(encoding="utf-8")
    tokens = estimate_tokens(source_text)
    if tokens > config.CHUNK_MAX_TOKENS:
        # Ollama would silently drop the overflow and the note would describe
        # half a section without saying so.
        raise ValueError(
            f"{chunk.section}: {tokens} tokens of source exceed the "
            f"{config.CHUNK_MAX_TOKENS} token budget; split the page range"
        )
    prompt = note_prompt(
        chunk, source_text, book_title, domain, language, slides=slides
    )

    sections = _best_answer(chunk, prompt, source_text, model, domain)

    chunk_figures = figures_for(
        figures if figures is not None else extract.load_figures(book_slug), chunk
    )
    copy_attachments(chunk_figures, book_slug, book_tag, out_dir)
    note = assemble(
        chunk,
        sections,
        figures_block(chunk_figures, book_tag),
        book_title,
        book_tag,
        model,
        domain=domain,
        language=language,
    )

    path = write_note(note_path(chunk, chapter_title, out_dir), note, out_dir)
    log.event(
        "generate",
        "note written",
        section=chunk.section,
        path=str(path),
        words=len(note.split()),
        figures=len(chunk_figures),
    )
    return path
