---
name: piaget-article-auditor
description: >
  Audit a single explanatory article — a popular-science or technical blog post, a teaching
  handout, or a stand-alone tutorial — for how well it builds understanding in its intended
  reader, using Piaget's assimilation/accommodation framework. Produces a readable Markdown
  review report: inferred reader profile, hidden assumptions, per-concept scaffolding checks,
  analogy and example checks, code/figure roles, and prioritized fixes with exact locations.
  Use when the user asks to "audit this article", "review this blog post / tutorial / handout
  for readers", "will beginners understand this", "find hidden assumptions", "check the
  explanation flow", "Piaget review", or the same in any language (e.g. 「审查这篇文章」
  「这篇教程读者看得懂吗」「找出隐性假设」「做 Piaget 审查」). Not for textbook chapters or
  other book-length teaching material (use a textbook auditor for those), and not for
  fact-checking, copy-editing, or opinion pieces without concepts to teach.
---

# Piaget Article Auditor

## Purpose

An explanatory article succeeds when its intended reader ends up with a *correct, usable mental
model* of the ideas it teaches. This skill reviews one article against that goal:

1. **Hidden reader assumptions** — what the author takes for granted that the reader may lack,
   including author-workspace shorthand leaked into the body.
2. **Explicit prerequisites** — whether each idea is introduced after what it depends on.
3. **Assimilation or accommodation** — whether each new idea extends what the reader already
   believes (assimilation) or contradicts it (accommodation), and whether the article handles
   that path well.
4. **Analogies, examples, code and figures** — whether they carry the key structure, and where
   they break.
5. **Promise and flow** — whether the first screen, the overall promise, and each titled unit
   deliver what they set up, and whether the sections connect.

The output is a review the author can act on: every finding points to an exact location, says
why it matters for the target reader, and suggests a concrete fix. It is not a rewrite, a
fact-check, or a copy-edit.

## Inputs

| Input | Required | Handling |
|---|---|---|
| The article | Yes | Markdown, plain text, HTML, `.ipynb`, or pasted text. Read all of it before judging. For `.ipynb`, markdown cells are the text; code cells are analysed in Step 4. |
| Intended reader | No | If the user states it, use it. Otherwise, if the article states it (a subtitle such as "for beginners", a line such as "for first-year students"), use that and quote it. Otherwise infer it in Step 1 and state the inference at the top of the report. Unless the user or the article explicitly states otherwise, assume the reader does not know the author's colleagues, roles, internal codes, task IDs, file names, or workflow. |
| Publication context | No | Where it will appear (personal blog, course site, docs), series it belongs to, earlier posts it relies on. |
| Report language | No | Default: the language the user writes in; if unclear, the article's language. |

Do not ask questions before starting unless the article cannot be identified. If the intended
reader is genuinely ambiguous between very different groups (for example "complete beginners"
vs "working engineers"), pick the one the article's own wording supports, say so, and note in
the report how the main findings would change for the other group.

## Workflow

### Step 0: Map the article

Scan once and list, without judging:

- Title, stated goal or promise (title, subtitle, opening paragraph), and article type
  (popular science, technical blog, teaching handout, tutorial, or slide deck/draft — see Edge
  cases).
- Sections (or slides/pages) in order, with their headings.
- **Non-concept blocks**: title and subtitle, opening paragraph (or cover and summary/executive
  slide or page), status, version, or workflow notes, and conclusion section. These blocks are
  not concept nodes (do not run Step 3 on them or list them in the concept index), but they
  **must** be checked in Step 2 (especially category G) and in Step 5's **first-screen** and
  **unit-promise** checks.
- The 1–3 main ideas each teaching section introduces. These are the **concept nodes** used in
  Step 3. Background stories, history, and opinions inside a section are not concept nodes;
  attach them to the nearest concept.
- How each idea is presented: definition, claim, example, analogy, derivation, code, figure,
  step-by-step procedure.
- Any code blocks, commands, figures, or interactive elements.

### Step 1: Profile the intended reader

Infer the reader the author is writing for from evidence in the text. Collect clues on seven
dimensions and write one or two descriptive sentences for each:

