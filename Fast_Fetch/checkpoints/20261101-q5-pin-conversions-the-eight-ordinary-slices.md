# 2026-11-01 — q5 backend lane `[Q5-PIN-SERIES]` the eight ordinary pin conversions, one pin per slice

Session: q5 (account5), worktree `/tmp/q5_gate5`. Muse 09:03: gate **HELD** (qoder1's write credential is dead,
owner-only fix), so nothing is gated by this lane and the stack is not replayed yet; continue the **eight
ordinary `INVARIANTS` conversions, one at a time**, own worktree only, CI-verifiable, push each slice branch and
report its sha. Do not rewrite `AGENTS.md` to fit a pin (10 B headroom). No merge, tag, restart, production
read or write; no Gradle at load ≥ 4.

This file is the rolling record for that series — **one file for eight slices, deliberately**, so the archive
count moves once rather than eight times. Each slice adds a section; nothing earlier in it is rewritten.

## The rule this series runs on

A conversion re-points a pin from a **value** to the **clause in the same sentence that makes the value
non-load-bearing**, and it may only target a clause that *already exists* in the document. No doc gets edited
to fit a pin, because root `AGENTS.md` has 10 bytes of headroom against its 32,000 B ceiling and `App/AGENTS.md`
939 B against 15,000 B — "write new law so the pin has something to bite" is not available at the margin, and
refusing it is the difference between a docs tidy and a lane editing the constitution to match a test.

Every slice re-derives, by importing the guard rather than grepping it: `len(INVARIANTS)` (104), zero missing
phrases, zero duplicate labels, the byte sizes and line counts of the capped docs, and the two archive-count
claims against their directory listings. Grep is the method that produced the "98 entries" error in the
previous checkpoint; it is not used here.

## Slice 1 — `measured: secrets list is empty` → "so it is a real answer and not a permission artifact"

**Branch:** `q5-pin-s1-secrets-empty-20261101`, stacked on `19b4a5f` (which is stacked on `c0e86e5`, which is
stacked on trunk `c2528e1`). Stacking is deliberate: gate order is qoder1's at gate time, and a chain replays in
one command while eight sibling branches replay as eight merges against a file every one of them edits.

**What it pinned:** `{"total_count": 0, "secrets": []}` — a literal HTTP response body from
`GET /repos/…/actions/secrets` measured 2026-10-29, in a paragraph that `63396c1` and the
`**UPDATE (Measured 2026-10-30 22:53, then re-measured 2026-10-31 07:5x)**` block in the same section have
since overturned: all four keystore secrets are configured now. So the guard was holding
up a *retired blocker* — the worst shape of state pin, because a lane that corrected the prose would go red,
and a lane that left it alone would keep a false sentence guarded.

**What it pins now:** "so it is a real answer and not a permission artifact" — the reading rule the same
sentence exists to teach. The old paragraph's whole argument is that an empty list is only evidence once you
know the reader's repo permissions (`{admin: true, push: true}` there). That clause does not rot when GitHub's
secret list changes, and it is the part that generalises to the next "the API says zero" claim anyone cites.

**Checked, not assumed:** the candidate clause was verified present verbatim in `AGENTS.md` before the edit,
and verified **not** already the target of another `ROOT_AGENTS` pin — the overlap test is not substring
containment, because this series nearly fooled me twice: `no signed artifact has ever been produced` looked
free to convert onto "no agent may create, move or delete a tag", but that is the *second half of a sentence
already pinned by its first half* (`cutting and moving tags is owner-only`), so the conversion would have added
a duplicate and removed a value. That candidate is dropped; slice 3 takes a different clause.

**Trade, stated:** nothing now fails if the empty-list measurement is deleted or reworded out of `AGENTS.md`.
The measurement stays there as dated history (`Measured 2026-10-29 17:55`), and the guard keeps the *reason it
was believable* — which is the part worth keeping.
