# 2026-10-28 — Session: the DesiSerials pilot runs, and the retry rule gets a cap and a reason (Qoder3)

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-28 — Session: the DesiSerials pilot runs, and the retry rule gets a cap and a reason (Qoder3)

**What landed.**
- `10fb93d fix(importers)` — `_bump_error` in `import_animahd.py` and `import_desiserials.py`
  now stores `last_error` per attempt and checks `error_count >= 3` **before** the requeue
  branch. `scraped = 2` is itself a queued state, so the old ordering let a page that fails
  the same way every pass be re-queued forever; three attempts now means three. The queue
  table is migrated in place (`_add_missing_columns` on `sitemap_cache`), so an existing
  staging database heals instead of crashing. A first failure still never parks a row.
  Same commit fixes `import_desiserials._flush`, which marked a finished episode from
  `raw_meta["episode_page"]` — a key the series record does not carry, because an episode
  page belongs to its release. It died mid-pilot with the writes already committed and all
  200 rows still queued; the row is now carried on the record as `queue_loc`.
- `794570a fix(animahd)` — a page served without episode anchors is re-read through
  `wp-json ...?slug=` before it is declined.

**DesiSerials pilot — measured, `verify=False`, workers=1, nice 15, into
`/home/ubuntu/radd-stream-data/desiserials.db` only.**
- queued 200 of the 3,646-episode catalog (REST pages 1–2), crawled 200 in 211 s,
  `declined=0 failed=0`, queue now `scraped=1` on 200/200.
- **34 posts / 200 releases / 359 sources** — one series row per show, one release per
  episode, exactly as the site publishes it (3,646 episodes → one row per series).
- Sources by service, all `playback_type=iframe`, all `unverified` at rest:
  vkspeed 190, upbolt 164, vkprime 5.
- `sample --rows 25` (verify=True): **10 `active`** (vkspeed 200 with a player document),
  **2 `blocked`** (upbolt 403 to this host), **13 left `unverified`** — HTTP 0 transport
  refusals, which are not verdicts about the link and are therefore not written as any.
  12 rows carry `last_checked`; the other 347 stay untouched.
- `is_18_plus` is 0 on all 34 rows and that is the catalog, not a wiring gap: `looks_adult`
  is called in `build_record` and `MATURE_TOKEN_RE` already carries `18\s*\+` outside the
  word-boundary group. Measured on the cohort — 0 of 34 published titles and 0 of 200
  queued payloads contain any adult token.

**AnimaHD: the 233rd post is not recoverable, and it is now recorded as why.**
`/from-old-country-bumpkin-to-master-swordsman/` (post 247) was at `scraped=2, error_count=2`
— requeued, never retried. Measured: the page is HTTP 200 / 104,642 bytes containing **zero**
episode anchors (both `app-ep-row-item` strings are inside JS selectors); `posts/247` is
13,617 bytes whose `content.rendered` is **397 bytes** — an empty `wp-block-paragraph` plus a
hidden Yoast SEO block — with **0 iframes in any field**; `?search=bumpkin to master swordsman`
returns that one post and 0 iframes in 48,407 bytes; `/wp-json/` lists no anime namespace at
all. So the reported 3668-byte / 32-iframe body does not reproduce on any of those request
shapes, and there is no JSON path to parse. The fallthrough is implemented and tested anyway
because it is the right order of operations, and with it the row ends
`scraped=-1, error_count=3, last_error='no-episode-rows'`. **AnimaHD: 232 posts / 4,801
releases / 9,575 sources** — that is the whole server-rendered catalog. No UA was chased:
`import_animahd.py` sends its browser UA at lines 264 and 296 and its header comment records
the 403-without-UA rule.

**Tests.** 59 offline in `test_desiserials_import.py` (the two queue-marking tests fail on
the old `_flush` with the same KeyError the pilot hit), 48 in `test_animahd_import.py`, 75 in
`test_database.py`. All green, all socket-blocked.

**Deliberately not done.** No push. Nothing merged: `fast_fetch.db` and
`merged_catalog_20261025.db` were not opened. No headless browser and no JS engine, so a
client-side episode grid stays unparsed rather than being worked around. No challenge solver,
no Referer on any media request, and upbolt's 403 is stored as `blocked` instead of probed.
`import_aryplus.py` / `test_aryplus_import.py` are modified in this checkout by another
account and were left unstaged. Databases stay out of Git.

---