| Dimension | Evidence to look for |
|---|---|
| R1 Background knowledge | Domain terms used without definition; ideas referenced by name only |
| R2 Abstraction level | Concrete-only, relational (how things connect), or formal (general statements, proofs) |
| R3 Notation and jargon | Symbols, acronyms, product names, and conventions introduced without explanation |
| R4 Procedural skills | Steps skipped in calculations, commands, or setup; actions described as "just" or "simply" |
| R5 Intuitions and visual sense | "Imagine…", "clearly", "as you can see" without a picture or explanation |
| R6 Code and tools | Languages, libraries, versions, environments, and terminal use assumed |
| R7 Reading behaviour | Whether the first screen gives the core answer or takeaway in reader terms (rather than author process, status, or review history), and whether the article supports skimming and arriving mid-page from search, signposts its structure, and tells the reader what to remember for later |

Then compare this **assumed reader** with the **target reader** (stated by the user, or the one
the article claims to serve, e.g. "a beginner's guide"). Unless the user or the article
explicitly states otherwise, the target reader does not know the author's colleagues, roles,
internal codes, task IDs, file names, or workflow — even when the target reader is a domain
expert or project lead; state explicitly in the report's Reader profile whether this baseline
is violated. The gaps between the assumed reader and the target reader drive Step 2. If the two
match closely, say so; a good article for experts is not a bad article.

### Step 2: Find hidden assumptions

A hidden assumption is something the reader must already know or be able to do, which the
article neither states nor teaches — or, in category G, author-workspace information leaked
into the body that the reader should not have to learn even when the text defines it. Search
with these categories, and prefer reporting a borderline case over missing one:

| Category | Typical signals | Question to ask |
|---|---|---|
| A Maturity | "obviously", "it is easy to see", "trivially", "left as an exercise" | Easy for whom? Compare with R2 for the target reader. |
| B Notation and terms | A symbol, acronym, or term used before (or without) its explanation; a word used in a technical sense that differs from everyday use | Does the target reader already own this vocabulary? (R3) |
| C Procedure | Skipped derivation steps, missing setup commands, "install X" with no version, hidden state between steps | Can the target reader actually perform this step? (R4, R6) |
| D Intuition | "Picture this", "intuitively", geometric or physical claims with no figure | Is this intuitive for *this* reader? (R5) |
| E Reading strategy | Abrupt change of pace or register; forward references with no marker; important caveats buried | Does the reader know what kind of passage this is and what to keep? (R7) |
| F Context | Reliance on an earlier post, a course, a company setting, or a particular platform, without a link or summary | Would a reader arriving from search have that context? |
| G Author workspace leak | In the body (excluding appendices, footnotes, and source/provenance notes), author-internal information the reader does not need: team member or role codes, task/ticket IDs, file names and paths, internal phase codes, version and review history, or internal evidence-grade labels. Report even when defined in the text | Must the reader first learn the author team's internal shorthand to understand this sentence? If it were removed or rewritten in reader terms, what would the reader's understanding lose? (R1, R3, R7) |

Record each assumption with: location, category, the dimension it comes from (R1–R7), what the
reader needs (or, for G, what internal shorthand is leaked), and severity (`high`, `medium`,
`low`; see Severity).

### Step 3: Check each concept node

Run these checks for every concept node from Step 0, in order.

**Check 0 — Path: assimilation or accommodation (always first).** Ask: what does the target
reader most likely already believe about this, and can the new idea fit into that belief?

- **Assimilation**: the idea is a natural extension or generalisation of something familiar.
  The usual good pattern is concrete case → general statement. No conflict is needed.
- **Accommodation**: the idea contradicts a common intuition or everyday meaning, so the reader
  must restructure what they believe. The usual good pattern is: old belief is named → it
  visibly fails → the new idea resolves the failure → the new idea is used once more.

Common accommodation points across fields: a familiar operation that stops obeying its old
rules; a word whose technical meaning differs from its everyday one; a result that runs
against intuition; a move from concrete to abstract where the familiar picture disappears.

