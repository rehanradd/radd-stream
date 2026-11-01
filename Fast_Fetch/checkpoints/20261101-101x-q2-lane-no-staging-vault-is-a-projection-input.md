# 2026-11-01 10:1x — q2 lane `[Q2-NO-VAULT-IS-A-PROJECTION-INPUT]`

The free half of #18: run `price_projection.py`'s schema-only open over the census vault set —
`sqlite_master` + `PRAGMA table_info` + `EXPLAIN QUERY PLAN`, no content row, nothing written, which is
exactly what the 09:07 ruling admits. Cumulative time was under 0.1 s, so this is the cheapest possible
answer to a question the tree has been treating as expensive.

## The answer: no staging vault is a projection input

Of the 19 priced vaults, 5 could be opened and **none of the 5 is a Layer-0 ledger**:

    filmyhit.db          posts, releases, sitemap_cache, sources, sqlite_sequence
    hindilinks4u.db      (same five)
    kisskh.db            (same five)
    moviesmela.db        (same six: + taxonomy_cache)
    toonworld4all.db     (same five)

`project()` reads `posts`, `releases`, `download_sources`, `post_sources`. Every one of these vaults
carries **`sources`, not `download_sources`, and no `post_sources` at all** — so `price()` refuses them,
correctly: you cannot price a rebuild against a database that is not one of its inputs. The mapping is
`merge_catalogs.py`'s job, and it is the reason #18's "read-only rehearsal" cannot be done on staging
data: the only legitimate rehearsal target is a synthetic four-table ledger (which is what
`test_project_readonly.py` builds, and why 15 of its cases construct their own DDL), or the merged
catalog itself — which stays frozen.

Second shape finding: **`releases` has no `post_id` in three of the five** (filmyhit, kisskh,
moviesmela), while hindilinks4u and toonworld4all do. Two lanes wrote two different `releases` tables.
That is not a curiosity: it is the reason the projection would raise rather than run slowly on a
vault-as-ledger, and it is why `price()` now says so (below).

## The defect this pass found in the slice I pushed an hour earlier

The first pass died with `sqlite3.OperationalError: no such column: post_id`. `EXPLAIN QUERY PLAN`
**parses** the statement, so a plan request against a table lacking the join column raises — my own tool
crashed on the real population it was written to classify. `ec0431d`'s pricer therefore had a hole that
its synthetic fixtures could not see, because every fixture was built from `init_db`'s shape.

Fixed in the follow-up sha: a per-row lookup whose join column is absent is reported as `NO-COLUMN`
with the detail `no post_id column in releases`, the verdict becomes **does not fit** (the projection
would raise here, not merely crawl), and the report names it under "lookups that cannot be planned". Any
other `OperationalError` from the planner is recorded as `UNPLANNABLE` instead of ending the pass.
`test_price_projection.py` pins the behaviour with a four-table ledger built deliberately without
`releases.post_id`, and the scan-message it now shares with the older case is asserted unchanged.

## 14 of 19 vaults are barred by the sidecar rule as written — and the rule needs a ruling

The pass skipped 14 vaults because a `-wal` and a `-shm` sit beside them, which is what 09:07 says to
abort on. What the directory actually holds:

    18 × *.db-wal   every one 0 bytes
    18 × *.db-shm   32,768 B each
     0 × *.db-journal
     fuser on 10xflix / 7starhd / 9xmovies / world4ufree / vegamovies → no process holds any of them
     wal mtimes: 04:51:10 → 04:51:59 local (1793490670 → 1793490719) — 49 s across 18 files,
     ~5 h 20 m before this pass

A 0-byte WAL has **no un-checkpointed frames**: nothing is waiting to be recovered, nothing is lost by
not reading through it. A `-shm` with no holder and no journal is debris from a process that exited
without closing cleanly — some lane opened these read-write in sequence ~50 s apart and died or was
killed. So the rule, taken literally, bars **74% of the census forever**: the debris will not go away on
its own, and the next lane to apply the rule will abort on the same files and report `complete: false`.

**I did not relax the rule and I did not delete anything.** Two reasons, and they are the same reason:
the ruling is the supervisor's, not mine, and a `-wal`/`-shm` pair is another process's artifact —
removing it to make my own report come out green is precisely the failure mode the rule exists to catch.
What is being asked for is a ruling with three classes instead of one:

* `-journal` present → hard abort (a hot journal means an interrupted transaction, and a read-only
  open of that database fails anyway);
* `-wal` **non-empty** → hard abort (un-checkpointed content, someone is mid-write);
* `-wal` 0 bytes **and** `-shm` with no holder and no journal → name it in the report, proceed
  read-only, and never delete. A `mode=ro` open cannot checkpoint, so it cannot disturb even the debris.

Until that ruling lands, #37's honest status is **unrunnable as instrumented**, and that is a fact about
the instrument, not about the vaults. The sidecar check can be re-run by anyone in a second with the
`ls`/`fuser` pair above; no database is opened to answer it.

## Do not re-derive

- A staging vault is `posts`+`releases`+`sources`+`sitemap_cache`; a projection input is
  `posts`+`releases`+`download_sources`+`post_sources`. Those are different shapes, so "rehearse the
  rebuild on a vault" is not a slower plan, it is a plan that does not type-check.
- `EXPLAIN QUERY PLAN` parses, so it validates column existence — useful as a schema check, and it
  raises on a schema that is not there.
- Three vaults (`filmyhit`, `kisskh`, `moviesmela`) have a `releases` table without `post_id`; two
  (`hindilinks4u`, `toonworld4all`) have one with it. Any merge that assumes one shape is wrong for the
  other half of the set.
