# 2026-10-28 23:45 — ARY Plus dead-ID audit closed: all 538 are 307 soft-404s, no retry justified

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 23:45 — ARY Plus dead-ID audit closed: all 538 are 307 soft-404s, no retry justified

**Status: `aryplus.db` is frozen** (no writes and no crawl since the retry). The importer fix is
committed as `1d0d4b7` and pushed to `master` + `main` (`ad9ba30..1d0d4b7`); this audit entry is
the remaining deliverable. The pre-retry copy is `/tmp/aryplus.pre_retry.db` (6.6 MB,
`scraped=-1 → 538 @ error_count=1`, `scraped=1 → 481`). The vault remains **out of the merge
queue**; no merge was performed.

### What the retry actually mutated

Only `sitemap_cache`, and only three columns: `scraped`, `error_count`, `raw_json`. `posts`,
`releases`, `sources` are byte-for-byte unchanged in row count and `MAX(posts.scraped_at)`;
`is_18_plus=0` before and after.

| Pass | Rows | `scraped` | `error_count` | `raw_json` |
|---|---:|---|---|---|
| live `--limit 1` probe | 1 | −1 → 2 | 1 → 2 | adds attempt 2 |
| retry pass 1 | 538 | −1/2 → 2 | 1 → 2 | legacy entry + attempt 2 |
| retry2 (killed at 160/537) | 160 | 2 → −1 | 2 → 3 | attempt 3, `status=dead` |
| resume after SIGTERM | 377 | 2 → −1 | 2 → 3 | attempt 3, `status=dead` |

The resume (377 rows) completed **before** the SINGLE-MASTER notice reached this session; the
SIGTERM stopped retry2, not the resume. Net state now: **538 rows at `scraped=-1`,
`error_count=3`, `raw_json.status=dead`**; 481 live rows untouched at `scraped=1,
error_count=0`.

### Cap-3 semantics (committed as `1d0d4b7`)

- Eligible set: `scraped IN (0,2) OR (scraped=-1 AND error_count<3)`. A parked row is no longer
  terminal at one failure.
- Each attempt is exactly one no-follow GET (`retries=0`); no hidden transport retries and no
  blocking sleeps beyond the crawl delay. A 3xx is preserved as the real failure instead of being
  followed to the homepage and mislabelled `no-jsonld`.
- `attempts = error_count+1`; each attempt appends one ledger entry
  `{attempt, kind, http_status, final_url, detail, exception?}` (last 8 kept). Status is
  `retrying` below the cap, `dead` at `attempts>=3`; `scraped=-1` at the cap, else `2`.
- Success through `export_staging` sets `scraped=1`, `error_count=0`, `raw_json.status=ok`.
- Known review point: `park_now` (404/410) writes `status=dead` early but the eligibility clause
  still retries it until the cap. No 404/410 occurred in this cohort, so no data effect.

### The 538 dead sitemap IDs, quantified

| Bucket | Count | Share / note |
|---|---:|---|
| Sitemap IDs total | 1,019 | 481 live + 538 dead |
| Live (`scraped=1`) | 481 | 47.2% |
| Dead (`scraped=-1`, `error_count=3`) | 538 | 52.8%, 538 distinct slugs |
| Dead, two measured 307 attempts in ledger | 537 | both attempts `Location: https://aryplus.tv` |
| Dead, measured 307 + aborted third attempt | 1 | `692ad7ed731e7d8c20de9baa`; re-probed live 2026-10-28 → 307 |
| Posts / releases / sources | 481 / 10,860 / 10,860 | delta 0 vs pre-retry snapshot |
| Adult-flagged | 0 | delta 0 |

Ledger composition: 538 `legacy-unrecorded` (attempt 1 predates logging; reason unavailable),
538 `redirect/307` (attempt 2), 537 `redirect/307` (attempt 3), 1 `transport/0` (attempt 3, the
SIGTERM artifact above).