**Check 1 — Prerequisites in place.** List the ideas this concept depends on and whether each
was established earlier in the article or can safely be assumed for the target reader. Rate a
gap `fatal` (the idea cannot be understood without it), `recoverable` (the reader can push
through with confusion), or `minor`.

**Assimilation path:**

- **Check 2a — Representative example.** Does the concrete example already contain the
  feature that the generalisation keeps? Too special and the reader cannot see the pattern;
  too complex and the example itself becomes the obstacle.
- **Check 3a — Explicit bridge.** Does the text say, in words, that the general statement is
  the thing the reader just saw, generalised? Or are example and statement left side by side
  for the reader to connect?

**Accommodation path:**

- **Check 2b — Conflict designed.** Is the old belief named and made to fail, by naming the
  wrong intuition, a counterexample, a puzzle, or a boundary case where the old method breaks?
  Without this, readers memorise the new rule and keep using the old one.
- **Check 3b — Conflict timing.** `before` the new idea is stated (best), `after` (weaker), or
  `absent` (fail).
- **Check 4b — Room to adjust.** After the conflict, does the article explain why the old belief
  was insufficient, then state the new idea, then use it once? Or does it jump straight to the
  rule?

**Analogy check (whenever a concept is taught through an analogy or metaphor).** Analogies are
the main assimilation device in explanatory writing, and the main source of wrong mental models.

- Does the analogy map the structure that matters for this concept (not just surface features)?
- Where does it break? Is the breaking point stated before the reader relies on it?
- Does a later section silently depend on a part of the analogy that does not hold?

Give each concept node a verdict: `pass`, `warn` (works, but a specific check is weak), or
`fail` (the target reader is likely to get lost or leave with a wrong model).

### Step 4: Code, commands, figures, and media

For each code block, command sequence, figure, or embedded media, decide its role and ask the
matching question:

| Role | Meaning | Question |
|---|---|---|
| `bridging` | Turns an idea into executable or visible steps | Is the translation faithful? Does it add load the reader cannot carry? |
| `visualisation` | Shows a shape, trend, or structure | Does the text say what to look at and what it shows? |
| `verification` | Confirms a claim numerically or by running it | Does it build understanding, or only confidence? |
| `exploratory` | Invites the reader to change something and observe | Is there a guiding question about what to notice? |
| `procedural` | A step the reader must reproduce (tutorials) | Can it be reproduced as written: versions, setup, inputs, expected output? |
| `decorative` | Present but adds nothing to understanding | Remove, or redesign so it carries a point? |
| `missing` | A figure, demo, or code block the title or text promises or refers to ("see the diagram", a heading such as "Seeing it in a picture") but does not include | What does the reader have to build in their head instead, and is that realistic for them? |

Reproducibility problems in `procedural` items are also hidden assumptions of category C.

### Step 5: Promise and flow

- **First screen**: do the title and opening paragraph (or the cover and first slide/page) give,
  in the target reader's own words, the core answer or what the reader will get from reading?
  If the first screen mainly talks about the author's process, project status, or review
  history instead, rate the problem at least `medium`.
- **Promise**: does the article as a whole deliver what the title and opening promise, for the
  target reader? Name any promised item that is missing or only gestured at.
- **Unit promises**: does every titled unit (section, slide/page, or titled card/box) answer the
  question or deliver the point its own heading sets up — especially when the heading is a
  question? When a unit does not answer its own heading, rate the severity by what the target
  reader loses at that point.
- **Links between sections**: does each section's result get picked up where it is used? Are
  forward references marked ("we come back to this in…")? For slide decks or page-by-page
  drafts only, also check each adjacent pair of slides for a one-sentence transition (see Edge
  cases; do not apply to regular articles).
- **Active moments**: accommodation needs the reader to *do* something. For each concept on the
  accommodation path, check whether some prediction, question, try-it step, or exercise makes
  the reader confront *that concept's* misconception. Distinguish two problems: no activity at
  all, and an activity that exists but only repeats the easy case, so the misconception never
  surfaces (one early prediction does not cover every later accommodation point). Say where one
  activity would help most.
- **Ending**: does the close consolidate the main model (summary, what to remember, what to read
  next), or just stop?

