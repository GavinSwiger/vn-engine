# ADR-0006 — Stable statement identity

Status: **accepted** — 2026-11-01 (with clarifications; Addendum 1 for menus, F07)
Proposed by: vn-feature-architect (F02 `04-technical.md` §7.8, §17.1). Reviewed by:
vn-product-designer (PR-F02-29, C1), vn-narrative-designer (O6, O8), vn-security-reviewer
(F02 `05-security.md` §5.4, SEC-F02-10). Decided by: vn-system-architect (F02
`07-architecture-review.md`).

## Context

Saves (F11), rollback (F14), read-text tracking (F15), history (F13), the flowchart (F20),
hot reload (F39), and translations (F43) need a per-statement identity that survives
reloads, operating systems, edits to other labels, moving a label to another file, and
renaming files (PR-F02-29). Authors never write it. The engine keeps no compiled cache
between launches (invariant 3, F02 scope).

## Options

1. Label + index path: typo fixes keep the identity, but every insertion shifts later
   identities, so read marks and saves silently land on the wrong line.
2. File + line: fails the move-a-label and edit-elsewhere rules.
3. Author-written ids (Yarn Spinner's `#line:`): rejected by product.
4. Carry ids over from the previous build (Ren'Py's approach): needs a cache in a write
   root and a safe format; out of scope.
5. A content hash scoped to the label, with an occurrence counter.

## Decision

Option 5.

- A statement's identity (`sid`) is `"<label>/<h>"`, or `"<label>/<h>~<n>"` for the n-th
  (n ≥ 2) statement in that label with the same `h`, counted in pre-order (an `if` before
  its branches' statements). `<label>` is the canonical (NFKC) label name. `<h>` is the
  first 6 bytes of BLAKE2b, written as 12 lower-case hex digits, of the UTF-8 encoding of
  `"\x1f".join(("v1",) + identity_key)`.
- Keys (F02 `04-technical.md` §7.8): `Say` → `("say", NFKC speaker or "", norm(text))`;
  `PythonLine` → `("py", norm(code without Python comments))`; `If` →
  `("if", norm(first condition))`; `Jump`/`Call`/`Return` → `("jump", target)` /
  `("call", target)` / `("return",)`. `norm(s) = " ".join(s.split())`. Dialogue attributes,
  file, line, column, indentation, nesting, and line wrapping are excluded.
- Labels have the identity `<label>`, defines `define:<name>`, includes `include:<path>`.
  These are not statement identities: `Program.get` never returns them.
- `engine/script/identity.py` exports `IDENTITY_SCHEME = 1`. Any data that persists an
  identity also stores the scheme it was made with.
- **Clarification 1.** The `"v1"` salt and `IDENTITY_SCHEME` change together. Changing a
  key, the normalization, the hash, or the format is a new scheme.
- **Clarification 2.** Canonical names use NFKC from Python's `unicodedata`. A Python
  upgrade can change NFKC only for newly assigned characters. This is accepted; it never
  affects ASCII names.
- **Rule for later statements.** Each new `Statement` subclass defines `identity_key()`:
  include what makes it "the same line" to a reader or translator (its words and
  arguments); exclude file, line, indentation, and presentation-only modifiers. The key
  is reviewed with the feature.
- Lookups from saved data use only `Program.get`, `location`, `label`, `at`, and
  `statements_in`. They accept any JSON value and return `None` or nothing for anything
  but an exact match, never raise, and never parse `~n` (SEC-F02-10).

| Edit | Identities |
|---|---|
| Any edit in another label, in any file | unchanged |
| Move a label to another file; rename or move a file; reorder includes | unchanged |
| Insert, delete, or reorder statements in label L | others in L unchanged, except a later statement with the same key as an inserted or deleted one (its `~n` shifts) |
| Re-wrap continued text; change whitespace, indentation, comments, or dialogue attributes; move a statement into or out of an `if` block in the same label | unchanged |
| Change a statement's text, speaker, code, condition, or target | that statement changes |
| Move a statement to another label; rename a label | the moved statement / every statement of the label changes |

## Consequences

- Every failure is "not found", never "the wrong line". F15 shows an edited line as
  unread, F43 shows it as needing translation, F11 and F39 fall back to a saved
  `StmtLocation` or ordinal (F11's policy).
- A typo fix changes that line's identity (product accepted, PR-F02-29).
- Identities are short JSON-safe strings grouped by label.
- 48 bits per label gives about n²/2⁴⁹ accidental collisions (1.8 × 10⁻⁷ for a
  10,000-statement label). A collision only puts two statements in one `~n` sequence; both
  stay unique. The hash is not a security boundary: a save editor can write any identity,
  so identities are references, never proof (security §5.4).
- A scheme change is a breaking change for saved data: a new `IDENTITY_SCHEME` and a
  migration in each feature that persists identities.

## Addendum 1 — Menus and choices (F07)

Status: **accepted** — 2026-11-01. Proposed by vn-feature-architect (F07 `04-technical.md`
§6.4, §18.2, C10). Decided by vn-system-architect (F07 `07-architecture-review.md`).

**Context.** F07's `menu` is a statement whose body is an optional question line and 1–6
choices, each with its own block. The pick record (F13, F19, F20), restore at a menu, and
translations (F43) need stable references to choices, but choices aren't statements.

**Decision.**
- `Menu.identity_key()` = `("menu", NFKC speaker or "", norm(question text or ""))`: the
  question's words, keyed like a `Say`. Choices, conditions, and the `voice` line above the
  question are excluded, so editing choices keeps the menu's sid and the saves made at it.
- The question `Say` has no identity of its own. It carries the menu's sid, is never walked,
  and is never a position. `Program.get(menu sid)` returns the `Menu`.
- A choice's key is `statement_hash(("choice", norm(text)))`, with the text as written, plus
  `~n` for the n-th equal hash within its menu (n ≥ 2, script order). Keys are unique within a
  menu; the full reference is `(menu sid, choice key)`. A choice key is not a sid:
  `Program.get` never returns a choice.
- Paths: `Statement.blocks()` generalizes `If` branches. Statement j of choice c of the menu at
  path p is `p + (c, j)`. Pre-order is the menu, then choice 0's statements, then choice 1's,
  and so on. `walk_block`, `Program.at`, and every nested walk descend through `blocks()`.
- `IDENTITY_SCHEME` stays 1 and the salt stays `"v1"`: no existing key, normalization, hash,
  or format changes, and `If.blocks()` gives the same pre-order, so every existing sid is
  unchanged (F02's identity goldens must pass unchanged).

**Consequences.**
- Question-less menus in one label share the key `("menu", "", "")` and are told apart by
  `~n`, like `return`. Inserting one shifts the later ones. A save at a shifted menu then
  usually fails F07's restore check (a saved pickable key must name a current choice) and is
  "not found"; it reaches the wrong menu only if the choice texts coincide.
- Rewording a choice changes only that choice's key. Recorded picks keep the old key, and
  readers treat keys that no longer resolve as unknown. Reordering choices keeps their keys,
  except the `~n` of duplicate texts.
- Rewording the question or changing its speaker changes the menu's sid (POSITION_NOT_FOUND,
  or F11's location hint).
- Choice keys are references, not proof, like every identity (security §5.4).

## Status history

- 2026-11-01: proposed (F02 `04-technical.md` §17.1); NFKC speaker added (narrative O8).
- 2026-11-01: accepted with clarifications 1 and 2 and the lookup rule (F02
  `07-architecture-review.md`).
- 2026-11-01: Addendum 1 (menus and choices) accepted (F07 `07-architecture-review.md`).
