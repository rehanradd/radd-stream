# CACHE_SPEC — ahead-of-playback progressive cache (`data/cache`)

Owner-facing + cross-agent spec for the app's media cache. This is the differentiator: **the app
plays a title and simultaneously keeps downloading it**, so slow connections never stall, a
mid-playback "keep this" continues from the bytes already buffered (**never re-downloads from 0**),
and purely-automatic preview files auto-delete after a user-chosen 3 or 6 hours. Every rule below is
implemented in `app/src/main/kotlin/com/raddstream/app/data/cache/` and the pure parts are covered
by JVM unit tests in `app/src/test/kotlin/com/raddstream/app/data/cache/`.

Integration/wiring lives in [`HANDOFF_appcache.md`](HANDOFF_appcache.md).

---

## 1. Architecture at a glance

```
Player (Media3)  ──playhead byte ──▶  CacheCoordinator ──tick()──▶ SchedulerPolicySelector
     │  "keep this"                          │  run ONE bounded pass
     ▼                                       ▼
 keepNow() ──▶ LocalPlaybackHandle     AheadFetcher (progressive, accepts_ranges=1)
     │                                    │  per-gap RangeByteFetcher → IntervalLedger
     ▼                                    │  persist → CacheTaskDao + ByteRangeManifestDao
 LocalMediaProxy (loopback 206)           └─ HlsAheadBuffer (segment ahead-buffer → local.m3u8)
                                            │
 WorkManager CacheSweepWorker ─▶ CacheSweeper ─▶ TtlPolicy + EvictionPlanner
                                            │
                              StorageGate/AndroidStorageGate (StatFs, private filesDir)
```

Layers:
- **Pure decision core** (no Android, unit-tested): `IntervalLedger`, `ByteInterval`,
  `SourceIdentity`, `ResumeToken`, `CoverageMapping`, `CacheTaskStateMachine`/`RetryPolicy`,
  `TtlPolicy`, `EvictionPlanner`/`SchedulerPolicySelector`, `HandoffAccounting`, `HlsPlaylist`,
  `CacheSweeper` (against a `CacheSweepStore` interface).
- **Room**: `CacheTaskEntity`/`CacheTaskDao`, `ByteRangeManifestEntity`/`ByteRangeManifestDao`,
  `CacheFileEntity`/`CacheFileDao` (inert until registered — see handoff §1–§3).
- **I/O engine**: `RangeByteFetcher` (OkHttp + `RandomAccessFile`), `AheadFetcher` (coroutine pass),
  `HlsAheadBuffer`.
- **Storage**: `StorageGate`/`AndroidStorageGate` (`StatFs`, hard ceiling, per-file cap, low floor).
- **Playback boundary**: `LocalMediaProxy` (loopback HTTP 206), `LocalPlaybackHandle`.
- **Scheduling**: `CacheCoordinator` owns running jobs, the scheduler tick, and re-resolve.

---

## 2. The byte-interval ledger (`IntervalLedger`, `ByteInterval`)

The ledger is the single source of truth for **which bytes of one resource are verified on disk**.

- Intervals are **half-open `[start, end)`** with `Long` bounds (files exceed `Int`).
- Canonical invariants, enforced on every `add`: sorted ascending, disjoint, non-touching (adjacent
  intervals merge), no empty intervals. This makes `coveredBytes()` a plain sum (no double count)
  and `gaps(total)` minimal and correct **regardless of the order chunks arrive** — out-of-order
  network completion is the point.
- API the rest of the system relies on:
  - `verifiedPrefix()` → contiguous run from byte 0 = the amount a sequential player can trust and
    the natural resume point.
  - `gaps(total)` → every missing range; this **is** the fetch plan.
  - `missingWithin(a,b)` → fetch plan intersected with a target window; used by the ahead buffer.
  - `firstMissing(total)`, `isComplete(total)`, `isCovered(offset)`, `nextContiguousEnd(offset)`.
- Durability: each committed interval is a row in `byte_range_manifests` (`ByteRangeManifestEntity`),
  PK `(taskId, start)`. A resume after process death rebuilds the ledger from those rows in O(intervals),
  so it can only ever ask for `gaps()` — bytes with a row are never re-requested.

## 3. Source identity — keyed by release+link, not URL (`SourceIdentity`)

Stream URLs rotate (`is_temporary`/`ephemeral` sources, and `POST /play` issues a fresh signed URL
each session), so identity is **not** the raw URL:

1. `resource_id` (content hash from `cat_links.resource_id`) + `release_id` — strongest.
2. `release_id` + `link_kind` + **normalised URL path** (scheme/host/query/fragment stripped) + size.
3. `release_id` + normalised path + size.