### Step 6: Write the report

Use the structure in [references/report-template.md](references/report-template.md). Rules:

1. **Locate everything.** Each finding names the section heading (or non-concept block / slide
   id, such as "Opening", "Cover", or "Navigation bar") and quotes a short phrase
   (at most one sentence) from the article so the author can find it. For a code block or
   figure, quote its first line or caption, or name it by position ("the second code block").
   When you cite the article, quotation marks mean its exact words (an ellipsis for a cut is
   fine; line breaks and Markdown formatting such as bold or backticks may be dropped, but no
   word may change); a paraphrase of the article, even a single word the article does not
   use, goes without quotation marks, in the findings and in "What works" alike. Code, commands, and sample sentences offered in a fix follow their own
   syntax and are not citations. If a finding involves several
   places (a title promise and a closing line, say), number and order it by the earliest place
   and quote the others as further evidence in the same entry.
2. **One severity per finding.** Every finding — concept (`C`), assumption (`A`), code or media
   (`M`), promise and flow (`P`) — carries one severity from the Severity table. For concept
   nodes the result and the severity go together: `fail` is `high` or `medium`; `warn` is
   `medium` or `low`.
3. **Severity gating.** Concept nodes that pass appear only as one line in the concept index.
   Only `high` and `medium` findings get a full entry; `low` findings go into a short list at
   the end, one line each with a location.
4. **One problem, one entry.** When the same gap shows up in more than one check — across a
   concept check, an assumption (including category G), a code/media item, or a
   promise-and-flow check (such as first screen or unit promise) — write one full entry where
   the reader is hurt most and name its id in the other place ("see A01" or "see P01") instead
   of opening a second entry. Separate entries are right only when the problems need different
   fixes. Likewise, when the same kind of category G leak (such as a recurring internal label
   or role code) repeats across sections, group it into one `A` entry ordered by the earliest
   place (per rule 1) rather than opening an entry per occurrence.
5. **Write the whole report in the report language.** Translate every heading, every bold
   field label, and all prose (in a Chinese report, for example, Verdict → 结论, Where → 位置,
   Fix → 改法, What works → 做得好的地方). Keep in English only the fixed vocabulary that makes
   reports comparable across languages: ids (`C01`, `R1`–`R7`, categories `A`–`G`), results
   (`pass`, `warn`, `fail`, `not audited`), severities (`high`, `medium`, `low`), gaps (`none`,
   `small`, `medium`, `large`), paths (`assimilation`, `accommodation`), and roles (`bridging`,
   `visualisation`, `verification`, `exploratory`, `procedural`, `decorative`, `missing`).
   Citations stay in the article's own words, and file names, code, and commands stay as they
   are.
6. **Say why for this reader.** Each full finding states what the target reader will likely
   think or do at that point, not just that a rule was broken.
7. **Suggest a concrete fix**: what to add, move, or reword, and where. Offer a sample sentence
   only when it makes the fix clearer; do not rewrite the article unless asked.
8. **Top three.** The summary lists at most three findings, highest severity first.
9. **One-line verdict and worst issue.** Exactly one sentence each. The verdict includes the
   concept count by result (for example "6 concepts: 4 pass, 1 warn, 1 fail") and an overall
   judgement. The worst issue names a single finding by its id. If there is no `high` or
   `medium` finding, write "none" and say in the same sentence why the article works for its
   reader — limited to the audited sections if some concepts are `not audited`; do not promote
   a `low` item or invent one.
10. **Note what works.** One to three short points on what the article does well, so the author
   knows what to keep.
11. **Do not invent problems.** If the article suits its target reader, say so. Do not count an
   expert article's expertise against it when the target reader is an expert (internal
   author-workspace shorthand in category G is not domain expertise — report it unless the
   user or the article explicitly states that the reader shares that workspace).
12. **Stay in scope.** Flag factual errors only when they would plant a wrong mental model, and
   label them as outside the main audit. Do not copy-edit. **Exception (category G):** putting
   author-internal information into the body is not a copy-editing issue or harmless
   transparency, but a reader-model problem that must be reported (category G). Methodological
   or provenance transparency the reader needs should be rewritten in plain reader language
   (for example, "preliminary description, not formally tested" instead of an internal label)
   or moved to footnotes or an appendix.

