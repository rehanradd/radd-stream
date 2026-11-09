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
