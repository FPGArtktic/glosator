# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The text pass: prompt rendering, output contract, atomic writes."""

from __future__ import annotations

import dataclasses
import re
from datetime import date
from pathlib import Path

import pytest

from app import config, generate
from app.chunk import Chunk
from app.extract import Figure
from app.language import POLISH

MODEL_OUTPUT = """## In short

A follower buffers a signal.

## Explanation

The emitter follows the base, one diode drop below it.

## Formulas

$Z_{in} = \\beta R_E$ — input impedance seen at the base.

## Glossary

- emitter follower — wtórnik emiterowy
- input impedance — impedancja wejściowa

## Pitfalls

Do not forget the base current.
"""


@pytest.fixture
def chunk(tmp_path: Path) -> Chunk:
    text_path = tmp_path / "chunk.md"
    text_path.write_text("## 2.3.1 Emitter follower\n\nsource text\n", encoding="utf-8")
    return Chunk(1, 2, "2.3.1", "Emitter follower", 71, 74, text_path)


def test_render_substitutes_placeholders() -> None:
    assert generate.render("a {{x}} b", x=1) == "a 1 b"


def test_render_rejects_an_unknown_placeholder() -> None:
    with pytest.raises(KeyError):
        generate.render("{{missing}}", other=1)


def test_note_prompt_has_no_leftover_placeholders(chunk: Chunk) -> None:
    prompt = generate.note_prompt(chunk, "body", "Book", "electronics", POLISH)
    assert "{{" not in prompt
    assert "2.3.1" in prompt
    assert "Write the note in Polish" in prompt


def test_a_slide_deck_asks_for_the_slides_to_be_explained(chunk: Chunk) -> None:
    prompt = generate.note_prompt(chunk, "body", "Course", "embedded", slides=True)
    assert "{{" not in prompt
    assert "embedded training slides" in prompt
    assert "never list its" in prompt
    book = generate.note_prompt(chunk, "body", "Book", "embedded")
    assert "embedded textbook" in book
    assert "never list its" not in book


@pytest.mark.parametrize("name", ["note.md", "export.md"])
def test_both_prompts_forbid_a_glossary_calque(name: str) -> None:
    # gemma4:31b's only glossary faults in tachygraf were calques: English
    # words translated one at a time into a phrase no Polish textbook uses.
    prompt = generate.load_prompt(name)
    assert "one at a time" in prompt
    assert "{{glossary}}" in prompt


@pytest.mark.parametrize("name", ["glossary-en.md", "glossary-pl.md"])
def test_both_glossary_directions_show_the_calque(name: str) -> None:
    rules = generate.load_prompt(name)
    assert "one at a time" in rules
    assert "obszar zubożony" in rules


@pytest.mark.parametrize("name", ["note.md", "export.md"])
def test_both_prompts_forbid_copying_a_garbled_formula(name: str) -> None:
    # gemma4:31b copied recognised LaTeX verbatim: a square root in the
    # parallel-resistor law, "sin" for Vin, 707 for .707.
    prompt = generate.load_prompt(name)
    assert "Never copy a garbled formula" in prompt
    assert "0.707" in prompt


def test_assemble_puts_exercises_last(chunk: Chunk) -> None:
    sections = {
        "Exercises": "1. Which command unloads a module?\n   Answer: modprobe -r",
        "Pitfalls": "a",
        "In short": "b",
        "Explanation": "c",
    }
    note = generate.assemble(chunk, sections, "", "Book", "bk1", "gemma4:31b")
    assert note.index("## Pitfalls") < note.index("## Exercises")
    assert note.rstrip().endswith("Answer: modprobe -r")


def test_split_sections_and_required_sections() -> None:
    sections = generate.split_sections(MODEL_OUTPUT)
    assert set(sections) == {
        "In short",
        "Explanation",
        "Formulas",
        "Glossary",
        "Pitfalls",
    }
    assert generate.missing_sections(sections) == []
    assert generate.missing_sections({"In short": "x"}) == ["Explanation"]
    assert generate.missing_sections({"In short": "x", "Explanation": "  "}) == [
        "Explanation"
    ]


def test_strip_wrapping_removes_fences_frontmatter_and_title() -> None:
    raw = (
        "```markdown\n---\nmodel: x\n---\n"
        "# 2.3.1 Emitter follower\n\n## In short\n\nok\n```"
    )
    assert generate.strip_wrapping(raw).startswith("## In short")


