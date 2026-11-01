# Session 2026-11-02 — q9 supervisor lane `[Q9-AUDIT-SIGNING-SECRET]`: audit critical 4 — signing secret fallback retired, signing fails closed

Branch `q9-audit-signing-secret-20261101`, worktree `/tmp/q9_secret` only; live tree `/opt/radd-stream` untouched.

- `redact.stream_secret` (Fast_Fetch/redact.py) no longer returns the hardcoded
  `"radd-stream-dev-secret-unconfigured"` at any of its three fallback sites. Order: env
  `RADD_STREAM_SECRET` → random 32-byte key generated and persisted in `server_state`
  (catalog file and parent dir created at first install) → `RuntimeError` when neither is
  possible. No secret value appears in error text; nothing logs it.
- `viewer.signing_secret` delegates fail-closed and never caches a failed lookup.
- `test_redact.py`: 4 new tests pin the fail-closed raise, env precedence, random
  per-install generation/persistence (no collisions), and the no-cache-on-failure rule.
- Fix commit `594d969` (base `b99814e`); re-merges of trunk: `0389747` (main `43513d9`),
  `a4bbbf4` (main `9074134`), this merge (main `723b504`).
- Hosted CI: Backend run `41339958991` (dispatch) and `41343438869` (push) success, all
  steps green incl. `test_docs_invariants`; Android run `41343560857` (dispatch) success,
  14/14 steps green, at tip `a4bbbf4`.
- Pre-existing, not this lane: two admin-gate 401 failures in `test_download_endpoint.py`
  reproduce on untouched base commits; that module is not in the CI gate list.
