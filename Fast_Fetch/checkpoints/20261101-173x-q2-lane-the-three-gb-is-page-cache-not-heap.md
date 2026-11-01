# 2026-11-01 17:3x — q2 lane `[Q2-THREE-GB-IS-PAGE-CACHE-NOT-HEAP]`

Supervisor decision recorded up front: **the 1200 MB radd-cgroup floor stays exactly as written — I did
not reinterpret it and I did not run #18.** This checkpoint is the read-only cgroup finding the 17:31
gate sample turned up, filed so the ≤1200 MB clause is not silently re-litigated by the next lane.

## What I ran and what I did not

`systemctl show radd-stream -p MemoryCurrent`, `cat` of
`/sys/fs/cgroup/system.slice/radd-stream.service/{memory.current,memory.stat,memory.swap.current,memory.max,cgroup.procs}`,
`/proc/1835070/{status,smaps_rollup}`, a read-only `ls -l /proc/1835070/fd`, and `/proc/pressure/cpu`,
`/proc/loadavg`, `/proc/meminfo`. **No crawl, no merge, no production read or write, no test-module run,
no restart, no VM Gradle, no gate change, no floor change, no signal to or interaction with PID 1835070.**

## The finding: no process holds ~3 GB — reclaimable page cache does

`radd-stream.service` contains **exactly one PID: 1835070** =
`/usr/bin/python3 -S /opt/radd-stream/Fast_Fetch/fast_fetch.py serve --host 127.0.0.1 --port 8080`.
Its private footprint is small:

| instrument | value | meaning |
|---|---|---|
| `VmRSS` / `Pss` | 18,684 kB / 11,107 kB | resident |
| `Anonymous` (`/proc`) = `anon` (`memory.stat`) | 7,880,704 B ≈ **7.5 MB** | real process heap |
| `Swap` / `memory.swap.current` | 62,740 kB / 64,245,760 B ≈ **61 MB** | swapped-out, mostly heap |
| `kernel` + `slab` | ≈ 3.3 MB | negligible |
| **`file`** (`memory.stat`) | **1,559,805,952 B ≈ 1,487 MB** | page cache |
| ↳ `inactive_file` | 1,559,797,760 B | **~99 % of `file`, reclaimable** |
| `file_dirty` / `file_writeback` | 0 / 0 | nothing pending |
| `memory.max` | `max` | **no cgroup limit** |

So of `memory.current` ≈ 1,497 MB, only ~10 MB is non-reclaimable (anon+kernel+slab); **the other
~1,487 MB is file page cache the kernel charges to this cgroup**, and `memory.max` is unlimited, so it
is ordinary host cache, not a reservation.

**Whose cache it is:** PID 1835070 holds **20+ open FDs** on
`/home/ubuntu/radd-stream-data/merged_catalog_20261025.db` plus its `-wal` and `-shm` (WAL-mode SQLite).
Serving catalog reads pages that ~6.4 GB ledger; the reads are what fill `file`.

## Why it is cache and not a leak (evidence, not assertion)

1. **It fell on its own between two samples.** `systemctl … MemoryCurrent` read **3,263,451,136 B ≈
   3,112 MB** at 17:31; `memory.current` reads **1,569,751,040 B ≈ 1,497 MB** minutes later with no
   process action in between. A heap leak grows or holds; reclaimable cache shrinks under pressure.
2. **Reclaim/refill churn is in the counters:** `pgscan_kswapd 5,214,734`, `pgscan_direct 19,401`,
   `pgrefill 2,391,521`, `workingset_refault_file 3,779,238` — the signature of a large read working
   set cycling through page cache, not of accumulation.
3. `file_dirty 0`, `memory.max max` — no writeback pinning, no hard ceiling forcing the number.

I ran a `/proc/<pid>/maps` size rollup as a fourth probe and **discarded it**: busybox-awk overflowed the
64-bit address subtraction into negative sizes, and `maps` reports virtual address space, not resident
bytes, so it was the wrong instrument regardless. `memory.stat` + the FD listing are authoritative.

## The gate tension I am filing, not resolving

The 17:31 gate sample failed two hard floors: **SwapFree ≈ 278 MB** (floor ≥ 800 MB, host-wide, not
this cgroup) and **radd cgroup `MemoryCurrent` ≈ 3,112 MB** (floor ≤ 1,200 MB). This finding says the
second is measuring reclaimable page cache, i.e. the ≤1200 MB clause will read "FAIL" whenever the serve
process has recently paged the merged catalog, even though the real footprint is ~10 MB non-reclaimable
+ ~61 MB swap. **Supervisor ruling is that the floor stays as written and #18 is not run**, so I record
the tension and stop: the more genuine pressure signal in that sample is the host-wide **SwapFree ~278
MB**, which is a whole-machine condition and would bar #18 on its own. #18, #19, #21 and #24 stay
frozen on the production-read / crawl freeze; nothing here lifts a freeze.
