# Session 2026-11-06 — crown supervisor `[CROWN-NIGHT-CHAIN]`: five trunk commits, one live-tree gap

Lane: qoder1 (crown supervisor). Base at start: `8a012d7`. Trunk at end: **`6b93405`**.
Host clock PKT throughout; box is nproc=1, `radd-stream.service` MainPID 3467520 since
Tue 2026-11-03 22:37:47 PKT and never restarted by anyone tonight.

## What landed on `main` (each is CI-green on the sha itself)

| sha | what | measured effect |
|---|---|---|
| `d9f73c5` | backup disk fix — the nightly backup's staging temp and the LFS clone leak | stops unbounded growth on a 65 %-full root |
| `f3849b8` | edge paging (`POSTS_MAX_OFFSET`, `bounded_int`) + `NEUTRAL_UPLOAD_HOSTS` serving neutral CDN art direct, + AGENTS.md de-drift | `?page=abc` becomes a 400 instead of a crashed connection; `?limit=1&page=1000000` is refused before the offset walk (was 15.33 s on loopback for an 84-byte answer) |
| `e052153` | `test_trunk_continuity.py` — a tripwire for the silent revert that behaviour suites cannot see | 7 tests; catches a reverted protection by symbol, not by behaviour |
| `45115bb` | `canonical_key` refusal guard (`canonical_key_corroborates`, `guard_canonical_key`, `journal_key_refusal`) + `key_census.py` | a row's key must name the row or the key is refused and journalled at write time |
| `6b93405` | adult fold vocabulary 30 → 52 tokens (`aka` deliberately excluded) + `EmptyTokenRefusalTests` (20 → 27 tests in `test_adult_fold_guard.py`) | 8 exposed keys move quarantine → agree, 0 move back, **no collision folds** (`connect_2022`, `euphoria`, `hot-girls-wanted`, `lucifer`, `sketch_2018` still refuse) |

Nothing above wrote to production data. **No `--apply`, no `--projection`, no re-key, no `UPDATE` of
`is_18_plus` or `canonical_key` has been run on any database.** The fold and the audit are both waiting
for the owner's word.

## The gap that matters more than the commits

The live tree at `/opt/radd-stream` is still `bf9e565`, which is **not an ancestor of `main`** (merge-base
`19abff7`; 2 live-only commits vs 294 trunk-only). The service runs the bytes on disk, so the running
edge has **none of the five protections** listed above — including `_tls_context`, which exists on trunk
(1 definition, 11 call sites) and does not exist live (0 and 0). Proven on the box, not inferred:
`?page=abc` → connection death at loopback / 502 at the edge; `?limit=1&page=1000000` → 84 bytes after
15.33 s. The adult invariants hold on both surfaces (`/api/v1/posts/159` 404 everywhere, `/api/m3u?id=159`
0 bytes at loopback and 403 at the edge, bare `/api/m3u` 403).

A file-graft deploy (copy one protection's hunks onto the live tree) was tried twice and is **dead**:
the hunks' context lines *are* trunk code the live tree predates, so they fail to apply, and a fuzz-2
graft that "succeeds" produces a file that compiles and does nothing (`defs=0 call-sites=2`).
`redact.py` is the single exception — it grafts with `--fuzz=0` and behaves correctly (CROWN_VERIFY_69
§9). The real choice is Plan A (move the tree) vs Plan B (fresh checkout + merge) vs C′ (`redact.py`
only), priced by q13's order #73 rehearsal; nobody has moved or restarted anything.

## Fleet decisions recorded this session

- **Rejected**: stripping bracket groups from the title cleaners to "converge" 6,209 `asymmetric-alias`
  + 11,917 balanced-bracket-year rows onto existing keys. It deletes the only stored copy of an alternate
  name and moves `hi-nanna`, `la-querida`, `aadu-magaadra-bujji`, `kantara-chapter-1` further apart.
  That population is tokeniser/gate work, not cleaner work.
- **Retired claims**: an 11,680-title shrink figure (correct values 11,685 filed-P1 / 11,575 shipped);
  "47-entry `JUDGE` map" (it is 36, plus a separate 23-entry `MAINSTREAM_KNOWN`); a `dom` series-vs-film
  classification (it is a year-parse artefact); a "production WAL was *written*" claim (downgraded to
  *opened* — the write fingerprints all read unchanged); the file-graft deploy plan.
- **Measured and unresolved**: `generate_canonical_key(clean_title, year)` disagrees with the stored
  `canonical_key` on **69,773 of 150,799 rows (46.3 %)** — independently reproduced by two agents with
  identical digits. Any "recompute the keys" sentence is a migration of half the ledger.
- **Measured, waiting for the owner**: an audit `--apply` at this sha frees **4,043** flagged rows
  (crown's count; the lane's is 3,931) and un-hides **3,726 works**, of which only 430 works / 563 rows
  are the residual population under study; 3,296 of those works are hidden on every surface today.

## Next actions owned by someone

1. Owner: deploy choice (Plan A / B / C′), fold `--apply`, audit tranche (i)/(ii)/(iii), five disk
   decisions, the 18080 `admin-v2` server question.
2. q14, order #75: three producer defects fixed test-first (`import_katmoviehd.py` leading-`and`,
   `import_hindilinks4u.py:328` missing `\)`, bare `Season` noise alternative). Migration demand counted,
   not executed.
3. q12, order #76: flag-provenance reconstruction — which of the 15,068 flags does the current rule
   still justify, and the fold∩audit intersection.
4. q13, order #73 (still owed): Plan A rehearsal at the new tip.
5. Crown: judge each filing by re-measurement; `Q14_RESULT_72` judged in CROWN_VERIFY_72, `Q12_RESULT_71`
   in CROWN_VERIFY_71, orders #69/#70 in CROWN_VERIFY_69/70.
