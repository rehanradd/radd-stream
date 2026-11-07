# Session 95 — Disclaimer email, changeable from the admin panel (2026-11-07 ~19:30 PKT)

User order 18:52 PKT 2026-11-07: both the disclaimer email and the disclaimer
text must be changeable from the admin panel. The text already was (v2 tuning
`disclaimer_text`/`disclaimer_version`, wired to the app through
`panel_feed.read_disclaimer()` into remote-config). The email existed nowhere.
This session adds it end to end, defaulting to the address the user gave in
chat 18:43 PKT (radddao1@gmail.com).

## Panel half (workspace `admin-v2/`, deploys by tar + panel restart)

- `admin_v2/store.py`: `"disclaimer_email": "radddao1@gmail.com"` added to
  `TUNING_DEFAULTS`, and the key added to `TUNING_TEXT_COLUMNS`. The existing
  `migrate()` loop adds any missing `TUNING_DEFAULTS` column on panel start
  and seeds just that column's default where it is NULL — so the live panel
  DB gains the column on the next restart, existing rows keep their values,
  and an operator-set email is never wiped by a restart.
- `admin_v2/services.py`: `put_tuning` validates the email (≤254 chars, one
  `@`, no spaces, non-empty local part, dotted domain) and the key joins the
  text-keys tuple that skips the integer `TUNING_BOUNDS` check; the consumers
  map gains `"disclaimer_email": "remote-config (app reads it)"`.
  `get_tuning` returns the key automatically (it iterates `TUNING_DEFAULTS`),
  so the email is readable and writable through the existing
  GET/PUT `/admin/api/v2/tuning` — the tuning surface is API-only, there is
  no server-rendered field to add.
- `tests/test_unit.py`: `test_disclaimer_tuning_keys` extended — default is
  the operator address, a new address round-trips, six bad addresses are
  refused, consumers map entry asserted. Panel suite: **149 tests OK**.

## Server half (`panel_feed.py`, branch `disclaimer-email-20261107`)

- `read_disclaimer()` now returns `{"text", "version", "email"}`. The
  three-column SELECT falls back to the old two-column one, so a panel DB
  that predates the email column still answers its text and version (only
  the email comes back empty). A junk email in the DB is never published
  (same shape check as the panel, server-side).
- `viewer.py` needs no change: `payload["disclaimer"]` already carries the
  whole `read_disclaimer()` dict into remote-config.
- `test_panel_feed.py`: fixture tuning table gains the column + the operator
  address; the three existing disclaimer tests updated to the 3-key dict;
  two new tests — invalid email not published, old-panel fallback. **31
  tests OK.**

## App half

- `PanelDisclaimer` gains `val email: String = ""` (default keeps old
  bodies decoding). `ServerSettingsRepository` mirrors it in DataStore
  (`disclaimer_email` key) via the `disclaimer` Flow and `saveDisclaimer`.
- `DisclaimerDialog` shows a `Contact: <email>` line under the version,
  only when the email is non-blank — an empty email shows no contact line,
  never an invented address.
- `VipRemoteConfigTest`: fixture disclaimer gains the email, assertions for
  the published and the empty case.

## Checks

- Panel suite 149 OK (workspace). `test_panel_feed` 31 OK. Full backend
  gate: **49/49 modules PASS, FAILED MODULES: 0** (run-backend-gate.py,
  exit 0). Pre-push Kotlin checks vs `1b6f42ec`: no new imports in any
  edited Kotlin file (field/logic additions only), no `/*`/`*/` imbalance,
  no dropped imports. **CI verdict: PENDING — this commit, then CI judges.**

## Not done

- Push (this commit, then CI judges). Gate deploy of the server/app half
  (branch → live tree through the gate, same as the 19:10 live deploy) and
  the panel half (tar copy + panel restart, which runs `migrate()` and adds
  the column). Live verification after both: remote-config carries the
  email, panel PUT changes it, app dialog shows it. Device checks
  owner-only.
