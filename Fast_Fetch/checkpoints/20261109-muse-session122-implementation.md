# Session 122 — implementation: cast, search finish, disclaimer, force-update, remote-config, anti-cheat

Date: 2026-11-09 ~05:51–06:45 PKT. Base: main @ 923656a (CI green; gate-deployed live 06:24 PKT,
tree now @ 923656a, PID 1303681). Branch: session122-implementation. No push (parent pushes +
runs CI), no live-tree touch, no local Gradle by owner order — Android CI judges.
Diff: 41 files (35 modified + 6 new), +1734/−283.

## Cast + actor search (user directive 05:57 PKT, overrides "no cast in app")
- Measured first: merged catalog `posts` has NO cast column. Staging DBs do: 10xflix
  13,516/13,775 rows (98%), 9xmovies 7,171/12,060 (59%), desicinemas 11/5,223 (0.2%).
  ~31,000 catalog posts touch a cast site (~20%); ~20,500 could show cast (~14%)
  after backfill. Quality is rough: comma lists AND space-glued blobs ("Mark Hamill
  Harrison Ford Carrie Fisher"), synopsis fragments, prefix junk.
- Backend: `fast_fetch.py` `posts.cast_names TEXT` + migration + save (non-empty wins,
  never blanks); `merge_catalogs.py` collects it; `redact.py` `post_detail` view only
  (never list rows); `viewer.py` q + fuzzy search match `cast_names` (fuzzy params
  `params[3:]` → `params[4:]`); new `backfill_cast.py` (report by default, `--apply`
  writes, `--site` filter, joins via `post_sources` page URL, never overwrites;
  report mode must `rollback()` — `sqlite3.connect` commits on exit).
- App: `PostDetail.castNames`, `parseCastNames` (comma split; comma-less ≤3 words is
  one name, longer is glued → no cast; drops >4-word chunks, non-capitalised words
  except particles de/van/von/der/den/ten/ter/le/la/di/du/bin/bint/al/el/ap/ab/af,
  digits/illegal chars; dedupe; cap 12), `DetailScreen` CastSection (chips, first 6 +
  "and N more", tap → actor search via `Screen.Search.createRoute`), omnibox label
  "Search for a title or an actor". No cast data → no section, never invented.
  Tests: backfill 4/4; database 215 OK (skipped=1); redact 82; query-plan 7;
  search_fuzzy 8; work_ref 5; media_search 44; CastNamesTest 8 new.

## Search surface — finished (SE-1/3/4/5/7/8/9/10/11)
- Slim FilterRail (Type chips + Filters button; sheet owns Type/Industry/Genre/
  Quality/Plan/Sort/years); "Filtered" pill tappable, driven by `hasFacetFilters`
  (facets + years, never sort); DirectVideoRow one Play button; new PageLinkRow
  (page link → system browser via ACTION_VIEW, "No browser" note on failure);
  paste hint stays while the field holds a half-typed address and mentions page
  links; suggestions-unavailable note when the suggest call itself fails
  (`suggest()` now returns null vs empty); RecentsSection (lazy row + Clear)
  survives under a pasted link; results in LazyColumn (keyboard dismiss on
  scroll); group headers "N title(s)"; fuzzy line names the query + "Show exact
  matches only" (exact-only is the empty state — all rows are fuzzy when
  `fuzzy=true`) + "Show close matches" back. Server-side year filtering still open (needs an API param).

## Disclaimer (user directive 06:05 PKT #1; closes DC-1)
- Default text VERBATIM from `files/disclaimer-text-20261109.md`
  (`DEFAULT_DISCLAIMER_TEXT`, version 1, email radddao1@gmail.com) in
  `VipRemoteConfig.kt`; `PanelDisclaimer.effective()` resolves panel text when
  set, else the default, at read time (stored value stays the panel value).
  First run: Accept ("I understand") or Decline → Toast + `finish()`; Settings card always shows it
  ("No disclaimer published yet" gone); analytics dialog waits until the disclaimer is settled (no
  more stacking); seen-version read via a known-flag so an accepted viewer never sees a flash.

## Force-update + Play Core (directive #2)
- Gate + dialog already existed; missing piece was Play Core. Added
  `app-update` + `app-update-ktx` 2.1.0 (catalog + build.gradle.kts) and new
  `update/InAppUpdate.kt`: flexible for soft, immediate for forced, download
  page fallback on ANY Play failure (no Play, sideloaded build Play knows
  nothing about, not available). Flexible download auto-completes on
  DOWNLOADED (listener, unregistered in MainActivity.onDestroy); immediate
  resumes itself if backgrounded mid-flow; a failed flexible flow falls back
  to the download page; an immediate flow never dismisses its dialog (cancel
  → dialog still there). Dialog now shows the published size when set.
  Live path today is the download page: Play only knows Play-installed builds.