def test_frontmatter_matches_the_output_contract(chunk: Chunk) -> None:
    text = generate.frontmatter(
        chunk, "Book, 3rd ed.", "bk1", "gemma3", date(2026, 10, 4), "electronics"
    )
    assert 'source: "Book, 3rd ed."' in text
    assert "chapter: 2" in text
    assert 'section: "2.3.1"' in text
    assert "pages: [71, 74]" in text
    assert "generated: 2026-10-04" in text
    assert "tags: [electronics, bk1, chapter-02]" in text


def test_assemble_puts_figures_between_formulas_and_glossary(chunk: Chunk) -> None:
    figures = generate.figures_block(
        [
            Figure(
                "fig-71-1",
                71,
                (0, 0, 1, 1),
                "Fig 2.10 — follower",
                "2.3.1",
                "figures/fig-71-1.png",
            )
        ],
        "bk1",
    )
    note = generate.assemble(
        chunk, generate.split_sections(MODEL_OUTPUT), figures, "Book", "bk1", "gemma3"
    )
    order = [note.index(f"## {name}") for name in ("Formulas", "Figures", "Glossary")]
    assert order == sorted(order)
    assert "![[attachments/bk1/fig-71-1.png]]" in note
    assert "description pending" in note
    assert note.startswith("---\n")
    assert "# 2.3.1 Emitter follower" in note


def test_assemble_omits_sections_the_model_left_out(chunk: Chunk) -> None:
    note = generate.assemble(
        chunk, {"In short": "a", "Explanation": "b"}, "", "Book", "bk1", "gemma3"
    )
    assert "## Pitfalls" not in note
    assert "## Figures" not in note


def test_assemble_says_there_is_nothing_in_the_notes_language(chunk: Chunk) -> None:
    sections = {"In short": "a", "Formulas": "None in this section."}
    note = generate.assemble(
        chunk, sections, "", "Book", "bk1", "gemma3", language=POLISH
    )
    assert "Brak w tej sekcji." in note
    assert "None in this section." not in note
    english = generate.assemble(chunk, sections, "", "Book", "bk1", "gemma3")
    assert "None in this section." in english


def test_note_path_follows_the_vault_layout(chunk: Chunk) -> None:
    path = generate.note_path(chunk, "Transistors")
    assert path == config.OUT_DIR / "02-transistors" / "02.03.01 Emitter follower.md"
    unnumbered = Chunk(1, None, "001", "Preface", 1, 2, Path("x.md"))
    assert generate.note_path(unnumbered, "").parent.name == "00-unsorted"


def test_chapter_folder_names_the_three_cases(chunk: Chunk) -> None:
    assert generate.chapter_folder(chunk, "Transistors") == "02-transistors"
    assert generate.chapter_folder(chunk, "") == "02"
    unnumbered = Chunk(1, None, "001", "Preface", 1, 2, Path("x.md"))
    assert generate.chapter_folder(unnumbered, "Transistors") == "00-unsorted"


