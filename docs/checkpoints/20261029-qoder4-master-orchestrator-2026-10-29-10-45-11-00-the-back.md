# qoder4 (Master Orchestrator) — 2026-10-29 10:45-11:00, the backfill ran and was partly rolled back

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## qoder4 (Master Orchestrator) — 2026-10-29 10:45-11:00, the backfill ran and was partly rolled back

I ran the P1 backfill myself against production, then reversed most of it. Both halves are
measured, and the reversal is the important part.

**Gate first.** From a clean worktree of `f3924a3` I ran CI's real 15-module list one module
per invocation, plus `importers/test_host_resolvers.py`: **16 PASS / 0 code failures**
(`test_database` 88, `test_redact` 58, `test_catalog_v2` 91, `test_api_v2` 46, host_resolvers
171, etc.). `qoder5` pushed it; `af68450` is `master` == `main` with **2/2 check suites
completed/success**. Rollback point verified identical to live before writing:
`prebatch4_20261029_051444.db` (posts 150,799 / adult 15,020 / public 135,779 / 455 exposed).

**The flip.** Report mode reproduced my independent count exactly (442 keys, 455 rows,
residual 1,190). `--apply` took **1.4 s**: 455 rows flagged, public 135,779 → 135,324,
`flipped == delta`, self-verification passed. Live with **no restart**, because the unit's
`RADD_DB_PATH` is `merged_catalog_20261025.db` and every request re-queries it.

**Then I audited why those rows were flagged, and the premise was wrong.** Of the 455:
**0** matched an adult pattern in their own stored text, **375** matched only because a
*sibling* did, **80** matched nothing stored at all. The siblings' patterns were
`\buncut\b` ×300 and `\bunrated\b` ×31. "Uncut" and "Unrated" are **version labels**, not
adult markers — the writer is `desicinemas`, and the works they hid are mainstream
(Kanguva, Hi Nanna, Guntur Kaaram, Junior, Election, Double iSmart, Das Ka Dhamki, Gangs of
Godavari, Kannur Squad, DeAr, Dharmaveer 2, Ratham, Yaathisai, Extra Ordinary Man). My
earlier "Dharmaveer 2 is now hidden" line was a claim about **hiding a legitimate film**.
The per-key law qoder5 built is correct; its input was poisoned, and key-level propagation
turns one misflag into a whole work disappearing.

**Reversal.** I captured a per-row preimage BEFORE writing
(`adult_flip_preimage_20261029_104859.json`, 455 rows + `.ids`), then re-justified every flip
against its own text, its siblings' text, and — for the 80 — the source vault's full raw row
(3 justified). Kept **48**, undid **407** in one transaction with `restored == delta` asserted,
then `wal_checkpoint(TRUNCATE)`. Verified through the public edge, not the file: total
135,779 → 135,324 → **135,731** (= 135,779 − 48); ids 2373/2338/2287/2328 visible again;
**0** of the 48 kept rows still publicly readable. Ledger now posts 150,799 / adult **15,068**
/ public 135,731. Journal: `adult_flip_rollback_journal.txt`.

**Scale of the underlying defect (measured, read-only, prod).** Of 15,068 flagged rows,
**7,663 (51%)** are justified *only* by `uncut`/`unrated` in stored text and **2,647** match
no stored pattern at all (evidence lives in `tags`/`raw_meta` at scrape time, which the ledger
does not keep). True-adult frequency: `18+` 3,309, `adult` 1,480, `ullu` 807, `naughty` 169,
`hunters` 128, `xxx` 73. **I did not touch the 7,663** — un-flagging them is an exposure event
and needs a code fix plus a `raw_meta` audit, not an ad-hoc UPDATE.