Save the report as a Markdown file when the environment allows (default name
`<article-name>.piaget-review.md` next to the article, or where the user asks), and give a
summary of at most three sentences in the conversation. If files cannot be written, output the
report in the conversation.

## Severity

| Level | Meaning for the target reader |
|---|---|
| `high` | Likely to get lost here, give up, or leave with a wrong model that later parts of the article (examples, exercises, the next section) depend on |
| `medium` | Likely to be confused, but the article itself contains what the reader needs to recover on rereading |
| `low` | Polish: wording, ordering, or a missing signpost that costs little |

Judge severity by what the reader ends up believing and doing, not by whether the article's
statements are correct:

- A concept whose common misconception is never challenged, so the reader keeps the old model
  while later parts of the article rely on the new one, is `high` even when the definition or
  formula given is correct.
- When the reader must know or decode an internal author code, role letter, or internal
  evidence-grade label to understand a conclusion (even if defined earlier in the text), rate
  it `high`. When the opening or conclusion section/slide spends its main space on the author's
  workflow, status, or review history rather than the answer, rate it `medium` (or `high` if the
  promised answer is not delivered elsewhere in the article).
- "Recoverable on rereading" counts only when the article contains what the reader needs. If
  they would have to find it elsewhere (another course, a search), it is not recoverable here.
- Do not raise or lower a severity merely because of a finding's prefix, category letter, or
  media role (a `missing` figure is judged by what the reader loses, like any other finding).

## Edge cases

| Situation | Handling |
|---|---|
| Very long article (more than about 8,000 words) | Map all of it in Step 0, then audit in full the sections that carry the main promise. List concepts in the other sections in the concept index with the result `not audited`; leave them out of the verdict's counts and say in the verdict how many were not audited. |
| One section mixes assimilation and accommodation | Split it into two concept nodes. |
| Part of a series | A reference to an earlier post is a category F assumption only when understanding depends on it and the article gives neither an adequate summary nor a link. If the article tells readers to read the earlier post first, judge against a reader who has, and note the dependency once. If the user provides the earlier posts or says readers will have read them, treat their content as known. |
| Translated article, or terms in two languages | Check that each technical term is used consistently and that terms which differ between language variants are explained. |
| Tutorial that is mostly commands | Concepts may be few; focus Step 4 on `procedural` items and Step 2 category C, and still check the one or two ideas the tutorial claims to teach. |
| Slide deck or page-by-page draft (including Markdown or Mermaid slide outlines) | Audit in the slide order the reader sees and by the on-screen text of each slide (when a slide is drafted as a Mermaid layout or table, audit its on-screen labels as slide body rather than treating the whole slide layout as a single Step 4 figure; figures inside a slide are still checked in Step 4). Treat the cover, navigation bar, slide titles, and bottom conclusion/takeaway bars as body text: the cover and first slide are the first screen (Step 5), each slide or titled card is a unit for unit-promise checks (Step 5), and navigation bars and slide titles are subject to category G just like any other body text. In Step 5 (under **Links between sections**, for slide decks/drafts only — do not apply to regular articles), check each adjacent pair of slides in order: can one sentence transition from the previous slide to the next? Where a transition sentence cannot be written, record a flow (`P`) finding that names the two adjacent slides where it stalls and states which step is missing (missing premise, skipped conclusion, or inverted order). Off-screen speaker notes and end-of-deck provenance/appendix slides count as footnotes/appendices for category G. |
| Opinion piece, news, or announcement with nothing to teach | Say the framework does not apply, and stop or offer a lighter flow review if the user wants one. |
| Article targets experts | Audit against experts; report only what would trip an expert or a newcomer to this specific sub-topic (category G author-workspace leaks still apply unless the user or the article explicitly states that the reader shares that workspace). |
| User supplies a revised version | Audit the new version on its own, then add a short "changes since the previous review" section listing which earlier findings are resolved, partly resolved, or still open. |
