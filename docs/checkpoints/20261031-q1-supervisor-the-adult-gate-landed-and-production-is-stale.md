# qoder1 supervisor pass — the adult gate landed, production is stale, and six files of App work existed nowhere but the deployment tree

**Token:** Q1-SUPERVISOR-PASS-3 · **Trunk:** `3a247dc` → `4a8c163` on `master` and `main`
· **Host:** 1 vCPU, load oscillating 2.87 → 4.69 across the pass, `mem_avail` ~3,750 MB,
`swap_free` ~3,041 MB — the hard floor was never breached. Local execution was limited to
four offline markdown/logic modules (`test_docs_invariants` ×2, `test_merge_catalogs`,
`test_adult_corroborated_fold`), each alone and under `nice -n 19`, in the two sub-4.0
windows. No crawl, no merge, no Gradle, no production read. Every other gate is a hosted
GitHub Actions run.

## 1 — The milestone log, and why it cost bytes it had to earn

`Fast_Fetch/CONTINUITY.md` item 14 records the previous pass and is now landed as `3a247dc`.
The file's own ceiling is enforced (`≤ 12,000 bytes`, `≤ 120 lines`, and the count on line 10
must equal the directory listing minus `README.md`), so adding an entry is a compression
exercise, not an append. It went 11,351 → 11,817 → 12,080 bytes mid-merge: the merge of
qoder5's branch pushed it over, and the fix was to compress two of **my own** supervisor
pointer lines while keeping every checkpoint path verbatim, because the guard asserts the
paths are reachable. Final: 11,957 bytes / 109 lines, archive count 56 → 57 (55 dated + 2
undated). The history itself was never shortened — only the index's prose.

## 2 — `q5-adultkey-reconciliation` is trunk

I held this branch on exactly one line: `test_merge_catalogs.py` audited
`SELECT post_id, source_post_id, evidence FROM adult_fold_journal` on the two paths where
nothing had created the table, because `merge_catalogs.py` guarded the fold call with
`if apply and exposures:`. Root-caused by reading, not running, at load 5–7. Both halves are
now fixed in code: the DDL runs on every merge whether or not anything folded, and a skipped
fold reports `adult_fold_skipped: 1` instead of being indistinguishable from a fold that
found nothing.

Evidence, two ways. Hosted run `41156831610` reports all 39 steps `success`, including
step 16 `🧪 test_merge_catalogs.py` and step 37 `🧪 test_adult_corroborated_fold.py`. Then,
in a sub-4.0 window at load 2.87, locally: `test_merge_catalogs.py` **Ran 8 tests … OK** and
`test_adult_corroborated_fold.py` **Ran 44 tests … OK**. Trunk `4a8c163` is green on both
refs (runs `41157445951`, `41157449578`, both `completed/success`).

What I verified in review rather than accepted from the author:

- **The fold propagates only reproducible evidence.** `adult_rule_agrees()` re-runs
  `is_adult_title()` on the row's own `clean_title`/`title`/`slug`, so an asserted-only flag
  cannot multiply across its siblings. `test_a_disputed_flag_folds_nothing_at_merge` pins the
  407-mainstream-works boundary as an executable fact, which is the property this file has
  carried as a *claim* since 2026-10-30.
- **The fold writes the database the merge was pointed at.** `merge_site_db` rebinds
  `fast_fetch.DB_PATH` to `target_db_path` at `:263` before any `get_db()` opens one, and
  `get_db(None)` falls back to that same global. I checked this specifically because the new
  fold opens `fast_fetch.get_db()` with no argument while the merge is handed a path — the
  classic shape of a target-scoped operation reaching the production catalog by accident.
  It does not, here, and the mechanism is pre-existing trunk code, not the new patch.
- **The `link_is_adult` fail-open → fail-closed flip cannot refuse a playable link.** Both
  callers (`viewer.py:3695` `/api/v1/stream`, `:3757` `/api/v1/download`) resolve an id from
  `download_sources`, and `fast_fetch.resolve_live_source` selects `FROM download_sources
  WHERE id = ?` (`:5449`) — the same id space the guard queries. An unknown id had no row for
  either, so refusing it removes no capability. This closes the hazard this file has listed as
  an open owner decision: the docstring and root `AGENTS.md` both already claimed fail-closed,
  and now the code agrees with both.
- `--apply` is now documented as the *unsafe* older path (it propagates asserted-only flags),
  with `--audit` / `--corroborate` / `--undo` as the gated ones. Nothing here touched the live
  database, and no tag was created.

## 3 — Production is stale, and that is the finding the owner has to act on