`digestHex()` (FNV-1a) is the stable filesystem-safe key. Two signed URLs for the same path → same
digest → the same ledger is reused on re-resolve. **If the digest differs, the cache refuses to adopt
the old bytes** (`ResumeToken.resumeRanges` returns the full range) so a different print never
inherits another print's bytes.

## 4. State machine (`CacheTaskStateMachine`)

States: `QUEUED, LOADING, PAUSED, COMPLETED, FAILED, EXPIRED, DELETED`. Transitions are whitelisted;
illegal moves throw `IllegalStateTransition` and the DB is left untouched (so a late callback from a
cancelled request can never corrupt state).

```
QUEUED  → LOADING | PAUSED | FAILED | DELETED
LOADING → PAUSED | COMPLETED | FAILED | QUEUED | DELETED      (QUEUED = re-resolve / pre-empt)
PAUSED  → QUEUED | LOADING | FAILED | EXPIRED | DELETED
COMPLETED → EXPIRED | DELETED                                  (never back to LOADING)
FAILED  → QUEUED | LOADING | PAUSED | EXPIRED | DELETED       (re-resolve + retry)
EXPIRED → DELETED | QUEUED                                     (QUEUED = still referenced, re-arm)
DELETED → (terminal, nothing)
```
Self-transitions are rejected. `holdsRunningTask` = {QUEUED, LOADING}: a file owned by one of those
is protected from TTL delete and eviction.

**Retry/backoff** (`RetryPolicy`): 1-based attempt, exponential from 2 s, capped 30 min,
`MAX_ATTEMPTS = 6`, deterministic jitter seeded by the task id so a restart keeps the same schedule
(a kill does not reset the backoff clock). On exhaustion → `FAILED`.

## 5. Ahead-of-playback progressive fetch (`AheadFetcher`, `RangeByteFetcher`)

While Media3 plays, one bounded pass per playhead advance:

- Target end = `min(playheadByte + aheadWindow(40 MiB), totalSize)`; plan = `ledger.missingWithin(0, target)`
  fetched **low-to-high** so the verified prefix (gapless playback) grows first.
- Each gap is split into 1 MiB pieces (`RangeByteFetcher`, HTTP `Range: bytes=start-end`) written at
  the exact file offset with `RandomAccessFile`; on success the ledger records `[start, start+written)`
  and it is committed to `byte_range_manifests` + `cache_tasks.downloadedBytes` (progress in **bytes**).
- Throughput / playback-starvation: work is chunked and cooperative-cancelled (`ensureActive`) so a
  chunk finishes fast and the fetch never blocks; per-pass byte cap (`256 MiB`) yields the scheduler.
- Pre-allocation: on first `Content-Range`/`Content-Length` we `setLength(total)` so out-of-order writes
  land correctly and **a partial file is a sized, resumable artifact, not garbage**.

**Hostile degradations:**
- **No range support** (`RangeByteFetcher` → `NoRangeSupport`, `AheadFetcher` → `NO_RANGE_FALLBACK`):
  the server ignored `Range` (200, no `Content-Range`) — we must NOT seek-write into the middle, so the
  coordinator falls back to a single sequential full fetch from offset 0 (`CacheCoordinator.sequentialFallback`).
- **Throughput collapse / transient errors** (`IoError`, `HttpError`) → `RETRY_LATER` → `PAUSED` with
  backoff; bytes already written are kept.
- **Ephemeral source dies mid-download** (`403/410/404` → `SourceDead` → `NEEDS_RERESOLVE`): every
  committed byte is persisted; the coordinator calls `SourceResolver.reResolve` for a fresh URL for the
  **same identity**, re-arms the task (`reResolveWithNewUrl`), and resumes at the first gap. It never
  silently restarts from 0. If re-resolve fails it backs off (`recordRetry`).
- **Unknown total size** (`Content-Length` absent): the plan extends the contiguous prefix forward and
  adopts `totalSize` once any response reveals it.
- **Cancellation / app kill**: `CancellationException` propagates (never swallowed); on next launch the
  task reloads its ledger and continues. Clean cancellation path = pause the job (bytes retained).

**HLS (`hls_manifest`)** → `HlsAheadBuffer`: fetch the media playlist (descend one level if it is a
master, picking the highest-bandwidth variant), download segments ahead of the playhead into
`filesDir/media_cache/<digest>/seg_N.bin`, and emit `local.m3u8` where **covered** segments point at
local files and uncovered ones keep the remote URL (`HlsPlaylist.rewriteLocal`). A segment already on
disk is marked covered and **never re-fetched**. A 403/404/410 segment → same re-resolve path.

## 6. Zero-waste handoff (`HandoffAccounting`, `ResumeToken`, `CacheCoordinator.keepNow`)

