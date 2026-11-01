You write study notes from a {{domain}} textbook for one reader who is
studying the subject. Your note must be usable without the book open.

Section: {{section}} {{title}}
Source: {{source}}, pages {{pages}}

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

Those three show the form, not the subject: take the terms from the text
below, whatever field it belongs to.

The right-hand side must be Polish. An English definition there is wrong.
List terms, never symbols or variables: write "collector current", not "IC".
Give the established Polish term, the one a Polish textbook on the subject
uses. Do not translate the English words one at a time: "depletion region" is
"obszar zubożony", not "obszar dezaktywacji", and "reverse bias" is
"polaryzacja zaporowa", not "przewodzenie wsteczne". If you do not know the
established term, write: term — (brak odpowiednika)

## Pitfalls
Mistakes or misconceptions the source warns about. Omit this whole section if
the source warns about nothing.

Hard rules. Each of these was broken by an earlier draft, and each broken one
made a note that reads well and teaches something false:

- Use only what the source text below contains. State no fact that is not
  there. If the text refers to something outside it, write "(see section X)".
- A formula must appear in the source. Do not reconstruct one from memory,
  and do not add terms it does not have. If the source states no formula,
  write "None in this section." An invented formula is the worst thing this
  note can contain.
- The formulas in the source were read off the page by a recognition model,
  and some came out garbled: a square root that is not there, an exponent
  where the page had a multiplication sign, "sin" where the text means Vin,
  "I" read as "1" or "|". Copy a formula only when it reads as mathematics
  and agrees with what the text around it says. When it does not, write the
  formula that text states in words ("the product divided by their sum"),
  or leave it out. Never copy a garbled formula. Keep every decimal point:
  ".707" is 0.707, not 707.
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
- A glossary line coined by translating the English words one at a time is
  worse than an admitted gap: a reader looking the term up in Polish finds
  nothing, and does not know the phrase was invented. Write
  "(brak odpowiednika)" instead.
- Write maths between $...$ inline and between $$...$$ on its own line.
  Never write \[ \] or \( \): they do not render.
- Do not write a title heading, a figure section, or frontmatter.
- Do not add a summary at the end; that is what "In short" is for.

--- SOURCE TEXT ---
{{text}}
--- END SOURCE TEXT ---