Landing is not shipping, and today the gap is measurable and large. `radd-stream.service` is
`active` as pid `1835070`, started Fri Oct 30 17:09:51, `WorkingDirectory=/opt/radd-stream`,
`ExecStart=… fast_fetch.py serve --host 127.0.0.1 --port 8080` — so the code it loaded is the
working tree of that directory, and that tree is checked out at `bf9e565`.

Measured against trunk `4a8c163`:

| | live tree | trunk |
|---|---|---|
| `fast_fetch.py` occurrences of `corroborated_adult_exposures` / `adult_rule_agrees` / `adult_fold_journal` | **0** | present |
| `redact.py` unknown-link answer | `:1097 return bool(row and row[0])` → **fail-open** | fail-closed |
| `viewer.py` | 3,576 lines | 4,042 lines |

So the merge-time adult law, the fail-closed redirector, and ~466 lines of API surface are
**correct on trunk and absent from the running system**. The compliance sentences in root
`AGENTS.md` that describe fail-closed behaviour are true of trunk and false of production
until someone updates the checkout and restarts the service — both owner actions, which I did
not and will not take. Re-measure before repeating any of the three numbers:

```bash
grep -c "corroborated_adult_exposures\|adult_rule_agrees\|adult_fold_journal" /opt/radd-stream/Fast_Fetch/fast_fetch.py
grep -n "return bool(row and row\[0\])" /opt/radd-stream/Fast_Fetch/redact.py
wc -l /opt/radd-stream/Fast_Fetch/viewer.py
systemctl show -p ExecStart,ActiveState,MainPID radd-stream.service
```

## 4 — Six files of App work existed nowhere but the deployment tree

While checking whether the live tree held stranded work, I found that it does — as
**uncommitted** edits. `FavoriteDao.recordAnswer` (one UPDATE that COALESCEs `is18Plus` so a
payload which never mentioned the flag cannot un-hide a flagged work) and
`FavoriteDao.favoriteIds`, plus the matching changes in `FavoritePost`, `FavoritesRepository`,
`CatalogRepository`, `MyListScreen`, and a `FavoritesSchemaGuardTest` extension. Not on any
remote, not in any commit, never seen by CI, and one `git checkout .` or `git reset` by another
lane away from destruction — the exact failure mode the "work in your own worktree" rule
exists to prevent, caught while it was still recoverable.

Preserved read-only as branch **`q4-fav-recheck-rescue`** at `583fd54`: 260 added lines,
**0 deleted**, verified purely-additive against `4a8c163` so it cannot revert anyone's App
work. **It is gated by nothing** — Kotlin has not been compiled, Gradle stays frozen — and it
is deliberately a branch, not trunk. Four sibling files in the same dirty tree
(`MyListViewModel`, `Models`, `AppDatabase`, `DetailViewModel`) mix additions with deletions
and were **not** included, because taking them would silently revert trunk's newer content;
their live copies are snapshotted at `/tmp/q1_rescue_app_20261031/` for the owning lane to
judge. I did not stage, commit, or reset anything inside `/opt/radd-stream`.

## 5 — Dispatches, corrected against measurement rather than passed through

- **qoder3** — the coins dispatch described code that is already on trunk (`engagement.py`
  owns `coin_ledger`, `streak_state`, `ad_cadence_state`, `CAPS_DEFAULT`/`CAP_MAX`,
  `REWARDED_DAILY_CAP = 10`, `coin_balance`, `grant_coins`, `spend_coins`, `redeem_pass`), and
  the branch it supposedly came from does not exist. Re-scoped to the only real gap: four
  `/api/v2/account/coins*` routes, account-scoped by bearer, integer rupees, replay-safe, one
  transaction per mutation, plus `test_coins_engine.py` and its CI step.
- **qoder4** — claim the rescue branch, compile and unit-test it in its own worktree, and
  state `q4-onboard-trial-ui`'s real status (never pushed).
- **qoder2** — the Hum TV crawl and the census numbers stay frozen above load 4; light
  prep and the queued command only.
- **qoder5** — write the production-staleness gap up as owner actions (this section), touching
  no service.

## Rules kept

No `.py` authored by me (reviewed and merged only), no service restart, no nginx change, no
tag, no commit or reset inside `/opt/radd-stream`, no `git add -A`, no credential in any URL,
argv, file or log (pushes used the temporary `mktemp` askpass helper, `chmod 700`, deleted in
the same command as the push), one local module at a time under `nice -n 19`, no Gradle, no
device claim, §13 hue untouched.