**Forward (keep mid-playback):** `keepNow(sourceKey)` promotes the AUTO_PREVIEW task to
USER_REQUESTED (so it drives to 100%) and computes `HandoffAccounting.plan`:
- `resumeRanges = ledger.gaps(total)` — **exactly** the missing bytes; every already-held byte is
  excluded, so fetched + held == total with zero overlap (asserted by `refetchIsExactlyTheGaps()`).
- `resumeFromByte = firstMissing(total)` (never the playhead, never 0).
- `bytesSaved` = bytes already held = what a naive restart-from-0 would have re-downloaded.
The **"70 of 130 minutes"** case is a unit test: a 75-minute buffer at a 70-minute playhead yields
`resumeRanges = [75min_byte, total)`, `bytesToFetch = total − buffered`, `bytesSaved = buffered`, and
proves no byte is re-fetched.

**Reverse (resume after restart / network change):** the persisted `ResumeToken` (`v1|digest|total|rev|ranges`)
plus `ByteRangeManifestDao` rows rebuild the ledger; `resumeRanges(token, digest)` returns gaps for a
matching digest, or the full range if the identity changed. `malformed`/tampered tokens decode to `null`
so garbage ranges are never trusted.

## 7. App-only playback (`LocalMediaProxy`, `LocalPlaybackHandle`)

Files live only in `context.filesDir/media_cache` (private, never external/shared). There is **no
`FileProvider` and no `ACTION_VIEW`/external intent** in this package. To play a **partial /
range-resumed** file the player opens a **loopback-only** `http://127.0.0.1:port/<name>` served by
`LocalMediaProxy`: it answers `Range` with 206 from disk, clamps every response to the verified prefix
(from `ByteRangeManifestDao.contiguousPrefix`), and returns 416 beyond it so Media3 sees a clean EOF at
the frontier rather than reading sparse holes. Completed files may instead be opened via
`Uri.fromFile(...)` (still app-private). HLS uses the rewritten `local.m3u8`.

## 8. TTL auto-delete (`TtlPolicy`, `CacheSweeper`)

All ages use `SystemClock.elapsedRealtime()` (`UptimeClock`) — monotonic, counts deep sleep, immune to
the user changing the wall clock. So a preview cannot expire early from a clock jump and cannot survive
6 real hours just because the phone slept. Negative elapsed (anomaly) clamps to 0.

Precedence per file:
1. `origin == USER_KEEP` → **never auto-deleted** (`USER_KEPT`).
2. `referencedByRunningTask` (QUEUED/LOADING) → **DEFER** (`HELD_BY_RUNNING_TASK`) — never delete under
   a live writer.
3. temporary file with no live owner → ORPHANED_TEMP leak, swept after a 20-min grace
   (`TEMP_GRACE_MILLIS`); within grace it is kept so a quick resume keeps its bytes.
4. otherwise auto-preview → EXPIRE once age ≥ TTL (3 or 6 h from creation). Touching a file does **not**
   extend it; to make a preview permanent the player promotes it to `USER_KEEP`.

`CacheSweeper.sweep()` runs TTL, then a low-storage eviction pass over survivors. `millisUntilDue`
supports finer WorkManager scheduling. Interrupted-then-resumed downloads do not leak: temp files are
either adopted (resume) or reclaimed as ORPHANED_TEMP.

## 9. Storage policy — the hostile cases (`EvictionPlanner`, `AndroidStorageGate`)

Before **any** write the engine calls `EvictionPlanner.admit`:
- **Per-file cap** (`RejectPerFileCap`) — one 4K remaster cannot hog the workspace.
- **Hard ceiling** on total cache usage (`RejectTooBigForCeiling`) — the user setting that guarantees
  "the downloader is never the reason the phone runs out of space."
- **OS low-storage floor** (`StatFs.availableBytes`): if free < floor, `EvictThenAdmit` frees space first;
  if even eviction can't reach the floor, `RejectNoEvictableHeadroom` (the write is refused, not forced).
- **Eviction ordering** (least-useful first, never protected): `usefulnessScore` = temp < incomplete <
  completed; then lowest `watchCount`; then oldest `lastAccess` (recently-needed kept). Protected =
  `USER_KEEP` or running-task-owned — never deleted. `plan()` stops as soon as the target is freed, so
  the most-watched/most-recently-needed files survive.
- **Disk fills mid-write**: the partial file is pre-sized and its completed ranges are in the ledger → it
  is resumable, not garbage (see §5). The gate re-checks free space before each chunk.
- **Storage permission denied / unwritable**: `openForWrite`/`StatFs` failures surface as `RETRY_LATER` /
  `STORAGE_SUSPENDED`; the task parks in `PAUSED` rather than crashing playback (playback continues on the
  network stream).

