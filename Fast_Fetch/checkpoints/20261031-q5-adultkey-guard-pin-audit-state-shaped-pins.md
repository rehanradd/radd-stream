# 2026-10-31 — pin audit: every docs-guard pin that quotes state instead of law

Branch `q5-adultkey-pin-audit`, from trunk `cc5f393`. Prompted by the two guard defects the
supervisor found: a pin written without backticks (unmatchable under `flat()`), and a pin that
held the truthful correction out by quoting `currently absent`. The rule this audit applies:

> **A pin must quote a law — a rule that must stay true — never a date-stamped status.**

Audited `Fast_Fetch/test_docs_invariants.py` at `cc5f393`: 18 tests, **18 OK** (run here,
`nice -n 19`, 22.0 s wall at load ~6 — markdown only). Read-only audit; **no pin was changed**.

## A. State-shaped pins in auto-loaded / live docs — the real list

| # | pin label | file | quoted string | why it is state, not law |
|---|---|---|---|---|
| 1 | `measured: secrets list is empty` | root `AGENTS.md` | `{"total_count": 0, "secrets": []}` | Exact JSON of a 2026-10-29 measurement, inside a paragraph the file itself labels **HISTORICAL, superseded**. A truthful retirement of that paragraph turns the guard red — the same class as `currently absent`. |
| 2 | `release died at the signing preflight` | root `AGENTS.md` | `it died at the `🗝️ Verify signing secrets are present` preflight` | A past run's outcome. History is load-bearing only while nobody corrects it. |
| 3 | `debug APK needs no secret` | root `AGENTS.md` | `uploads a **debug APK** on every green run` | Workflow behaviour snapshot; false the day the upload step is renamed or removed. |
| 4 | `no signed artifact has ever been produced` | root `AGENTS.md` | `No signed APK or AAB has ever existed for this product` | An **event-expiring fact**, not a rule: the first published signed artifact makes it false while the law (prove an artifact before claiming one) still holds. Needs a named retire trigger. Added by the supervisor at `cc5f393`; reported, not changed. |
| 5 | `one vCPU` | root `AGENTS.md` | `**This host has ONE vCPU** (`nproc` = 1)` | Host property; it is scoped "measured on this box" but pinned as fleet law. |
| 6 | `rule 7 carries its measurement` | root `AGENTS.md` | `266.312 s` | One timing sample, re-measured routinely; the law is the sentence around it, already pinned separately. |
| 7 | `rule 7 names the hosted verdict` | root `AGENTS.md` | `1 s on the hosted runner` | Same: a sample, not a rule. |
| 8 | `the filter shape is measured, never assumed` | root `AGENTS.md` | `` `paths: ["Fast_Fetch/**", ".github/workflows/backend-ci.yml"]` `` | The file explicitly says "the rule is the method, not the shape" and that a quoted shape could not be reproduced. Adding a path to CI (a truthful edit) breaks the guard. |
| 9 | `backend is the running system` | root `AGENTS.md` | `The backend is **already deployed there and is the running system**` | Deployment status, dated; changes the moment the host is stopped or redeployed. |
| 10 | `nginx allow-lists the public routes` | root `AGENTS.md` | `nginx allow-lists only `/api/v1/posts`, `/api/v1/stream`, `/api/v1/stats`` | Config snapshot; the allow-list has already grown (v2 account routes, `/download/`). The law is "nginx allow-lists only the public routes". |
| 11 | `the named hole: 442 keys / 455 rows` | root `AGENTS.md` | `442 keys held both, and 455 unflagged twins were reachable` | Measurement of the *pre-reconciliation* catalog, kept as the named hole's history; superseded numbers follow two lines later. |
| 12 | `residual measure under the correct identity` | root `AGENTS.md` | `2,600 keys … 3,486 … 69,773-row re-key blast radius` | Dated measurement (2026-10-29). The same section says this evidence moved to `docs/SPEC_ADULT_FLAG_EVIDENCE.md`; a re-measurement (which the doc requires) breaks the pin. |
| 13 | `MovieBox is metadata + trailer evidence, not playable` | `Fast_Fetch/SITES.md` | `**metadata + trailer-evidence** source, not a` | A site-capability status; true until a playable print is imported. |
| 14 | `no playable print is resolvable from this host` | `Fast_Fetch/SITES.md` | `no playable print is resolvable from this host` | Status that the fleet's own work is trying to change. |

## B. Archive pins — state-shaped but acceptable by design

`INVARIANTS` lines ~238-274 and `ABSORBED` pin dated narrative inside
`Fast_Fetch/checkpoints/**` and `docs/checkpoints/**` (`today`, `Load was 7.01 (gate 5.5)`,
`85 behind / 2 ahead`, `44 posts / 0 releases / 0 sources`, `now prefers the API`). These are
**conservation** pins, not law pins: the archives are append-only, so a pinned status cannot be
truthfully edited out from under the guard. The rule they defend is "nothing was deleted". Keep
them; the hazard is only a lane editing an archive in place.

## C. Structural pins that look numeric but are self-correcting

`N session files` / `N files cover` are compared to the directory listing, not hard-coded;
byte ceilings and `>= 10` / `>= 20` file counts are bounds. Not state claims.

## D. Suggested law-shaped replacements (not applied)

- 1, 2 → pin the law the history supports: "do not re-quote it as a live blocker" (1) and
  "That preflight is why exercising this is safe" (2); or move both into the historical
  checkpoint and pin only "Do not generate a replacement keystore to work around it"
  (already pinned).
- 3 → pin `the debug build needs no secrets` (a requirement), not the upload step.
- 4 → keep, with a retire trigger recorded next to it: the first published signed artifact
  replaces it with "release artifacts are published at …/releases".
- 5-7 → pin the rule already in the file ("never exclude one on this box's timing");
  drop the samples, or label them `measured-once` and pin their surrounding law.
- 8 → the law is already pinned ("read the workflow's own trigger block"); drop the literal
  `paths:` string.
- 9 → pin "never copy untested or WIP code onto it" / "do not treat it as hypothetical".
- 10 → pin "nginx allow-lists only the public routes" without the enumerated list.
- 11-12 → pin "That is fixed here, not by adding another `WHERE` clause" (already pinned) and
  "re-measuring must report both"; move the numbers to the SPEC receipts the file names.
- 13-14 → pin the SITES rule "a vault stays a FAIL until some surface publishes a playable URL"
  (already pinned from the q2 checkpoint), not the current absence of a print.

Nothing here was re-pinned: the guard is the supervisor's surface this turn. The list is the
deliverable, and each item names the law to pin instead.

## E. Push status — blocked, recorded not worked around

`git push origin q5-adultkey-pin-audit` failed `Invalid username or token`; the same
`GITHUB_TOKEN` answers **401** on `GET /user` (read-only one-request check, value never printed).
No other credential exists on this box (`gh` absent, no credential helper, no `~/.git-credentials`).
The branch is committed locally (`6a36a86` here, plus this note) and unpushed; the next lane with a
live credential pushes it unchanged. Nothing was force-pushed or rerouted through an API uploader.