**Also measured the opposite direction** (identity normalized to
`generate_canonical_key(clean_title, year)`, 150,799 rows scanned): 109,912 distinct keys,
**2,600** keys holding both a flagged and an unflagged row, **3,486 publicly served rows**
under those keys, and a **69,773-row re-key blast radius**. That is the leak the per-key law
cannot reach, and it is why `?q=4+Play` still returns id 23519: same film as
`4-play-2021-hindi-movie-free-download` (flagged, filmyhit) but stored under
`4-play_2021` (hindilinks4u). Design review before any re-key write.

**Held by my order:** no merge batch 4, no kuttymovies/DesiSerials ingestion into prod until
the pattern fix is on `main` — otherwise `inherit_key_adult` re-propagates the garbage.

**VM.** An idle 2.1 GB Gradle daemon (pid 1030434, `-Xmx1536m`, 3 h resident, no client
attached) was squatting on RAM during qoder2's crawl; `./gradlew --stop` reclaimed it
(MemAvailable 2,778 → 4,818 MB, swapFree 1,739 MB). Load 2.6-2.9, API ~0.16 s, disk 113 G free.
**Fleet reality check:** qoder2 hit "Model queued (57 s)" — the account tier throttles, so
throughput is ~2 concurrent agents, not 4. `qoder3`'s CLI (pid 671341) is `SIGSTOP`'d with a
bash prompt in its pane; keystrokes there hit the shell, not an agent. Left stopped on purpose:
resuming it releases an ungated pusher.

**Recovered the owner's actual fleet plan** (`docs/MONETIZATION_AND_FLEET_PLAN.md`, untracked):
qoder1 = pre-roll/native ads + 25-min cap + 7-day streak UI; qoder2 = Hum TV/Geo/ApneTV;
qoder3 = green backend CI (**done**, shipped as `64c0b1b`); qoder5 = `safe_link_rollup` +
`/api/v2/account/wallet`. qoder1's shortener directive arrived **truncated twice** ("must be
100% direct with" has no ending), which is why its items 2+ never ran.

### The live process is 2 days 15 h older than `main`, and that is why two public surfaces disagree

Measured, not inferred: `systemctl show radd-stream -p ExecMainStartTimestamp` →
**Tue 2026-10-27 19:47:16 PKT**, still `active`. `/opt/radd-stream/Fast_Fetch/viewer.py` has
mtime 10-29 05:16 and contains the fixed stats path (`links_by_state_safe` appears twice,
identical to `main`). Python binds source at import, so the interpreter is executing the
Oct 27 code and **no edit to the tree changes that**. Consequence, measured through the public
edge right now:

    GET /api/v1/posts?limit=1   -> total 135,731   (matches my ledger write exactly)
    GET /api/v1/stats           -> {"posts": 116922, "releases": 1383752,
                                    "sources": 3783959, "active_sources": 3783959}

`/api/v1/posts` looks current because it re-queries SQLite per request — which is precisely
how my adult flip and rollback were visible with no restart. `/api/v1/stats` looks wrong
because its *code* is old: `posts` is the stale projection stamp `works` (116,922, stamped at
the 9,770 s rebuild), not the ledger (150,799) and not the adult-excluded live count
(135,731); `releases`/`sources` are stamps too (ledger: 1,780,121 and 4,073,865). And
`active_sources == sources` is the exact bug `34f22c6` removed from the source, while
`cat_projection_meta.links_by_state` in the same database already says
`{"unchecked": 3456460}` with `link_coverage = 0.0`. The endpoint is publishing as "active"
3.46 M links that its own ledger admits were never probed.

**Do not "fix" this by editing viewer.py again — it is already fixed on `main`.** Two things
are required, both owner-gated, and I am not restarting the production unit on my own
authority:
  1. an owner-approved restart to load the current code (this is the activation step already
     recorded above for the ingest-path change), and
  2. a projection rebuild, which must wait for the `uncut`/`unrated` pattern fix (task #12)
     or it will bake 7,663 false hides into `cat_works.is_18_plus` — the surface the app and
     the v2 API filter on.
Until both land, treat `/api/v1/stats` as stale-but-harmless and read the truth from
`/api/v1/posts?limit=1` (`total`) and from SQLite directly.

