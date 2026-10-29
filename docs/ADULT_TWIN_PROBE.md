# The adult twin probe — counting what the per-row filter cannot hide

Status: **designed and pinned offline. Not run against production.** Load on this box was
**7.95** when this file was written, and the fleet rule is nothing heavy above load 4, so the
production count below is a marked next step for a quiet window, not a number anyone has.

## 1. The defect, stated exactly

`AGENTS.md` records the invariant as: no public surface may list *or play* a row flagged
`is_18_plus=1`. That law is applied **per row**. Media identity is **per key** — many `posts`
rows can carry the same `cat_works.canonical_key`, one work scraped from several sites. When a
key holds both a flagged row and an unflagged one, the unflagged twin is listable, searchable
and playable, and it names the same film. The historical measurement was **442** distinct
`canonical_key` values in that state and **455** flagged rows still reachable, e.g. `4 Play`
id 23519 (hindilinks4u, `is_18_plus=0`) answering `/api/v1/posts?q=4+Play` while the same film
from filmyhit is correctly hidden. **I did not re-measure either figure here** — both are quoted
from the root `AGENTS.md` note taken against `09058ef`, and the point of this document is the
query that lets anyone re-measure them cheaply and correctly, in one index-only pass.

## 2. The query

```sql
-- (A) how many works are named by BOTH a flagged and an unflagged row
SELECT COUNT(*) FROM (
  SELECT canonical_key FROM posts
  WHERE canonical_key IS NOT NULL
  GROUP BY canonical_key
  HAVING SUM(is_18_plus) > 0 AND SUM(1 - is_18_plus) > 0
);

-- (B) the flagged rows that are reachable through a twin — the exposure count
SELECT COUNT(*) FROM posts p
WHERE p.is_18_plus = 1
  AND EXISTS (SELECT 1 FROM posts q
              WHERE q.canonical_key = p.canonical_key AND q.is_18_plus = 0);
```

Why this shape, measured rather than assumed — `EXPLAIN QUERY PLAN` on the fixture in
`Fast_Fetch/test_adult_twin_probe.py`:

```
SEARCH posts USING INDEX idx_posts_canonical_key (canonical_key>?)
```

**Index-only, and no `USE TEMP B-TREE FOR GROUP BY`**, because `idx_posts_canonical_key` already
delivers the grouping order and the aggregate reads only the key and the flag from the index's
rowids. That matters on this file: the qoder4 master measured `SELECT COUNT(*) FROM posts` at
**0.91 s** and the same read with `WHERE is_18_plus = 1` at **26.46 s** (both 2026-10-30, cited
not repeated — re-running either at load 8 breaks the fleet rule). The 26 s is the wide-row cost
of touching the table; a probe that stays inside the key index is the only kind of adult audit
that belongs on a live box at all.

Two shape traps this avoids, both learned the hard way tonight in
[`SEARCH_LATENCY_FINDINGS.md`](SEARCH_LATENCY_FINDINGS.md):
- **Do not join `releases`/`download_sources` into the count.** The exposure count needs no
  media rows, and the by-media route's 66 s came from full scans, not from a missing index.
- **Do not group by `clean_title`.** Titles differ per site (`… hd` vs `… (2019)`); only
  `canonical_key` names the work, which is the whole reason the defect exists.

## 3. What the probe does NOT settle

(A) and (B) count the exposure; they do not remove it. The fix is a **reconciliation**: propagate
`MAX(is_18_plus)` across every row sharing a `canonical_key`, so a flagged twin flags the work,
plus a test that fails if a later scrape writes an unflagged row under a key that has ever carried
a flagged one. Reconciling is a production write and is explicitly outside this brief. Also note
(B) counts rows, (A) counts works; the older 442/455 pair is (A)/(B) respectively, so re-measuring
must report both or it is not comparable.

## 4. The quiet-window run, marked as a next step

Run **only** when `uptime` shows load under 4, read-only, `nice`/`ionice`, one pass, no loop:

```bash
python3 -S - <<'PY'
import sqlite3
c = sqlite3.connect("file:/home/ubuntu/radd-stream-data/merged_catalog_20261025.db?mode=ro",
                    uri=True)
a = c.execute("SELECT COUNT(*) FROM (SELECT canonical_key FROM posts"
              " WHERE canonical_key IS NOT NULL GROUP BY canonical_key"
              " HAVING SUM(is_18_plus) > 0 AND SUM(1 - is_18_plus) > 0)").fetchone()[0]
b = c.execute("SELECT COUNT(*) FROM posts p WHERE p.is_18_plus = 1 AND EXISTS"
              " (SELECT 1 FROM posts q WHERE q.canonical_key = p.canonical_key"
              "  AND q.is_18_plus = 0)").fetchone()[0]
print(f"works with a mixed key: {a}   flagged rows reachable via a twin: {b}")
PY
```

Expect the plan above; if it says `SCAN posts` instead, the index is gone and the run must be
aborted rather than allowed to finish — a `SCAN` here is a multi-minute table read on the file
the service is using. Name the file and the load in the same sentence as the two numbers.

## 5. Evidence, reproducible offline

`python3 -S Fast_Fetch/test_adult_twin_probe.py` — a temp fixture, no production file, no
network. It pins the mixed-key counting (a key with only flagged rows is not an exposure; a NULL
key is not a twin), the (A) vs (B) distinction, and the index-only plan text. If
`idx_posts_canonical_key` is ever dropped from the schema, the plan assertion fails before anyone
runs a `SCAN` against production and mistakes it for a measurement.
