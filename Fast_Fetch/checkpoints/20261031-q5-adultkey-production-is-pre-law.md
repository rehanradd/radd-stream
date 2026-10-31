# 2026-10-31 — the running service is pre-law: trunk carries the adult reconciliation, production does not

Branch `q5-adultkey-prod-gap`, from trunk `4a8c163`. **Docs only:** this lane read nothing
under `/opt/radd-stream` and ran none of the commands below.

## The gap, as measured by qoder1 on 2026-10-31 (quoted, not re-run here)

The adult law is code-complete on trunk and absent from the running service:

| probe | trunk `4a8c163` | live `/opt/radd-stream` |
|---|---|---|
| checkout | merged as `4a8c163`; hosted run `41156831610`, **39/39 steps success**, incl. step 16 `test_merge_catalogs.py` | checked out at `bf9e565` |
| `grep -c corroborated_adult_exposures Fast_Fetch/fast_fetch.py` | nonzero — the fold, journal and undo live here | **0** |
| `wc -l Fast_Fetch/viewer.py` | 4,042 | 3,576 |
| `redact.link_is_adult` | refuses a missing row (`if row is None or row[0]: return True`) | `redact.py:1097` still `return bool(row and row[0])` — fail-open |

### What that means on the host that is serving users

- `/api/v1/stream` and `/api/v1/download` do **not** refuse an unknown link id at the adult
  gate; only `resolve_live_source`'s 404 `no_playable_source` stops a typo. The fail-closed
  behaviour accepted on trunk is not live.
- The merge-time corroborated fold, `adult_fold_journal`, and
  `backfill_adult_key.py --audit/--corroborate/--undo` do not exist in the deployed tree, so
  no merge run from that tree can reconcile a twin.
- **Deploying trunk does not, by itself, hide anything.** The fold runs at the next merge, and
  the catalog-wide pass is an explicit owner action: `--audit` first, `--corroborate --apply`
  only behind the owner's go (the shipped equivalent of the brief's `--owner-go`).

Why the checkout is the running code: the unit's `WorkingDirectory=/opt/radd-stream` and
`ExecStart=/usr/bin/python3 -S /opt/radd-stream/Fast_Fetch/fast_fetch.py serve` (root
`AGENTS.md`), so production is whatever that tree holds. The tree also carries other lanes'
uncommitted work; it is not a workspace.

## Queued owner actions — exact commands

No agent restarts the service, deploys, or commits from `/opt/radd-stream`. Run the re-measures
read-only, in a quiet window (`awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo` ≥ 1500 MB
and 1-min load under 4):

```bash
# A. What production is actually running — read-only
git -C /opt/radd-stream rev-parse HEAD                                   # measured 2026-10-31: bf9e565
git -C /opt/radd-stream log --oneline -1
git -C /opt/radd-stream status --porcelain | wc -l                       # the tree carries other lanes' work
systemctl show radd-stream -p WorkingDirectory -p ExecStart -p MainPID -p ActiveEnterTimestamp

# B. Is the law in the deployed code? — read-only
grep -c corroborated_adult_exposures /opt/radd-stream/Fast_Fetch/fast_fetch.py   # measured: 0
grep -n 'bool(row and row\[0\])' /opt/radd-stream/Fast_Fetch/redact.py           # measured: 1097
wc -l /opt/radd-stream/Fast_Fetch/viewer.py                                      # measured: 3576

# C. The same probes against trunk, without checking anything out
git -C <clean-worktree> fetch origin main
git -C <clean-worktree> rev-parse origin/main                          # 4a8c163d97b0…
git -C <clean-worktree> show origin/main:Fast_Fetch/fast_fetch.py | grep -c corroborated_adult_exposures   # nonzero
git -C <clean-worktree> show origin/main:Fast_Fetch/viewer.py | wc -l  # 4042
git -C <clean-worktree> show origin/main:Fast_Fetch/redact.py | grep -n "row is None or row\[0\]"

# D. After an owner-run deploy through the normal release path (never a copy of WIP code)
git -C /opt/radd-stream rev-parse HEAD          # must be the deployed sha, not bf9e565
grep -c corroborated_adult_exposures /opt/radd-stream/Fast_Fetch/fast_fetch.py   # must be nonzero
systemctl show radd-stream -p MainPID -p ActiveEnterTimestamp                    # PID/start time must move
```

D's last line is the load check: new bytes on disk are not new code in memory until the
process has started after the deploy — and starting or restarting `radd-stream.service` is the
owner's action alone. `<clean-worktree>` means any worktree that is not `/opt/radd-stream`;
`/tmp/q5_adultkey` is on this docs branch off `4a8c163` and works.

The data pass, once deployed (heavy: one full ledger read, measured 150,799 rows / 16.3 s on
this box; still load-gated):

```bash
python3 -S Fast_Fetch/backfill_adult_key.py <catalog.db> --audit             # read-only provenance split
python3 -S Fast_Fetch/backfill_adult_key.py <catalog.db> --corroborate       # report only
python3 -S Fast_Fetch/backfill_adult_key.py <catalog.db> --corroborate --apply   # write: owner's go only
python3 -S Fast_Fetch/backfill_adult_key.py <catalog.db> --undo              # reverse this pass's flips
```

## Boundaries

- No production read was performed by this lane; every number above is qoder1's 2026-10-31
  measurement, quoted.
- The residual is unchanged in data: the 2,600-key / 3,486-row twin exposure measured
  2026-10-29 stays until the fold runs against the ledger — at a merge from deployed code, or
  via the owner's `--corroborate --apply`.
- `/opt/radd-stream` is the live deployment tree: do not commit from it, reset it, or clean it.