## 10. Queue + fairness (`SchedulerPolicySelector`)

- Global concurrency cap (`maxConcurrent`, default 2); `CacheCoordinator` runs at most that many `LOADING` jobs.
- **USER_REQUESTED always beats AUTO_PREVIEW**: scheduled first; when full of auto work, running auto tasks
  are **pre-empted = paused (bytes kept)**, choosing the least-progressed (largest remaining) auto first.
- Within a band: FIFO by enqueue time.
- Network gates (`NetworkClass` from the OS): AUTO_PREVIEW only on WIFI (or MOBILE if
  `allowAutoPreviewOnMobile`); never on `METERED_ROAMING`; **nothing** runs on `NONE`. USER_REQUESTED runs on
  WIFI/MOBILE.
- Data budget: an auto-preview whose remaining bytes exceed the period budget is throttled, not started.
- Battery: no busy loops (bounded passes) and the sweep runs under `Constraints{batteryNotLow}` (handoff §6).
- Cancellation: `jobs[id].cancel()` → structured `CancellationException`, ledger flushed on the way out.

## 11. Scenario coverage map (owner's list → what the code does → test)

| Scenario | Behaviour | Where | Test |
|---|---|---|---|
| Play + keep downloading | bounded ahead pass per playhead | `AheadFetcher.run` | (engine, needs SDK) |
| `accepts_ranges=1` direct | per-gap range writes | `RangeByteFetcher.fetch` | ledger math `IntervalLedgerTest` |
| HLS ahead-buffer | segment buffer + local.m3u8 | `HlsAheadBuffer` + `HlsPlaylist` | `HlsPlaylistTest` |
| Server no ranges | sequential fallback | `NO_RANGE_FALLBACK`→`sequentialFallback` | (engine) |
| Throughput collapse | chunk + cap + backoff pause | `ensureActive`, `RETRY_LATER` | `RetryPolicyTest` |
| Ephemeral dies mid-download | persist bytes, re-resolve, resume (never restart) | `NEEDS_RERESOLVE` | `SourceIdentityTest` (adopt vs refuse) |
| 70/130 keep → no re-fetch | resume at buffer head | `HandoffAccounting.plan` | `HandoffAccountingTest` |
| Resume after restart | rebuild ledger from rows/token | `ResumeToken.decode`/`resumeRanges` | `ResumeTokenTest`, `HandoffAccountingTest` |
| Out-of-order arrival | canonical disjoint merge | `IntervalLedger.add` | `IntervalLedgerTest` |
| Completion detection | gaps empty | `isComplete` | `IntervalLedgerTest` |
| Disk already full | refuse write, evict least-useful first | `EvictionPlanner.admit`/`plan` | `EvictionPlannerTest` |
| Disk fills mid-write | partial file is resumable | pre-alloc + manifest commit | (engine) |
| Storage perm denied | park PAUSED, keep playing remote | `STORAGE_SUSPENDED` | (engine) |
| TTL 3h vs 6h | user-configurable expiry | `TtlPolicy`, `TtlHours` | `TtlPolicyTest` |
| User-kept never deleted | precedence rule 1 | `TtlPolicy.evaluate` | `TtlPolicyTest`, `CacheSweeperTest` |
| File under a running task | deferred, not deleted | `HELD_BY_RUNNING_TASK` | `TtlPolicyTest`, `CacheSweeperTest` |
| Interrupted-then-resumed leak | orphaned temp swept after grace | `ORPHANED_TEMP` | `TtlPolicyTest`, `CacheSweeperTest` |
| App-only playback | loopback 206, no FileProvider | `LocalMediaProxy` | (engine) |
| Concurrency cap / priority / network | scheduling | `SchedulerPolicySelector` | `SchedulerPolicyTest` |
| Packed-season offset mapping | episode↔byte | `CoverageMapping` | `CoverageMappingTest` |

## 12. Verification status

- Pure logic + orchestrators: **JVM unit tests only** (no Android framework) — interval ledger,
  resume-token math, handoff accounting (incl. 70/130), ephemeral adopt/refuse, state machine,
  retry/backoff, coverage mapping, TTL, eviction (full-disk ordering), scheduler fairness, HLS
  parse/rewrite, and `CacheSweeper` end-to-end against a fake store.
- Room entities/DAOs, `RangeByteFetcher`/`AheadFetcher`/`HlsAheadBuffer`, `AndroidStorageGate`,
  `LocalMediaProxy`, `CacheCoordinator`: **require the Android SDK / device to verify** (see the report
  section in `HANDOFF_appcache.md`); written conservatively but not compiled here.
