# ADR-0010 — New script words are positional, never reserved

Status: **accepted** — 2026-11-06 (owner-approved with the skins plan, `specs/skins-contract.md`)
Proposed by: the skins plan (docs/proposals/engine-features.html, "Positional words"
foundation). First applied by: F62 round 1 (`ranks`, `points.rank`).

## Context

`engine/core/constants.STATEMENT_WORDS` reserves 40 words: a line that starts with one is
that statement, and no label, character, variable, meter, or define may use one, in any
capitals (E60). Reserving a word is a breaking change: a game that already has
`default event = 0` or a character called `clock` stops loading when the word is added.

The engine-features plan adds about a dozen words (`event`, `clock`, `place`, `map`, `send`,
`present`, `roll`, `camera`, `bubble`, plus modifiers such as `ranks`). Earlier features
already avoided reserving words inside statements (`tip`, `item`, `gallery` after
`lock`/`unlock`; the glitch names after `effect`; F04's stage words), each by its own rule.
This decides the rule once.

## Options

1. **Reserve each new word.** Rejected: every release could break a working game, and the
   name lists grow without end.
2. **Reserve none; decide each word by where it stands.** Chosen.
3. **A version switch in config** (`language = 2` turns new words on). Rejected: two
   languages to document, check, and support in Studio.

## Decision

1. **The reserved list is closed.** `STATEMENT_WORDS` keeps its 40 words and gets no more.
   New words never give E60 and stay valid names of labels, characters, variables, images,
   meters, and defines.
2. **Words inside a statement** are that word only in the place the statement expects
   them, and, where a name could stand in the same place, only when what the word needs
   follows. F62: on a `points` line, `ranks` starts the ranks only when a quoted label
   follows it; otherwise it is a meter name (`points ranks 0 to 10`).
3. **A new statement word** is that statement only as the first word of its own line. A
   line that starts with the word and then a quoted string (`event "Wait!"`) stays dialogue
   by a character of that name, as F04's stage words already do (`layer "Hi"`). Python
   (`$` lines, conditions, values) never sees statement words, so the word is always a
   name there.
4. **One checker rule per new statement word**: when a line starting with it fails to parse
   as the statement and the game defines a character (or variable) of that name, the error
   says how to write the other reading. The first feature that adds a statement word adds
   this rule beside its parser.
5. **Engine names' attributes are separate.** A read-only engine view (`points`, `codex`)
   may give methods names its own entries can't take: a meter can't be `highest` (F22) or
   `rank` (F62, E414). This binds only that view's names; variables and characters are free.
6. **Docs.** docs/script-language.md §19 states the rule once; each statement's section says
   where its words count.

## Consequences

- Updating the engine never makes a working script fail to load because of a new word.
- Parsers for new statements must accept the dialogue reading (rule 3) and give the
  rule-4 hint; review checks both.
- Studio's syntax colouring colours a positional word only in its place, as it does for
  F51's `time` and F59's `check` (F62: `ranks` before a quoted label on a `points` line).
- A word that turns out to need reserving would need a new ADR and a migration note.