## Remote-config extension (directive #3) — DATA ONLY, never code
- Server side verified complete: `remote_config()` + viewer.py merge emit every key the app decodes
  (sections, broadcasts, hidden_work_ids, theme, tabs, disclaimer, free_quality_cap, min_version_code).
  Gaps found + filled: `apk_update_size_bytes` was emitted but undecodable → decoded, threaded
  through `AppUpdate`, shown in the dialog. `apk_update_sha256` deliberately NOT decoded: the app never holds the APK bytes (browser downloads them), so
  a digest it cannot check is a promise it cannot keep — and UPD-1b's "no
  digest, no banner" is NOT enforced, because it would silently kill the
  force-update card whenever the operator has not set a digest (owner call).
- Gaps NOT filled (owner/panel decisions, recorded): no `ads_enabled` server
  setting exists, so the watcher always saves ads off (matches the no-SDK
  state); `featureFlags.search`/`sharing` have no server knobs (always on);
  top-level `wallet`/`streak` are dead keys — the server publishes them only
  under `engagement.*` with different shapes, so the coin screens (when built)
  must decode `engagement.*`, not these; server-driven labels need a strings-map
  decision (Brand.copy keys stay app-side in brand.properties).
- Remote-config content is DATA ONLY (text, toggles, lists). Code hot-patching
  is against Play policy and a cracking hole; it stays out by design.

## Anti-cheat / coin safety (directive #4)
- New velocity guard in `engagement.grant_coins` (the single credit funnel):
  >20 credit grants in 600 s refuses with `VelocityLimitReached`, all reasons
  counted together (a script cannot farm around a per-reason cap by switching
  reasons); admin grants exempt; rewarded-ad daily cap (10/day) still binds
  first. A retry (duplicate idempotency key) now answers idempotent BEFORE any
  cap/velocity check, so a harmless retry is never a refusal (mirrors spends).
  Route edge maps it to 429 `rate_limited` + Retry-After 600 — a 500 would read
  as "try again" to a retrying client. Existing layers verified: no earning
  route takes an amount; share/finish-watch carry server-computed idempotency
  keys; finish-watch needs server-observed progress; trial mint capped at
  10/day per hashed IP. NOT built: device-level earnings velocity —
  `user_accounts` has no device column and `device_trials` covers trial
  accounts only, so it needs a schema change; full device attestation (Play
  Integrity) is the follow-up, not this session.
- Tests: engagement 38 OK (4 new velocity tests); coins_engine 82; accounts_api 38; admin_panel 107; docs_invariants OK.

## Pre-push Kotlin checks
- Import diff per edited file clean; every new import used; PlayArrow removed
  (unused); @Composable DetailScreen 15→16 (+CastSection), SearchScreen 7→9
  (+PageLinkRow, +RecentsSection); `/*` vs `*/` balanced in all edited files
  (DetailScreen 28/27 is the pre-existing `"video/*"` string literal);
  no new drawables. Disclaimer text verified byte-identical to the source file.

## Data gaps + what remains
- Cast: ~86% of titles still show no cast. Fill path: more importers extracting
  cast + `backfill_cast.py --apply` through the gate (target needs the column
  from the deployed code first). TMDb spine needs the owner's commercial-
  agreement decision. CastNames parser is defensive by design (glued blobs yield no cast, never wrong names).
- NOT done in this pass (audit is 157 issues; this session finished the cast
  slice, the search surface, disclaimer, force-update, remote-config, anti-
  cheat): worst-first SU-1 (dead server bricks app), VIP-4 ("Watch Ad" plays
  no ad), PL-1 (autoplay-next, no countdown/Cancel), DE-1 (Detail autoplay
  ignores Resume); missing screens (profile, dashboard, standalone check-in,
  coin balance/history); the rest of the audit surface by surface; the two
  design-reader summaries (benchmark §14/§15, video audit 52 issues) had not
  arrived when this checkpoint was written.
- Device verification owed: Play Core fallback (tap Update now on a sideloaded
  build → download page opens), disclaimer Decline exits, cast chips + actor
  search on a real title with cast data, velocity 429 on the wire.

## Parent fixups after CI (06:56 PKT 2026-11-09)

CI on 0f29a57 failed BOTH runs — two unrelated defects, neither a 122 code
regression:

1. **Android compile error (122's bug):** `HomeScreen.kt:125` used
   `ActivityResult.RESULT_IN_APP_UPDATE_FAILED`, but `androidx.activity.result.ActivityResult`
   has no such constant. The constant lives in Play Core itself:
   `com.google.android.play.core.install.model.ActivityResult` (proven by
   inspecting the app-update-2.1.0 AAR — it is the only class in the artifact
   carrying the name; the Android docs page writes it as
   `ActivityResult.RESULT_IN_APP_UPDATE_FAILED` without saying which
   ActivityResult). Fix: import it aliased as `PlayCoreActivityResult`, use
   `PlayCoreActivityResult.RESULT_IN_APP_UPDATE_FAILED`, and drop the now-unused
   `androidx.activity.result.ActivityResult` import.
2. **Backend test flake (pre-existing, Session 105's test, not 122):**
   `test_device_trials_and_webhook.py::test_no_account_response_carries_a_pin_a_digest_or_a_phone_of_someone_else`
   asserts the bare PIN `"4721"` never appears in a response body — but
   `vip_until` is a float timestamp, and at CI time it was `1794534721.0603328`,
   which contains `4721` as a substring. The test passed in the local gate
   (06:47) and failed on CI (06:52) on the clock alone. Fix: check the PIN
   quoted, as a JSON string value (`'"4721"'`) — a leaked PIN field would be a
   string value; a timestamp is a number. Test module re-run: 89 tests OK.
   122's diff to `accounts_api.py` is only the +9-line 429 mapping; the test
   file is untouched by 122 (last touched 42afbc0, Session 105).

Both fixes are in the second parent fixup commit on `session122-implementation`.
No local Gradle run (owner order) — Android CI is the compile check.

## Parent fixup 3 (07:02 PKT 2026-11-09) — second Android compile error

The self-check (07:00 PKT) read the 0f29a57 Android job log: there were TWO
compile errors, not one. Fixup 2 covered only the HomeScreen constant. The
second: `DetailScreen.kt:559 Unresolved reference 'onActorClick'`.

Root cause: `onActorClick` is a parameter of `DetailScreen` (line 129), but
line 559 sits inside the private `DetailContent` (line 422), whose parameter
list had no `onActorClick`, and the call site (line 271) did not pass one.
The builder wired `CastSection(cast, onActorClick)` inside DetailContent
without threading the callback through. Fix: add
`onActorClick: (String) -> Unit = {},` to DetailContent's params (next to
`onOpenVipUpgrade`, with the same KDoc wording as DetailScreen's) and pass
`onActorClick = onActorClick,` at the call site. NavGraph already passes the
real handler (line 358: `navigate(Screen.Search.createRoute(actor))`), so the
chain NavGraph → DetailScreen → DetailContent → CastSection is now complete;
a tap searches that actor's titles.

Pre-push checks: diff is exactly +3 lines, no deletions, no new imports;
@Composable 15 (base) → 16 (builder's CastSection; this fixup adds none);
comment balance 26/25 → 29/28, delta +3/+3 (two builder KDocs + this one),
the persistent 1-off is the pre-existing `"video/*"` string literal. No local
Gradle run (owner order) — Android CI is the compile check. Pushing this
fixup cancels the in-progress acebcde Android run (cancel-in-progress) and
starts a fresh run on the new SHA — intended, since acebcde was known to fail
on this error.

## Parent fixup 4 (07:14 PKT 2026-11-09) — BrandDriftTest brand-name failure

CI on 2003a93: Backend GREEN (run 42548927512, SUCCESS) — the quoted-PIN fix
works on CI. Android FAILED (run 42548927534, job 128939925170): the build now
COMPILES (both fixup 2/3 errors gone) but 1 of 1147 tests fails:
`BrandDriftTest.brandNameIsNeverHardcodedOutsideTheBrandFiles` (AssertionError
at BrandDriftTest.kt:106).

Root cause: the test scans single-line string literals in every Kotlin source
for the brand needles ("radd stream", "radd-stream", from brand.properties
identity.name / identity.name.short / server.project.name) and allows them
only in Brand.kt + RaddMark.kt (pending-migration list is empty — a ratchet).
Session 122's Decline Toast in MainActivity.kt:334 said "You need to accept
the disclaimer to use Radd Stream." — the one new offender. Proven by
replicating the test's exact scan locally (same regex, same needles):
offenders were exactly [MainActivity.kt]; the `"""` DEFAULT_DISCLAIMER_TEXT
block in VipRemoteConfig.kt is invisible to the scanner (its regex matches
single-line literals only) and is NOT an offender — do not touch it.

Fix: reword the Toast to "You need to accept the disclaimer to use the app."
— same meaning, no brand name, no need for Brand.name. Re-ran the replicated
scan: zero offenders. Raw-Color(0x) scan also clean (test 2's check). No test
pins the Toast text. Pre-push checks: diff is exactly 1 line, @Composable
0/0, comment balance 8/8, no import change. No local Gradle (owner order) —
Android CI is the verdict.

## Landed (07:27–07:29 PKT 2026-11-09)

- CI on 310dfb0: BOTH GREEN — Backend 42550060579 SUCCESS, Android
  42550060391 SUCCESS. APK app-debug-294 verified (artifact 13645500522,
  24,436,379 bytes, 510 entries, manifest present, zip intact) at
  ~/workspace/app-debug-294/app-debug.apk.
- Merged to main (fast-forward, no conflicts): main 923656a → 310dfb0,
  42 files +1835/−283. Pushed via bundle route; GitHub main @ 310dfb0a2c.
  VM clone /tmp/muse-panel-push main @ 310dfb0a2c (fast-forwarded via
  `git merge --ff-only origin/main` — the fetch-into-branch form refuses
  on the checked-out branch; that is the fix when the clone's checked-out
  branch is the target).
- Gate-deploy started: backup 0729 running (PID 1313557, script from
  backup-0549 with HHMM replaced; TS 20261109-0729). Next: verify backup
  (BACKUP-DONE + integrity ok/ok), live-tree ff, service restart, proofs.
  The rev-5 rebuild (PID 1304855) is still running on its own copy file —
  the gate does not touch it; the swap follows after both finish.
