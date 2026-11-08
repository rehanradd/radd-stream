# Session 119 — D2.5 live-path follow-ups 1 + 2 (2026-11-09, ~02:4x PKT)

Base: `dd2663ee` (Session 112 landing, live). Branch: `session119-d25-followups`.
Read-only probe report that drove this work:
`hidden_files/d25-live-path-probe-20261109.md` (own-path 53/120 v1 vs
54/120 v2 — the 112 branches never executed for these URLs).

## What was wrong (probe-proven)

1. pkembed/mxdrop: unwrappers HEALTHY (direct calls 206 video/mp4) but
   the Stage-2 gate killed the proven link — those branches did not set
   `_gate_from_verdict`, so the resolver re-probed the fresh URL bare
   (bare `Mozilla/5.0` UA) and vkpluscdn plus2 / mxcontent 403'd it.
2. filmu/cineverse: Stage-1 `vidly`/`modiplay` fails, but `stage1_tried`
   blocked the legacy branches, so the working 112 `unwrap_filmu`
   (10/15 direct) / `unwrap_cineverse` (8/15 direct) branches were dead
   code for these URLs.

## Fix 1 — gate from verdict on both branches (`fast_fetch.py`)

Set `_gate_from_verdict = True` in the mxdrop and pkembed branches (the
pattern 12 other branches already use): the unwrapper's own verified
Range probe IS the gate evidence. No unwrapper change.

## Fix 2 — Stage-1 failure falls through (`fast_fetch.py`)

New `_stage1_failed` flag: set when Stage-1 ran and returned not-ok.
`if stage1_tried and not _stage1_failed: pass` replaces the old blanket
`if stage1_tried: pass`, so a Stage-1 FAILURE falls into the legacy
chain (filmu/cineverse/vidbolt/vibuxer/vidrift/iqsmart branches), while a
Stage-1 SUCCESS, a negative-cache hit, and a Stage-1 raise still skip it
(the sibling ladder below still runs if the fall-through also fails).
The stale comment claiming a failure "must NOT fall through" is updated.

## RESOLVER_VERSION 2 → 3

The fix changes what the resolver does with a row, so v2 failure records
written under the broken gate/dispatcher are stale and the rows deserve
one fresh press (Session 107 design; 112 precedent). No test pins the
number literally — all uses are symbolic. The 113 negative-cache check
reads the version at call time, so it keeps working.

## UA decision — NOT changed

`current_hosts.USER_AGENT` stays bare `Mozilla/5.0`. Reasons: the
`_gate_from_verdict` fix makes the UA irrelevant for pkembed/mxdrop (no
bare re-probe happens at all); the UA is shared by every Stage-1 probe
and no test pins its value, so a global change is unproven scope creep.
If a future host needs it, that is a dedicated probe, not this session.

## Re-measurement (live, same 15 newest rows/host, own-path only, no failover)

Method: fresh snapshot `/tmp/d25-probe-119.db` (sqlite3 .backup of the
live catalog 02:22 PKT; failure records for the 60 sample rows cleared
in the snapshot ONLY, live DB untouched), Session 119 tree copied to the
VM, script `hidden_files/d25-119-reprobe.py`, log
`hidden_files/d25-live-119.log`.

| host | probe v1 | probe v2 (112) | Session 119 | expected |
|---|---|---|---|---|
| pkembed | 2/15 | 2/15 | **15/15** | ~15/15 |
| mxdrop | 0/15 | 0/15 | **11/15** | 11–15/15 |
| filmu | 0/15 | 0/15 | **10/15** | ~10/15 |
| cineverse | 6/15 | 6/15 | **14/15** | ~14/15 |

50/60 own-path, up from 8/60. Remaining dead are dead files, not
resolver gaps: mxdrop's 4 (4570820/4570812/4570796/4570792, ~1 s each)
match the lane's 4 deleted-file pages; filmu's 5 match its direct
diagnostic (10 active / 1 error / 3 dead / 1 blocked); cineverse's 1
(4348046) is the row the 01:41 press only reached via failover siblings.

## Tests — 6 new in `test_database.py` (suite 208 → 214)

- pkembed/mxdrop serve even when `_stage2_probe` is stubbed to fail
  (gate-from-verdict pins).
- filmu/cineverse fall through when Stage-1 vidly/modiplay fails
  (stubbed `classify_backend` + failing `resolve_copy`).
- Stage-1 success never calls the legacy branch (negative control).
- A fresh negative-cache record keeps the row off the legacy branches
  (no re-unwrap, no Stage-1 re-probe).
Negative control: the 4 positive tests FAIL on the base tree
(`no_playable_source`) — verified via `git stash` on `fast_fetch.py`.

## Gate

- Full gate on the pre-bump tree: FAILED MODULES: 1 — `test_redact.py`
  only. The errors are the documented load flake (`PublicEdgeHttpTests`
  local-server 10 s timeouts; load 3–4; 3 errors, then 0, then 1, then 3
  across runs on the SAME tree; the set matches the 116 base-tree flake
  in AGENTS.md). No timeout or code was touched for it.
- Solos on the final (bumped) tree: `test_database` 214 OK,
  `test_api_v2` 64 OK, 4 importer modules OK.
- Final full gate on the bumped tree: FAILED MODULES: 0 (re-run at load
  0.53 — the earlier test_redact failure was the documented load flake,
  gone at low load). Importer modules solo OK.

## Not done here

- vidrift: no resolver fix exists (host-side no-streams). Untouched,
  no weight change (probe follow-up 3, stands).
- Nothing is live or deployed — the parent gates that. A deploy needs
  its own backup + live test; the v2→v3 bump starts a fresh re-probe
  wave (all v2 failure records go stale by design).
