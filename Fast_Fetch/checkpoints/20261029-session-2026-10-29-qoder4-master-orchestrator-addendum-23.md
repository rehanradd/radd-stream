# Session 2026-10-29 (qoder4 master orchestrator, addendum 23:10) — the memory incident I was mid-write when it happened `[Q4-MASTER]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (qoder4 master orchestrator, addendum 23:10) — the memory incident I was mid-write when it happened `[Q4-MASTER]`

The serving process went
5.38 -> 6.05 -> **6.66 GiB** RSS between two of my own samples (22:32-22:34), with 18 fds and 15
threads, while the box fell to **755 MiB MemAvailable** and swap 4.7/6.0 GiB. At **23:02:45** the unit
was restarted by someone (`NRestarts=0`, so manual, not the OOM path; no log attributes it, and an
interactive `agy` session has been open in a code-server terminal since ~21:47). RSS dropped to
0.05 GiB and available memory to 7.8 GiB. I did not restart it and I will not. Cause of the growth is
ours, not traffic: `/api/data` builds the whole 150,799-row ledger in the server heap and glibc
thread-arenas never return it; I also caught an in-process
`viewer.fetch_database_payload('', full=True)` as a child of that `agy` session at 22:34. Post-restart
measurements: `/api/v1/stats` 200 in **22.5 s** and `/api/v1/posts?limit=1` 200 in **20.3 s** (687 B,
`total 135731` — the adult-filtered count survived the restart). Delivered a fleet rule banning live
`/api/data` and `full=True` reads, banning `/api/v1/stats` polling, and requiring a report to me
instead of a restart. Full write-up in `docs/SESSION_CHECKPOINT.md`.

