# Contact form — public intake writes the panel's inbox (Muse, 2026-11-06)

## Done
- **Server (this branch):** NEW `contact_intake.py` — `POST /api/v1/contact`
  writes the panel's `contact_messages` table with the panel's own rules:
  category one of the panel's five (bug/payment/content/takedown/other),
  body non-empty and cut at 2000, subject cut at 200, the contact hint
  stored masked (first 2 + `***` + last 2, the panel's `mask_hint` copied),
  markup stripped and URLs replaced. A missing panel DB or table, or a
  locked write, answers "unavailable" (503, honest retry-later), never a
  swallowed message; nothing here raises. `viewer.py` answers the route
  ahead of the v2 dispatcher (a v1 route `api_v2` would 404), in the v1
  shape (`{"success": true}` / `invalid_params` 400 / `unavailable` 503).
  The write goes straight to the panel database because the panel's own
  `create_contact` needs an operator actor the public server cannot hold;
  the table is the only thing touched. The public gate's ordinary browse
  bucket applies — a per-IP daily cap is a follow-up if spam appears, and
  the panel's spam status is the triage. Tests: 8 new
  `test_contact_intake.py` cases, 8 OK locally; registered in backend-ci.yml.
- **App (this branch):** `ContactWire` (request/response), `RaddStreamApi`
  POST, `CatalogRepository.submitContact` (false on any failure, so the
  form keeps the text), `SettingsViewModel` `ContactUiState` + open/close/
  setters/submit (body required, no-server refusal, success closes and
  clears, failure keeps the text), `SettingsScreen` "Contact us" card +
  `ContactDialog` (5 category chips in a wrapping FlowRow — five do not
  fit one row on a narrow phone — subject, message, optional email, and the
  line that the email is stored shortened). No new strings.xml entries:
  Settings is hardcoded English like the rest of that screen, and the
  OnboardHonesty copy guard was checked by hand — the dialog's literals
  carry no banned word ("secure", "private", …) and sit after
  `ProfileLinkDialog`, inside its scanned scope, so the guard still sees
  its positive controls.

## Not done
- No push yet: CI runs 42144779319 + 42144779434 (step 19 fix + language
  defaults + tabs) are still in progress on this branch, and a push would
  cancel them. This commit lands after those runs finish.
- No local Gradle run — owner order is GitHub Actions only; CI judges.
- **Gate item:** nginx does not allow `/api/v1/contact` yet — like
  `/api/v2/play` (step 13), the route exists in code but the public edge
  403s it until the allow-list gains the path and the server deploys
  through the gate.
- Next one-by-one steps: Live control page, per-region sections +
  disclaimer versioning, P0 bug fixes, remaining ideas sweep,
  research-rule screens.
