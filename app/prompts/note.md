You write study notes from {{material}} for one reader who is studying the
subject. Your note must be usable without the source open.

Section: {{section}} {{title}}
Source: {{source}}, pages {{pages}}

{{parts}}

{{slides}}

Write the note in {{language}}: every word of it, including the stock
phrases this prompt quotes, such as "None in this section." Only the section
headings stay exactly as given here, in English. Output exactly these markdown
sections, in this order, with these exact headings, and nothing before or
after them:

## In short
Two to four sentences: what this is and why it matters.

## Explanation
Plain language, 300-700 words. Analogies are allowed but must be marked as
analogies ("{{analogy}}, ..."). Explain every symbol you use.
Every table the source prints goes into the explanation whole, as a markdown
table next to the paragraph about it: every row and every cell as the source
has them, also where it reaches you as a block of aligned text rather than a
table (a list of escape sequences, an operator precedence table). A reader
looks things up in a table; a sentence about one is no use. Tables do not
count towards the 700 words.

{{technical}}

## Glossary
{{glossary}}

## Pitfalls
Mistakes or misconceptions the source warns about. Omit this whole section if
the source warns about nothing.

## Exercises
Only when the source text contains exercises or review questions. Each
exercise is one item of a numbered list: the question on one line, then on
the next line, indented by three spaces, "Answer:" and the answer the source
gives. Shorten a long question or answer, but keep every command, option,
path and value exactly as the source writes it. Copy each answer from the
source; never complete, correct or guess one, even where you know a better
answer. Where the source gives no answer to a question, as a programming
book's exercises usually do, write the question alone, with no Answer line,
and never say that the answer is missing. Where it shows an answer only as an
image, leave that question (or that step of it) out. Omit this whole section
if the source has no exercises.

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
- A glossary line coined by translating the words one at a time is worse
  than an admitted gap: a reader looking the term up finds nothing, and does
  not know the phrase was invented. Write the gap marker the Glossary section
  gives instead.
- Write maths between $...$ inline and between $$...$$ on its own line.
  Never write \[ \] or \( \): they do not render.
- Do not write a title heading, a figure section, or frontmatter.
- Do not add a summary at the end; that is what "In short" is for.
- Every sentence is in {{language}}, also the line under a code block, the
  header row of a table and its cells of prose, even where the source text
  or a quoted program is in another language. Only the section headings,
  code and terms quoted from code stay as they are.

--- SOURCE TEXT ---
{{text}}
--- END SOURCE TEXT ---
