# SPEC ADULT FLAG EVIDENCE

> Moved **verbatim** out of `AGENTS.md` by the 2026-10-30 documentation diet.
> The diet splits LAW / LOG / SPEC and never deletes: every line below is
> byte-identical to what `AGENTS.md` carried at `dc73ac7`.
### from `AGENTS.md` lines 95-97

  Proved live on this host: `/api/v1/posts/159` (a flagged post) is 404 on loopback and at the public
  edge, `/api/m3u?id=159` returns 0 bytes where `/api/m3u?id=158` returns a real playlist, and
  `/api/m3u` is 403 at the edge.

---

### from `AGENTS.md` lines 122-124

  `Fast_Fetch/backfill_adult_key.py` reconciles rows written before the law existed (report, then
  `--apply`, then `--apply --projection`) and prints the public total before and after, refusing to
  commit unless the total dropped by exactly the number of rows it flipped.

---

### from `AGENTS.md` lines 145-162

  **The 7,663 is the wide measure; the ledger-text measure is narrower, and the difference matters
  to anyone reading a candidate list.** One read-only pass over `posts` on the production catalog
  (2026-10-29, `audit_adult_flags.classify`, no vaults) splits the 15,068 flagged rows into
  **9,069 true-adult in their own stored text, 4,246 version-word-only, 1,753 with no pattern
  evidence in the ledger at all** across 14,931 distinct `canonical_key`s. Only the 4,246 are
  un-flag candidates — the rest of the owner's 7,663 count adult words that live outside
  `title`/`clean_title`/`slug`/`url` (tags, `raw_meta`, site-wide rules), which the ledger alone
  cannot see. Freeing them leaves **39 mixed keys** (one copy served, one still hidden) and 4 rows
  are blocked by a true-adult sibling.
  **Four patterns still hide mainstream works, and none of them was touched** because the standing
  instruction was to weaken nothing else: `\bhunters\b` (128 rows, 127 matched by nothing else —
  e.g. *KPop Demon Hunters*, *Transformers Prime: Beast Hunters – Predacons Rising*),
  `\brabbit\b` (61, 56 — *Wallace & Gromit: The Curse of the Were-Rabbit*, *1001 Rabbit Tales*),
  `\bnaughty\b` (169, 149) and `\badult\b` (1,480, 82 — *Shin-chan: The Adult Empire Strikes Back*).
  By the rule above, a version word may not be a pattern; these four are not version words either,
  but they name a genre noun, not a person, studio, or act, and each has a title in the catalog that
  proves the false positive. Removing one is the owner's exposure decision, not an agent's — and
  `audit_adult_flags.py` reports what each one hides before anyone writes.
