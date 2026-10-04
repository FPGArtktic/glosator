# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""The text pass: prompt rendering, output contract, atomic writes."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app import config, generate
from app.chunk import Chunk
from app.extract import Figure

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
    prompt = generate.render(
        generate.load_prompt("note.md"),
        section=chunk.section,
        title=chunk.title,
        source="Book",
        domain="electronics",
        pages="71-74",
        text="body",
    )
    assert "{{" not in prompt
    assert "2.3.1" in prompt


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


def test_note_path_follows_the_vault_layout(chunk: Chunk) -> None:
    path = generate.note_path(chunk, "Transistors")
    assert path == config.OUT_DIR / "02-transistors" / "2.3.1 Emitter follower.md"
    unnumbered = Chunk(1, None, "001", "Preface", 1, 2, Path("x.md"))
    assert generate.note_path(unnumbered, "").parent.name == "00-unsorted"


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
    with pytest.raises(PermissionError, match="outside the output folder"):
        generate.check_writable(generate.note_path(sneaky, "Transistors"))


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
    assert path == config.OUT_DIR / "04" / "4.07 Limits of the sampling method.md"


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