Dead IDs by ObjectID creation year (UTC): 2024 = 44, 2025 = 134, 2026 = 360. Largest months:
2026-02 = 133, 2026-01 = 62, 2026-09 = 56, 2026-03 = 48. Oldest 2024-03-05, newest 2026-10-23;
live IDs span 2023-09-04 → 2026-10-26. So these are not one stale batch: the sitemap carries
unpublished/deleted IDs across three years.

### 404/410 vs unhydrated SPA shell: the classification

| Classification | Count | Recorded evidence |
|---|---:|---|
| True 404/410 gone page | **0** | No 404/410 in 1,614 ledger entries (538 × 3 attempts); 13/13 live re-probes on 2026-10-28 returned 307 |
| 200 shell with a title payload the parser failed to hydrate | **0** | The 200 body after the redirect is the 5,208-byte homepage: 0 `self.__next_f.push` blocks, 0 JSON-LD, 0 `vod.aryzap.com` URLs, 0 hits of the requested ID |
| Unpublished/deleted id, served as 307 → homepage | **538** | 17,690–17,733-byte `__next_error__` shell; `Location: https://aryplus.tv` |

The 307 body is not a title shell either: it is the Next.js error shell (`<html
id="__next_error__">`, 5 RSC chunks, the requested id twice), and the destination is the
homepage. A known-good title page for contrast: 149,662 bytes, 13 RSC chunks, 2 JSON-LD blocks,
40 `vod.aryzap.com` URLs, title `Watch Jaisay Aapki Marzi | ARY Plus Official Site`. A browser
cannot hydrate a title the server did not send, so this is a gone page, not a parser miss.

Live sample (read-only, one no-follow GET each, 0.4 s apart, `nice -n 15`):

| Slice | Probed | 307 → home | 404/410 | Title payload |
|---|---:|---:|---:|---:|
| 2024 IDs | 4 | 4 | 0 | 0 |
| 2025 IDs | 4 | 4 | 0 | 0 |
| 2026 IDs (incl. `6adbc…`) | 4 | 4 | 0 | 0 |
| `692ad7ed…` (artifact row) | 1 | 1 | 0 | 0 |

Following two of them (`65e6ed…`, `692ad7…`) produced the 5,208-byte homepage with
`rsc=0 jsonld=0 vod=0 id_hits=0`.

### Is another retry pass worth running? No.

- 538/538 observed failures are deterministic Next.js routing: unknown title → 307 to `/`.
  Attempt 2 was a 307 for all 538; attempt 3 was a 307 for 537 and an aborted request for 1,
  which now also re-probes as 307.
- Two full passes already spent 1,076 GETs and wrote `posts=0, releases=0, sources=0`; a third
  pass would repeat the same 538 redirects with no new evidence.
- The only open question was the aborted row, and a single live GET answered it (307). No DB
  write is needed to accept that; the stored ledger keeps the artifact honestly.
- Revisit only if the site republishes these ids. The trigger should be a 10-id sample probe
  (read-only), and lifting the cap must be a deliberate state reset, not a crawl flag.

### Hand diagnosis of `6adbc1756b3c8c352b377ebd`

`GET https://aryplus.tv/title/6adbc1756b3c8c352b377ebd` → **HTTP 307**, `Location:
https://aryplus.tv`, 17,690-byte Next.js `__next_error__` shell; identical for Chrome and
Googlebot UAs (not UA-gated). Following it yields the 5,208-byte homepage. `.../en/title/<id>`
returns 200 but the same 5,208-byte homepage: **0 JSON-LD blocks, 0 `vod.aryzap.com` URLs** — a
soft 404, not a title page. Not a locale or CDN workaround; the ID currently has no title.

### Open items

1. `692ad7ed731e7d8c20de9baa` — **closed by evidence, ledger left as recorded.** Its third
   attempt was a stop artifact: `STOP_REQUESTED` inside `http_get` returned status 0 and the
   ledger fallback recorded `detail="transport failure"`. The live re-probe returned 307. The
   importer now refuses to spend an attempt on a stop-aborted request (`1d0d4b7`); the stored
   ledger was deliberately not rewritten.
2. The importer/test changes were committed as `1d0d4b7` and pushed to both refs. This audit
   entry is the docs commit that follows; `aryplus.db` remains frozen.

