# Report template

Write the report in the report language (see Inputs in `SKILL.md`). Translate every heading,
every bold field label, and all prose below; keep in English only the fixed vocabulary listed
in `SKILL.md` Step 6 rule 5 (ids, results, severities, gaps, paths, roles), so reports stay
comparable across languages. Omit a section only where the template says it is optional.

Every finding has exactly one severity (`high`, `medium`, `low`; see Severity in `SKILL.md`).
`low` findings get one line under Low-priority notes. `high` and `medium` findings get a full
entry: `C`, `A` and `M` entries under Findings; `P` entries under Promise and flow, after its
four one-line checks. Concept results and severities go together: `fail` is `high` or
`medium`, `warn` is `medium` or `low`.

When one problem is already written up as a full entry elsewhere (`SKILL.md` Step 6 rule 4),
do not open a second full entry: in the concept index keep the node with its result and
severity, and where the second entry would go write one line, `see A01`, in the
`Checks that failed`, `Problem`, or Promise-and-flow line. A one-line pointer satisfies the
full-entry requirement for that finding.

```markdown
# Piaget review: <article title>

- **Article**: <file name or link>; <article type>; about <N> words
- **Target reader**: <stated by the user | stated in the article: "<quote>" | inferred: one sentence, with the evidence>
- **Verdict**: <one sentence, including "N concepts: a pass, b warn, c fail" (and "d not audited" if any)>
- **Worst issue**: <one sentence naming one high or medium finding id | "none", with why the audited part works>

## Top findings

1. <id> (<severity>) — <one or two sentences: what happens to the reader, and the fix>
2. …
3. …

(At most three, highest severity first. Write "none" if there is no high or medium finding.)

## What works

- <one to three short points worth keeping>

## Reader profile

| Dimension | Assumed reader (from the text) | Gap to target reader |
|---|---|---|
| R1 Background knowledge | … | none / small / medium / large: … |
| R2 Abstraction level | … | … |
| R3 Notation and jargon | … | … |
| R4 Procedural skills | … | … |
| R5 Intuitions and visual sense | … | … |
| R6 Code and tools | … (write "not applicable" when there is no code) | … |
| R7 Reading behaviour | … | … |

## Concept index

| Id | Section | Concept | Path | Result | Severity |
|---|---|---|---|---|---|
| C01 | <heading> | <concept> | assimilation / accommodation | pass / warn / fail / not audited | — / high / medium / low |

## Findings

### C02 <concept> — fail, high

- **Where**: <heading> — "<short quote>"
- **Checks that failed**: <e.g. Check 2b conflict: absent; Analogy: breaks without warning>
- **What the reader will likely do**: <one or two sentences>
- **Fix**: <what to add, move, or reword, and where; optional sample sentence>

### A01 <assumption> — medium

- **Where**: <heading> — "<short quote>"
- **Category / dimension**: <A–F> / <R1–R7>
- **What the reader will likely do**: <what the target reader lacks here, and what happens>
- **Fix**: <define here, link, add a step, or narrow the target reader>

### M01 <code block, command, figure, or media (or a missing one)> — <role, e.g. procedural or missing>, medium

- **Where**: <heading> — <first line or caption, or "the second code block">
- **Problem**: <e.g. a variable is never defined; the text never says what the plot shows>
- **What the reader will likely do**: <e.g. copy the code, get an error, and stop>
- **Fix**: …

## Promise and flow

One line each for the four checks below; any problem at `high` or `medium` also gets a full
`P` entry after them. `P0n` stands for the actual id: `P` findings are numbered in reading
order like every other prefix, not by which check found them.

- **Promise**: <delivered | partly delivered: see P0n>
- **Links between sections**: <no issues | see P0n>
- **Active moments**: <present at … | missing for C03: see P0n>
- **Ending**: <consolidates | stops: see P0n>

### P01 <problem> — medium

- **Where**: <heading> — "<short quote>"
- **What the reader will likely do**: …
- **Fix**: …

## Low-priority notes

- <id> (low) — <heading> — "<short quote>": <one line>

## Changes since the previous review

(Optional: only when auditing a revised version.)

| Earlier id | Status | Note |
|---|---|---|
| C02 | resolved / partly resolved / open | … |
```

Id prefixes: `C` concept nodes, `A` hidden assumptions, `M` code, commands, figures and media,
`P` promise and flow. Number each prefix from `01` in reading order. Low-priority items keep
their prefix and number.
