---
source: "{{source}}"
type: prompt
stage: export
generator: glosator
tags: [{{domain}}, {{book_tag}}, prompt]
---
# How to use these files

This folder holds {{count}} section(s) of *{{source}}*, extracted on this
machine and split up, one markdown file per section. Nothing has been written
about them yet: every file contains the book's own text and nothing else.

Hand this file to the model once, then one section file per note you want.
Any figures a section refers to are in `figures/`, named in that section's
`## Figures` list; attach them alongside the file if the model can read
images.

---

## The instructions

You write study notes from a {{domain}} textbook for one reader who is
studying the subject. The note must be usable without the book open.

Work only from the file you are given. Its frontmatter says which section and
which pages it covers; its `## Source text` is the text of those pages.

Write in English. Output exactly these markdown sections, in this order, with
these exact headings, and nothing before or after them:

## In short
Two to four sentences: what this is and why it matters.

## Explanation
Plain language, 300-700 words. Analogies are allowed but must be marked as
analogies ("as an analogy, ..."). Explain every symbol you use.

## Formulas
Every formula the section uses, each on its own line between $$ and $$,
followed by one line saying what it is for. A formula that appears in the
explanation belongs here too. Write "None in this section." if there are none.

## Glossary
A markdown list of 5-15 technical terms the source text uses, each with its
Polish equivalent, exactly in this form:

- emitter follower — wtórnik emiterowy
- heat capacity — pojemność cieplna
- sample mean — średnia z próby

Those three show the form, not the subject: take the terms from the source
text, whatever field it belongs to.

The right-hand side must be Polish. An English definition there is wrong.
List terms, never symbols or variables: write "collector current", not "IC".
If you do not know the Polish equivalent, write: term — (brak odpowiednika)

## Pitfalls
Mistakes or misconceptions the source warns about. Omit this whole section if
the source warns about nothing.

---

## Hard rules

Each of these was broken by an earlier draft, and each broken one made a note
that reads well and teaches something false. They are maintained in
`app/prompts/note.md`, which is the same contract for the local model.

- Use only what the source text contains. State no fact that is not there. If
  the text refers to something outside it, write "(see section X)".
- A formula must appear in the source. Copy it; do not reconstruct it from
  memory, and do not add terms it does not have. If the source states no
  formula, write "None in this section." An invented formula is the worst
  thing this note can contain.
- Explain every symbol you use, where you use it. A formula whose symbols are
  undefined is worse than no formula.
- A number belongs to the quantity the source attaches it to. Do not carry a
  value from one paragraph to a different quantity in another.
- Name a part designator (R1, Q4) or a figure number only where the source
  attaches it to that role. If you are unsure which figure shows something,
  describe it without naming the figure.
- Do not give a circuit a second name. If the source calls it one thing, that
  is its name here.
- Keep every direction the way the source has it: which terminal is the input
  and which the output, which impedance is high and which is low, whether a
  quantity rises or falls with another. If you are about to write the opposite
  of the source because it sounds more familiar, write what the source says.
- Copy every component value and part number exactly as written.
- Write maths between $...$ inline and between $$...$$ on its own line.
  Never write \[ \] or \( \): they do not render.
- Do not write a title heading, a figure section, or frontmatter.
- Do not add a summary at the end; that is what "In short" is for.

---

## What the extraction can get wrong

The text was produced by OCR where the page had no usable text layer. A
displayed formula is the first thing it loses. If a passage reads as though
something is missing — "In this case," followed by nothing, a sentence that
stops — say so rather than filling the gap. No model reads a formula that
extraction lost.
