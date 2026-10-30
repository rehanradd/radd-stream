# 2026-10-27 — Session: the Android client finally speaks to the payment ledger (Qoder)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-27 — Session: the Android client finally speaks to the payment ledger (Qoder)

Backend files were not modified this session; the ledger shipped earlier. Recorded here because
three findings about the *running* server were settled, and because the client is half of this
feature's contract.

- **Live routes confirmed against the deployed process** (`127.0.0.1:8080`, zero writes):
  `POST /api/v2/account/payment` and `GET /api/v2/account/entitlement` both answer
  `401 unauthorised` with no bearer and a well-formed body, and `404 not_found` for a bearer the
  server does not know. So `viewer.py` reading the body before dispatch (`viewer.py:3298-3310`)
  is uniform across every account route — the earlier "is the payment route checked before
  authentication?" worry was not a bug, and the app's verdict table
  (`SyncContract.verdictOf`: 401 → SIGN_OUT, `404 && !hadWorkRef` → SIGN_OUT) is correct for a
  revoked or pruned key: the device signs itself out instead of showing a stale VIP.
- **Admin token rotation verified by hash only.** `RADD_ADMIN_TOKEN` in the service environment is
  a 64-character secret and does not match the 22-character token that `Fast_Fetch/CONTINUITY.md`
  and `Fast_Fetch/CHAT_HISTORY.md` had been publishing in prose (5 occurrences). The documented
  value is therefore dead, but it should not sit in the tree: both files now carry a redaction
  placeholder. Git history still contains it — rewriting history is the owner's decision, not an
  agent's.
- **Client side landed:** `POST` carries `{"plan","method","tid"}` and the entitlement read is
  polled at launch and every 6 h. `docs/FULL_MASTER_FEATURE_INVENTORY.md` M-MON-01 is marked built
  except its quality clause: remote config publishes no quality flag, so the client did not invent
  one — M-MON-05's server-side `max_quality` in the PlayBundle is the real prerequisite.

**Checks:** `python3 -S Fast_Fetch/test_database.py` and `test_vidout.py` unchanged (no backend
edit); Android `:app:compileDebugKotlin :app:testDebugUnitTest` green — see `App/AGENTS.md`
Session 13 for the counts.

---