def test_write_atomic_leaves_no_temporary_file(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "note.md"
    generate.write_atomic(target, "first")
    generate.write_atomic(target, "second")
    assert target.read_text(encoding="utf-8") == "second"
    assert list(tmp_path.glob("**/*.tmp")) == []


def test_figures_for_filters_by_page_range(chunk: Chunk) -> None:
    inside = Figure("a", 72, (0, 0, 1, 1), "", "", "figures/a.png")
    outside = Figure("b", 90, (0, 0, 1, 1), "", "", "figures/b.png")
    assert generate.figures_for([inside, outside], chunk) == [inside]


def test_run_writes_the_note_and_copies_attachments(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    crop = config.WORK_DIR / "bk1" / "figures" / "fig-71-1.png"
    crop.parent.mkdir(parents=True, exist_ok=True)
    crop.write_bytes(b"not really a png")
    figure = Figure(
        "fig-71-1", 71, (0, 0, 1, 1), "Fig 2.10", "2.3.1", "figures/fig-71-1.png"
    )

    monkeypatch.setattr(generate.ollama, "generate", lambda *_a, **_k: MODEL_OUTPUT)
    path = generate.run(
        chunk,
        book_slug="bk1",
        book_title="Book",
        book_tag="bk1",
        chapter_title="Transistors",
        model="gemma3",
        figures=[figure],
    )

    assert path.exists()
    assert "wtórnik emiterowy" in path.read_text(encoding="utf-8")
    assert (config.OUT_DIR / "attachments" / "bk1" / "fig-71-1.png").exists()


def test_run_rejects_output_without_the_required_sections(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        generate.ollama, "generate", lambda *_a, **_k: "## Explanation\n\nx"
    )
    with pytest.raises(ValueError, match="In short"):
        generate.run(
            chunk,
            book_slug="bk1",
            book_title="Book",
            book_tag="bk1",
            chapter_title="Transistors",
            figures=[],
        )


def test_frontmatter_carries_the_generator_marker(chunk: Chunk) -> None:
    note = generate.assemble(
        chunk, {"In short": "a", "Explanation": "b"}, "", "Book", "bk1", "gemma3"
    )
    assert f"generator: {generate.GENERATOR}" in note
    assert generate.is_ours_text(note)


@pytest.mark.parametrize(
    "text",
    [
        "# a note someone wrote by hand\n",
        "---\ntags: [mine]\n---\n# hand-written\n",
        "",
        "---\nnot closed\n",
    ],
)
def test_is_ours_rejects_foreign_files(tmp_path: Path, text: str) -> None:
    path = tmp_path / "theirs.md"
    path.write_text(text, encoding="utf-8")
    assert not generate.is_ours(path)


def test_is_ours_on_a_missing_or_unreadable_file(tmp_path: Path) -> None:
    assert not generate.is_ours(tmp_path / "gone.md")
    assert not generate.is_ours(tmp_path)


def test_write_note_refuses_to_overwrite_a_foreign_note(chunk: Chunk) -> None:
    path = generate.note_path(chunk, "Transistors")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("my own note, years of work\n", encoding="utf-8")

    with pytest.raises(PermissionError, match="not written by glosator"):
        generate.write_note(path, "new text")

    assert path.read_text(encoding="utf-8") == "my own note, years of work\n"


def test_write_note_replaces_its_own_output(chunk: Chunk) -> None:
    path = generate.note_path(chunk, "Transistors")
    first = generate.assemble(
        chunk, {"In short": "a", "Explanation": "b"}, "", "Book", "bk1", "gemma3"
    )
    generate.write_note(path, first)
    second = first.replace("## In short\n\na", "## In short\n\nrewritten")
    generate.write_note(path, second)
    assert "rewritten" in path.read_text(encoding="utf-8")


def test_write_note_refuses_a_path_outside_the_output_folder(tmp_path: Path) -> None:
    with pytest.raises(PermissionError, match="outside the output folder"):
        generate.write_note(tmp_path / "elsewhere.md", "text")


def test_note_path_cannot_escape_the_output_folder() -> None:
    sneaky = Chunk(1, 2, "../../../etc", "passwd", 1, 2, Path("x.md"))
    path = generate.note_path(sneaky, "Transistors")
    assert path.parent == config.OUT_DIR / "02-transistors"
    generate.check_writable(path)


def test_note_path_keeps_a_slashed_title_in_one_file() -> None:
    # "6.3 SSI / MSI Blocks" made a directory "6.3 SSI " in the first full run.
    chunk = Chunk(1, 6, "6.3", "SSI / MSI Blocks", 1, 2, Path("x.md"))
    path = generate.note_path(chunk, "")
    assert path == config.OUT_DIR / "06" / "06.03 SSI-MSI Blocks.md"


@pytest.mark.parametrize(
    ("title", "stem"),
    [
        ("Framework for TTL/CMOS Logic", "Framework for TTL-CMOS Logic"),
        ("What is Circuit Analysis?", "What is Circuit Analysis"),
        ("Current & Voltage", "Current & Voltage"),
        ('Tips: "Fast" <loops> | #1 [^a]', "Tips Fast loops-1 a"),
    ],
)
def test_file_stem_drops_what_a_file_name_or_wikilink_cannot_hold(
    title: str, stem: str
) -> None:
    assert generate.file_stem(title) == stem


def test_claim_dir_refuses_a_directory_it_does_not_own() -> None:
    theirs = config.OUT_DIR / "attachments" / "bk1"
    theirs.mkdir(parents=True)
    (theirs / "my-photo.png").write_bytes(b"mine")

    with pytest.raises(PermissionError, match="did not write"):
        generate.claim_dir(theirs)


def test_claim_dir_is_idempotent_on_its_own_directory() -> None:
    target = config.OUT_DIR / "attachments" / "bk1"
    assert generate.claim_dir(target) == target.resolve()
    assert generate.claim_dir(target) == target.resolve()
    assert (target / generate.OWNER_STAMP).exists()


def test_run_writes_into_the_given_output_folder(
    chunk: Chunk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    monkeypatch.setattr(generate.ollama, "generate", lambda *_a, **_k: MODEL_OUTPUT)

    path = generate.run(
        chunk,
        book_slug="bk1",
        book_title="Book",
        book_tag="bk1",
        chapter_title="Transistors",
        figures=[],
        out_dir=elsewhere,
    )

    assert path.is_relative_to(elsewhere)
    assert not any(config.OUT_DIR.rglob("*.md"))


def test_run_refuses_a_chunk_that_cannot_fit_the_context_window(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    oversized = "word " * (config.CHUNK_MAX_TOKENS * config.CHARS_PER_TOKEN)
    chunk.text_path.write_text(oversized, encoding="utf-8")
    monkeypatch.setattr(
        generate.ollama,
        "generate",
        lambda *_a, **_k: pytest.fail("the model must not be called"),
    )

    with pytest.raises(ValueError, match="token budget"):
        generate.run(
            chunk,
            book_slug="bk1",
            book_title="Book",
            book_tag="bk1",
            chapter_title="Transistors",
            figures=[],
        )


def test_normalise_math_rewrites_latex_delimiters() -> None:
    raw = "charge \\(Q = C V\\) and\n\\[\n  Q = C_{GC} \\cdot \\Delta V_G\n\\]\n"
    fixed = generate.normalise_math(raw)
    assert "$Q = C V$" in fixed
    assert "$$Q = C_{GC} \\cdot \\Delta V_G$$" in fixed
    assert "\\[" not in fixed and "\\(" not in fixed


def test_normalise_math_leaves_dollars_alone() -> None:
    text = "$R_{ON}$ and $$Z = \\beta R_E$$"
    assert generate.normalise_math(text) == text


def test_run_normalises_math_from_the_model(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = MODEL_OUTPUT.replace(
        "The emitter follows the base, one diode drop below it.",
        "The charge is \\(Q = C_{GC} \\Delta V_G\\).",
    )
    monkeypatch.setattr(generate.ollama, "generate", lambda *_a, **_k: output)
    path = generate.run(
        chunk,
        book_slug="bk1",
        book_title="Book",
        book_tag="bk1",
        chapter_title="Transistors",
        figures=[],
    )
    assert "$Q = C_{GC} \\Delta V_G$" in path.read_text(encoding="utf-8")


def test_note_path_uses_the_chapter_number_when_the_title_is_unknown() -> None:
    chunk = Chunk(1, 4, "4.07", "Limits of the sampling method", 99, 102, Path("x.md"))
    path = generate.note_path(chunk, "")
    assert path == config.OUT_DIR / "04" / "04.07 Limits of the sampling method.md"


def test_the_domain_is_the_first_tag_of_every_note(chunk: Chunk) -> None:
    # Books come from different fields; nothing may assume electronics.
    text = generate.frontmatter(
        chunk,
        "Example Textbook",
        "stat1",
        "gemma3",
        date(2026, 10, 4),
        "Mathematical Statistics",
    )
    assert "tags: [mathematical-statistics, stat1, chapter-02]" in text


def test_a_book_without_a_domain_falls_back_to_the_configured_one(
    chunk: Chunk,
) -> None:
    text = generate.frontmatter(chunk, "Book", "b", "gemma3", date(2026, 10, 4))
    assert f"tags: [{config.DEFAULT_DOMAIN}, b, chapter-02]" in text


def test_run_passes_the_domain_to_the_prompt(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def fake_generate(_model, prompt, **_kwargs):
        seen.append(prompt)
        return MODEL_OUTPUT

    monkeypatch.setattr(generate.ollama, "generate", fake_generate)
    generate.run(
        chunk,
        book_slug="org1",
        book_title="Book",
        book_tag="org1",
        chapter_title="Alkanes",
        figures=[],
        domain="organic chemistry",
    )
    assert "organic chemistry textbook" in seen[0]
    assert "{{" not in seen[0]


def test_assemble_writes_polish_headings_for_a_polish_note(chunk: Chunk) -> None:
    sections = {"In short": "a", "Explanation": "b", "Glossary": "- c — d"}
    note = generate.assemble(
        chunk, sections, "", "Book", "bk1", "gemma4:31b", language=POLISH
    )
    assert "## W skrócie" in note
    assert "## Wyjaśnienie" in note
    assert "## Słowniczek" in note
    assert "## In short" not in note


def test_run_asks_for_the_book_language(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts: list[str] = []

    def fake_generate(_model: str, prompt: str, images=None) -> str:
        prompts.append(prompt)
        return MODEL_OUTPUT

    monkeypatch.setattr(generate.ollama, "generate", fake_generate)
    path = generate.run(
        chunk,
        book_slug="bk1",
        book_title="Sztuka elektroniki",
        book_tag="bk1",
        chapter_title="Tranzystory",
        figures=[],
        language=POLISH,
    )
    assert "Write the note in Polish" in prompts[0]
    assert "wtórnik emiterowy — emitter follower" in prompts[0]
    assert "## W skrócie" in path.read_text(encoding="utf-8")


def test_a_programming_book_is_asked_for_code_instead_of_formulas(
    chunk: Chunk,
) -> None:
    prompt = generate.note_prompt(chunk, "body", "Book", "programming")
    assert "## Code" in prompt
    assert "character for\ncharacter" in prompt
    assert "## Formulas" not in prompt


def test_any_other_book_is_still_asked_for_formulas(chunk: Chunk) -> None:
    prompt = generate.note_prompt(chunk, "body", "Book", "electronics")
    assert "## Formulas" in prompt
    assert "## Code" not in prompt


def test_assemble_puts_code_right_after_the_explanation(chunk: Chunk) -> None:
    sections = {
        "Glossary": "- pętla — loop",
        "Code": "```c\nint main(void)\n{\n    return 0;\n}\n```\nThe smallest program.",
        "Explanation": "text",
        "In short": "short",
    }
    note = generate.assemble(chunk, sections, "", "Book", "bk1", "m", language=POLISH)
    headings = re.findall(r"^## (.+)$", note, re.MULTILINE)
    assert headings == ["W skrócie", "Wyjaśnienie", "Kod", "Słowniczek"]
    assert "{\n    return 0;\n}" in note


def test_an_exercise_without_an_answer_is_kept_as_a_bare_task() -> None:
    # gemma4:31b filled every unanswered exercise of a C textbook with
    # "Answer: (no answer provided in source)" instead of leaving it out.
    prompt = generate.load_prompt("note.md")
    assert "with no Answer line" in prompt
    assert "never say that the answer is missing" in prompt


def test_a_programming_book_gets_room_for_its_listings(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def fake_generate(_model, _prompt, **options):
        calls.append(options)
        return MODEL_OUTPUT

    monkeypatch.setattr(generate.ollama, "generate", fake_generate)
    for domain in ("programming", "electronics"):
        generate.run(
            chunk,
            book_slug="bk1",
            book_title="Book",
            book_tag="bk1",
            chapter_title="Transistors",
            figures=[],
            domain=domain,
        )
    assert calls[0] == {
        "num_ctx": config.LISTING_NUM_CTX,
        "num_predict": config.LISTING_NUM_PREDICT,
    }
    assert calls[1] == {}


def test_an_answer_cut_off_is_asked_for_with_more_room(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def fake_generate(_model, _prompt, **options):
        calls.append(options)
        if not options:
            raise generate.ollama.AnswerTooLong("stopped at its length limit")
        return MODEL_OUTPUT

    monkeypatch.setattr(generate.ollama, "generate", fake_generate)
    generate.run(
        chunk,
        book_slug="bk1",
        book_title="Book",
        book_tag="bk1",
        chapter_title="Transistors",
        figures=[],
        domain="electronics",
    )
    assert calls == [
        {},
        {"num_ctx": config.LISTING_NUM_CTX, "num_predict": config.LISTING_NUM_PREDICT},
    ]


def test_a_merged_chunk_asks_for_every_section(chunk: Chunk) -> None:
    merged = dataclasses.replace(chunk, parts=("2.3.1 Emitter follower", "2.3.2 Bias"))
    prompt = generate.note_prompt(merged, "body", "Book", "electronics")
    assert "- 2.3.1 Emitter follower\n- 2.3.2 Bias" in prompt
    assert "several sections" in prompt
    assert "several sections" not in generate.note_prompt(chunk, "body", "Book")


def test_a_merged_note_lists_its_sections_under_the_title(chunk: Chunk) -> None:
    merged = dataclasses.replace(chunk, parts=("2.3.1 Emitter follower", "2.3.2 Bias"))
    sections = {"In short": "a", "Explanation": "b", "Glossary": "- c — d"}
    note = generate.assemble(
        merged, sections, "", "Book", "bk1", "gemma4:31b", language=POLISH
    )
    assert (
        "# 2.3.1 Emitter follower\n\n*Sekcje: 2.3.1 Emitter follower · 2.3.2 Bias*"
        in note
    )


def test_run_asks_again_when_an_answer_drops_a_listing(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk.text_path.write_text(
        "## 2.3.1 Counting\n\n```\nint n = 0;\nn++;\n```\n", encoding="utf-8"
    )
    code = "\n## Code\n\n```c\nint n = 0;\nn++;\n```\nCounts.\n"
    answers = [MODEL_OUTPUT, MODEL_OUTPUT + code]

    def fake_generate(_model, _prompt, **_kwargs):
        return answers.pop(0)

    monkeypatch.setattr(generate.ollama, "generate", fake_generate)
    path = generate.run(
        chunk,
        book_slug="p1",
        book_title="Book",
        book_tag="p1",
        chapter_title="Basics",
        figures=[],
        domain="programming",
    )
    assert answers == []
    assert "int n = 0;" in path.read_text(encoding="utf-8")


def test_the_second_ask_names_the_lines_the_first_answer_lost(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk.text_path.write_text(
        "```\nint a = 1;\nint b = 2;\nint c = 3;\n```\n", encoding="utf-8"
    )
    some = "\n## Code\n\n```c\nint a = 1;\n```\nOne line.\n"
    prompts = []

    def fake_generate(_model, prompt, **_kwargs):
        prompts.append(prompt)
        return MODEL_OUTPUT + some

    monkeypatch.setattr(generate.ollama, "generate", fake_generate)
    generate.run(
        chunk,
        book_slug="p1",
        book_title="Book",
        book_tag="p1",
        chapter_title="Basics",
        figures=[],
        domain="programming",
    )
    assert "PREVIOUS ANSWER" not in prompts[0]
    assert prompts[1].startswith(prompts[0])
    reminder = prompts[1][len(prompts[0]) :]
    assert "int b = 2;\nint c = 3;\n" in reminder
    assert "int a = 1;" not in reminder


def test_run_keeps_the_better_answer_when_both_fail(
    chunk: Chunk, monkeypatch: pytest.MonkeyPatch
) -> None:
    chunk.text_path.write_text(
        "```\nint a = 1;\nint b = 2;\nint c = 3;\n```\n", encoding="utf-8"
    )
    some = "\n## Code\n\n```c\nint a = 1;\n```\nOne line.\n"
    answers = [MODEL_OUTPUT + some, MODEL_OUTPUT]
    monkeypatch.setattr(
        generate.ollama, "generate", lambda *_args, **_kwargs: answers.pop(0)
    )
    path = generate.run(
        chunk,
        book_slug="p1",
        book_title="Book",
        book_tag="p1",
        chapter_title="Basics",
        figures=[],
        domain="programming",
    )
    assert "int a = 1;" in path.read_text(encoding="utf-8")


def test_section_numbers_are_padded_so_names_sort() -> None:
    assert generate.padded_section("1.2") == "01.02"
    assert generate.padded_section("1.10") == "01.10"
    assert generate.padded_section("101.1") == "101.01"
    assert generate.padded_section("003") == "003"
    assert generate.padded_section("4.11-2") == "04.11-02"
    assert sorted(["01.10", "01.02", "01"]) == ["01", "01.02", "01.10"]
