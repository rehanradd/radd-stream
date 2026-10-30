# 2026-10-29 — `uncut`/`unrated` were never adult markers; the pattern is fixed, the 7,663 are still flagged `[Q5-UNCUT-FALSEHIDE-P1B]`

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 — `uncut`/`unrated` were never adult markers; the pattern is fixed, the 7,663 are still flagged `[Q5-UNCUT-FALSEHIDE-P1B]`

**The mistake, in one line:** `ADULT_TITLE_PATTERNS` carried `r"\buncut\b"` and
`r"\bunrated\b"`, which are *edition* labels (desicinemas writes them on mainstream releases),
and the key-level law I shipped an hour earlier turned each of those false row-flags into a
whole hidden film. Owner's measured scale on prod: of 15,068 flagged rows **7,663 (51%) were
justified only by those two words**, 2,647 match no adult pattern at all. He already reversed
his own damage from the preimage, keeping 48 genuine flips and undoing 407; prod is back to
**posts 150,799 / is_18_plus=1 15,068 / public 135,731**.

**What is on `master`/`main` now (`ab78849`, was `c401021`):**
- both version words removed outright from `fast_fetch.py` **and from the seven other lists**
  that held them (the inline multimovies pattern list, plus `import_9xmovies`,
  `import_bolly4u`, `import_world4ufree`, `import_moviezguru`, `import_filmyzilla`,
  `import_multimovies`); `\b18\+` collapsed into `\b18\s*\+`; no co-occurrence rule added,
  because no test could show one catching what the remaining patterns miss.
- `test_database.py` 88 → **119 tests**, pinning both directions on the shapes that broke
  (Kanguva HDRip Uncut, Hi Nanna Unrated Director Cut, an uncut **slug** through
  `save_scraped_data`, `18+ Adult Erotic` / `Ullu` / studio+uncut still flagging) and re-proving
  the key law after the change.
- `Fast_Fetch/audit_adult_flags.py`: classifies every flagged row (stored-text adult /
  version-word-only / no-stored-evidence, the last resolved from that site's staging vault) and
  **reports by default**. Writes need `--owner-go` (plus `--prod` for the live catalog) and it
  fsync-then-rereads a `(id, canonical_key, old flag)` preimage first. **I did not run it
  against prod and did not mass-unflag anything** — that is the owner's exposure event.
- TLS: one `config.tls_context()` factory replaces the engine's module-level `CERT_NONE`
  context and its two hand-rolled copies; `RADD_TLS_VERIFY` defaults to today's permissive
  behavior, `RADD_TLS_VERIFIED_HOSTS` graduates a host to real verification, and a test proves
  a listed host with an untrusted chain **raises instead of returning bytes**.

**Two TLS facts the owner asked for, measured on `ab78849` (detail in `Fast_Fetch/CONTINUITY.md`):**
the bad-chain population is not enumerable offline — 64 log/txt files under the data dir plus
`journalctl -u radd-stream` record **zero** verification failures, because verification has
never been attempted there. The usable input is the canary set: **121 distinct hostnames** in
`https://` literals across non-test modules, to be walked through `RADD_TLS_VERIFIED_HOSTS` in
batches. And the permissive default is not engine-wide: three `urlopen` calls (`:375` TLD
discovery, `:4942` media Range probe, `:5816` domain-health CLI) pass no context and have always
verified — so `RADD_TLS_VERIFY=permissive` is not a total rollback switch. **25 hand-rolled
permissive contexts still live in other lanes' modules** (importers, `site_scout`,
`bridge_tracer`, `domain_resolver`, `link_health`, `scrape_multimovies_full`); they were left to
their owners rather than rewired under a privacy fix.

**Read this before the next move:**
1. The projection-rebuild precondition from the entry above is now met — the pattern fix is on
   `main`, so a rebuild will not bake the version-word false hides into `cat_works.is_18_plus`.
   The better order is still: owner runs the un-flag pass, then rebuild, then the restart he
   approves. Nothing here restarts the unit.
2. **HOLD stands:** no merge batch 4, no kuttymovies/DesiSerials ingestion into prod until the
   un-flag pass has run.
3. Re-key migration is **still paper only**. Under the corrected identity prod has 2,600 keys
   carrying both a flagged and an unflagged row, 3,486 publicly served rows under those keys, and
   a 69,773-row re-key blast radius. Design + measured blast radius first, owner approves before
   anything writes.
4. `AGENTS.md`'s adult section still quotes the pre-backfill exposure numbers (442 keys / 455
   rows) as history; the current truth is the 2,600 / 3,486 / 69,773 figures in item 3, and any
   agent who reads "15,068 flagged" should read it with 7,663 false positives still in it until
   item 1 runs.

**Gate proof:** CI's 16 modules, one invocation each, from a clean worktree of `ab78849` —
939 tests, 16/16 OK, worktree clean before and after. Verified host-only; no prod database was
opened, no full scan or join was run against the 6.37 GB catalog.

