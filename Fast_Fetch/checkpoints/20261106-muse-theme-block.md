# 20261106-muse-theme-block — panel theme controls, server theme, app applies it

**Agent:** Muse (BoNzoO), coded directly on the user's order (audit + complete
everything one by one, 01:00 PKT 2026-11-06). No qoder lane. Branch
`muse/app-panel-connection-20261106` (same branch as the panel feed).

## What was built

**Panel (admin-v2 workspace, not this repo) — the bug first:**
- `_seed` in `admin_v2/store.py` unconditionally UPDATEed every tuning
  column to defaults on every panel start — every restart wiped all operator
  tuning. Fixed: defaults are seeded ONLY where the column is still NULL. A
  fresh row gets all defaults, an existing row keeps its values, a newly
  added column gets just its own default. Dead `cols`/`placeholders` vars
  removed; TEXT column rule extended to the theme keys
  (`TUNING_TEXT_COLUMNS`).
- New tuning keys: `theme_mode` "dark", `theme_accent` "", `theme_dynamic_color`
  0, `theme_hero_autoplay` 1, `theme_hero_interval_s` 5. `hero_max` default
  3 → 6 (the shipped 6-slide hero), bounds (0,5) → (0,6).
- `services.py`: bounds for the new integer keys; `put_tuning` validates
  mode ∈ {dark, light, system} and accent empty-or-#RRGGBB; `tuning_consumers`
  labels the 5 theme keys + hero_max "remote-config (app reads it)" (13 of
  20 controls still stored-only, honestly labelled).
- Tests: 4 new in `tests/test_unit.py` (defaults, validation, seed preserves
  operator tuning on re-seed, seed fills a NULL new column only) + 2
  assertions in `tests/test_live_real.py`. Suite: **126 tests OK**,
  orphan audit 0.

**Server (this repo):**
- `Fast_Fetch/panel_feed.py`: new `read_theme()` — tuning_settings from the
  panel DB, mode=ro, never raises; missing DB/table/row/column → defaults;
  out-of-range value → its own default. Defaults: dark, accent "", dynamic
  off, autoplay on, interval 5, hero_max 6.
- `Fast_Fetch/viewer.py`: remote-config merges `theme` next to
  sections/broadcasts/hidden_work_ids (always present).
- Tests: 3 new in `test_panel_feed.py` (operator values, defaults when
  nothing set, invalid values fall back per-field). Suite: **18 tests OK**.
  Also green: test_docs_invariants 74, test_redact, test_catalog_api 127.

**App (this repo):**
- `VipRemoteConfig` gains `theme: PanelTheme` (mode/accent/dynamicColor/
  heroAutoplay/heroIntervalS/heroMax, all defaulted) + 3 decode tests.
- `ServerSettingsRepository`: `themeSettings` Flow + `saveTheme()` (DataStore);
  `RemoteConfigWatcher` saves the theme on a successful poll only — a failed
  poll keeps the last good theme, like the switches.
- `MainActivity`: resolves darkTheme from the stored mode (dark→true,
  light→false, system→system setting) via pure `resolveThemeDark`;
  dynamic colour = stored && Brand.allowed && panel permission;
  accent parsed by pure `parseAccentHex` ("" → null, bad hex → null).
  Root Surface now uses `colorScheme.background`, not the hard-painted dark.
- `Theme.kt`: `RaddStreamTheme` gains `accent: Color?` — repaints `primary`
  roles only (primaryContainer mixed, onPrimary by luminance); semantic
  Radd* tokens untouched.
- Light migration: NavGraph (Scaffold, NavigationBar, selected/unselected/
  indicator colours) and SetupScreen (background, texts, message colours,
  button container + contentColor — also fixes the button-label contrast
  finding) now use `colorScheme` roles; no legacy dark alias remains in the
  three files. `brand.properties`: `features.light_scheme` false → true.
- Hero: `HeroCarousel` takes `autoplay` + `intervalMs`; `HomeScreen` takes
  `heroMax`/`heroAutoplay`/`heroIntervalMs` from the NavGraph theme;
  heroMax 0 hides the slot entirely (no skeleton).
- Tests: new `ThemeResolutionTest` (9 cases: modes, system follow, unknown
  → dark, accent parse valid/invalid).

## Not done
- No local Gradle run — owner order is GitHub Actions only; CI judges.
- Panel workspace changes are NOT in this repo: they must be posted to the
  VM panel workspace and the panel server restarted (correct six env vars,
  exact PID) before theme control works end-to-end. The live panel DB has no
  theme columns yet; `read_theme` defaults cover it until then.
- No live deploy of this branch (gate path + `RADD_ADMIN_V2_DB` env).
- Next one-by-one steps: tabs control, contact form, Live control page,
  per-region sections + disclaimer versioning, P0 bug fixes (heal shape,
  HLS download), remaining ideas sweep, research-rule screens.

## Addendum — Android CI failure on 76f7ef4, fixed
- Backend CI GREEN (run 42102651068). Android CI FAILED (run 42102651008,
  step 7): `compileDebugKotlin` — `Theme.kt:222:36 Unresolved reference
  'luminance'`. `Color.luminance()` is not a member in this Compose version;
  the codebase already owns the WCAG formula as a private helper in
  ArtworkAccent.kt.
- Fix (separate commit): ArtworkAccent's `luminance` is now `internal` and
  shared; `accentOnPrimary(accent)` is a pure function in ThemeResolution.kt
  (same 0.5 rule); Theme.kt calls it. Two new ThemeResolutionTest cases
  (jade/black -> white ink, white/cream -> dark ink; values checked against
  an independent WCAG computation: jade 0.437, cream 0.802). Test count 9 -> 11.
- Heal fix (separate commit, same push): `/api/heal` for a missing post now
  answers 404 `{"success": false, "error": "Post not found"}` instead of
  success:true + error; new test; test_operator_isolation 41 OK.
