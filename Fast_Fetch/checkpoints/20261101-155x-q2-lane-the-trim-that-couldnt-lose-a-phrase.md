# [Q2-THE-TRIM-THAT-COULDNT-LOSE-A-PHRASE] 2026-11-01 15:5x — q2 lane, root `AGENTS.md` 31,990 B → 29,601 B, every removed line archived verbatim

Tag: `[Q2-THE-TRIM-THAT-COULDNT-LOSE-A-PHRASE]`. Lane: q2 (`/tmp/q2_admin_auth`, branch
`q2-census-pricing`). Slice: owner ruling (3) — *"archive old sections to a dated file, trim root
below 30000 bytes, no content loss."* No test module run locally; no production read; nothing deleted.

## The constraint that actually governs a trim

`AGENTS.md` was 10 B under its 32,000 B ceiling, so "make it smaller" is trivial; "**below 30,000**
with **no content loss**" is not, because 78 of the 104 phrases `test_docs_invariants.py` pins are
pinned to *root* `AGENTS.md` — the adult law, the git-safety rules, all seven guardrail rules, the
secrets table, the loopback-vs-token finding. A diet that cut any of them is green on size and red on
LAW, and the repo already has a precedent for a trim that hid history instead of moving it.

So the order of work was inverted from the usual one: **choose nothing, ask the suite first.** For
each candidate block, "which pinned phrases stop being findable in the trimmed file?" Only blocks
that scored zero moved. That question is `InvariantPhrasesTests` itself, and it can be answered before
a sha without running the module — the suite's own constants (`INVARIANTS`, `CEILINGS`, `ABSORBED`,
`MERGED`, the two link regexes) were imported and re-applied as a static pass.

**The probe was wrong once and the failure mode is worth keeping.** My first version asked "is this
phrase lost relative to the file as it stands *right now*?", which is self-referential after the first
cut: by the third round the baseline already contained the damage, and two losses went silent —
`'No signed APK or AAB has ever existed for this product.'` (my rewrite lower-cased the sentence-initial
`No` mid-paragraph) and `'Do not describe the dashboard as token-gated; describe it as loopback-only,
which is what is true.'` (I wrapped a **markdown table row** across lines, so every continuation line
carried a `|` and the flattened row no longer contained the sentence). The authoritative form is
match-against-`HEAD`, and it is case-sensitive: **whitespace-insensitive does not mean
case-insensitive, and a hard-wrapped table cell is not the same text as the same cell on one line.**
Both were caught by the full 104-phrase pass, not by the incremental one.

## What moved, and where

`docs/ARCHIVE_ROOT_AGENTS_20261101.md` (11,957 B) holds **every removed line, verbatim, as one hunk
per `git diff` against `HEAD:AGENTS.md`** — 8,400 B across 11 removals. Generating the archive from
the diff rather than by retyping it is what makes "no content loss" checkable instead of promised; the
fences are 4-backtick because two archived blocks contain ``` themselves, and a naive
find-and-replace-to-fence silently corrupted the `App` command block's own closing fence on the first
attempt (caught by re-testing `verbatim in archive`, which is the assertion that matters).

Moved: the per-sha `Current Project Status` table (1,484 B); the two CI path-filter measurement
paragraphs (1,883 B) — the four law sentences they carried stayed; the keystore `UPDATE` paragraph's
run ids and base64 byte-accounting (1,812 B → 1,335 B, all four conclusions kept); the operator-panel
`Key Links` row's route-by-route 05:47 measurement (925 B, replaced by the finding plus a pointer to
`docs/ADMIN_PANEL_ACCESS.md`, which is where that law already lives); continuity item 2's quoted test
counts; the worktree-green measurement; App-session item 4's original tag instruction; the five failed
release runs' step-by-step breakdown; the adult-residual per-site concentration (filmyzilla 437,
9xmovies 344, moviezguru 190, hindilinks4u 151) and the `suzume-2022`/`puli-2015` key examples.

Kept in place: all 78 root-pinned phrases, the guardrail, the git-safety bullets, the secrets table,
the whole adult law including the named hole and the pattern law, the `nginx` allow-list, and the
`paths:` trigger literal — i.e. everything an agent must obey, versus what it may look up.

## Verification, and the one thing it cannot prove

Static pass over the suite's own tables (replicated, not executed — the freeze stands): 104 invariant
phrases ✓, ceilings ✓ (`AGENTS.md` 29,601 / FF 14,469 / App 14,061), index shape ✓, invariant targets
reachable ✓, rotated dirs and SPEC layer ✓, relative links resolve ✓, `docs/checkpoints` reachable ✓,
both index count claims equal their directory listings ✓, `ABSORBED` files/headings/indexes ✓, no
conflict markers in the seven multi-lane files ✓, every removed `AGENTS.md` line present in the
archive corpus ✓, and `test_trunk_added_no_line_that_is_now_nowhere`'s computation re-run for both
rotated logs (78 + 50 trunk-added lines, 0 now nowhere) ✓. **CI is still the judge of the real module**
— a replica proves my reading of it, not its behaviour; that gap is the same one the method-error note
in the 09:3x checkpoint describes, and it is why the replica is a pre-check and not a substitute.

Also checked before touching anything: no other suite *reads* `AGENTS.md` (the five files that
mention it do so in docstrings/prose only, and no test asserts a line *number* in it), so re-wrapping
cannot break a citation the way it broke the table-row phrase inside my own text.

## What this changes for the next lane

Root `AGENTS.md` now has **~2,400 B of headroom** under its ceiling instead of 10 B. If you add to it,
`test_docs_invariants.py::ByteBudgetTests` will let you, and the rule the diet exists to enforce —
LAW stays auto-loaded, LOG goes to a dated archive — is the thing to follow, not the byte count. If
you cut, run the phrase question first and match against `HEAD`.
