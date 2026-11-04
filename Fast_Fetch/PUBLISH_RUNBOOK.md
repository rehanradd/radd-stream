# 📜 PUBLISH_RUNBOOK — static catalog export → `/var/www/radd-static`

> **STATUS: DRAFT — NOTHING IN THIS FILE HAS BEEN EXECUTED.**
> As of 2026-11-05 the staging directory `/var/www/radd-static` does **not**
> exist, no nginx config references it, and the Emperor has not approved it.
> The Crown Prince (order `qoder13_publish_runbook`) executes or approves each
> marked step; no agent runs them. Steps tagged `[APPROVAL-GATED]` touch
> `/var/www` or `/etc/nginx` and stop until that approval is explicit.

## Why this runbook is written before any publish

A pre-generated static JSON is a **new public display surface with no
request-time gate**. Today the public list is protected twice over —
`redact.adult_clause` (`Fast_Fetch/redact.py:1068`, applied inside
`api_v1_get_posts`, `Fast_Fetch/viewer.py:2516`) on *every request*, and the
nginx route allow-list. A bug in either can be fixed and the next request is
clean. A bad exported byte sits on disk — and in every client's cache — until
someone re-runs the export and reloads. That asymmetry is the whole content of
this runbook: gate 1 proves the bytes, gate 2 installs, gate 3 serves, and §4
says how long a mistake survives and how to end it.

---

## 0. Prerequisites (all must be true; any one false ⇒ do not proceed)

| # | Condition | How to check | Status today |
|---|---|---|---|
| 0.1 | `reconcile_adult.py` merged, so ledger flags are per-*work* not per-row | `git log --oneline -- Fast_Fetch/reconcile_adult.py` on `master` | ❌ lives on `q11-adult-reconcile-20261104`, **not merged** |
| 0.2 | Emperor has explicitly approved the web root | written in a crown order | ❌ asked, not answered |
| 0.3 | `sweep_public_edge.py --export` OK on a snapshot | `python3 -S Fast_Fetch/sweep_public_edge.py --db /tmp/edge_snapshot.db --posts 20 --export` | ✅ 2026-11-05 (`4f7c17d`): 0 leaks |
| 0.4 | `test_catalog_exporter` green | `python3 -S Fast_Fetch/test_catalog_exporter.py` | ✅ 16/16 |
| 0.5 | Full 15-module CI list at branch head | the backend-ci.yml list | 🟡 13/15 — the two reds (`test_evidence_writeback`, `test_merge_catalogs`) are pre-existing at master base `bf9e565`, link-state vocabulary drift; **must be green before publish** because the same drift could mark a link state nobody has reviewed |
| 0.6 | Export content decision settled: browse list only (no synopsis, no art handles, no stream/download URLs) | `catalog_exporter.export_page` + §"the synopsis incident" below | ✅ |

> **The synopsis incident — keep verbatim, it is the strongest argument here.**
> A `synopsis` column was added to the export SELECT for "API parity" and the
> real-data sweep immediately flagged brand text (`G-Direct`, `PikaHD`,
> `gostream`) in the exported bytes. Root cause: the live browse route never
> emits `synopsis` at all, stored synopsis is scraper prose, and
> `redact.scrub_text` only deletes from its *curated* list of known brands —
> an unknown brand survives it. The column was removed. A pre-rendered public
> file must never carry free scraper prose: there is no request-time fix that
> reaches bytes already on disk and already in caches.

---

## 1. Build & verify in staging (agent-executable today; touches only `/tmp`)

```bash
cd /opt/radd-stream                      # or the reviewed worktree at branch head
BUILD=/tmp/radd-static-build-$(date +%Y%m%d%H%M)
python3 -S Fast_Fetch/catalog_exporter.py \
    --db /home/ubuntu/radd-stream-data/merged_catalog_20261025.db \
    --out "$BUILD" --pages 20 --per-page 50
```

The exporter opens the ledger `mode=ro` (`catalog_exporter.export_catalog`) —
it cannot write to the database — and every file lands atomically
(temp + `os.replace`). Then prove the bytes before anyone moves them:

```bash
python3 -S Fast_Fetch/sweep_public_edge.py \
    --db /tmp/edge_snapshot.db --posts 20 --export   # gate 1a: harness green
grep -RhoE 'https?://[A-Za-z0-9._-]+' "$BUILD" \
    | cut -d/ -f3 | sort -u                          # gate 1b: eyeball host list
```

Gate 1b must show **only** the `redact.PUBLIC_IMAGE_HOSTS` CDN names. Any other
host ⇒ stop, that byte must not leave `/tmp`.

## 2. Install — `[APPROVAL-GATED]`

Versioned-release layout so rollback is a pointer move, not a rebuild. The
releases live **outside** the served path — `/var/www/radd-static` is only ever
a symlink, never a directory (a directory there would silently swallow the swap
`mv` into it and publish nothing):

```text
/var/www/radd-static                  ← symlink ONLY; the path nginx names
/var/lib/radd-static/releases/…       ← immutable export trees (keep the last 3)
```

```bash
# 2.1 first time only (Emperor-approved): create the release store
install -d -m 0755 -o root -g www-data /var/lib/radd-static/releases

# 2.2 copy a verified build in
cp -a /tmp/radd-static-build-<stamp> /var/lib/radd-static/releases/<stamp>

# 2.3 activate — one atomic symlink rename; requests between swaps see the old
#     bytes or 404 before the very first publish, never a half-installed tree
ln -sfn /var/lib/radd-static/releases/<stamp> /var/www/radd-static.new
mv -Tf /var/www/radd-static.new /var/www/radd-static
```

Retention: keep the three newest releases; prune older only after gate 3 passes.

## 3. Serve — `[APPROVAL-GATED]` — proposed nginx snippet (NOT installed)

Read-only, `alias`-based, no directory listing, short bounded cache. Add via a
file in `/etc/nginx/conf.d/` or an include the review picks — this runbook does
not decide which:

```nginx
location ^~ /static-catalog/ {
    alias /var/www/radd-static/;
    autoindex off;
    default_type application/json;

    # The invalidation lever — see §4. Short TTL is the whole safety story.
    expires 15m;
    add_header Cache-Control "public, max-age=900, must-revalidate";

    # A static catalog never needs to execute or proxy anything.
    gzip on;
    types { application/json json; }
}
```

Reload gate — order and no shortcuts:

```bash
sudo nginx -t            # must pass; a config nobody read is not "obviously fine"
sudo systemctl reload nginx
```

`nginx -s reload` re-reading config is instant for the *route*; it does **not**
re-fetch bytes or purge anything cached downstream of nginx. Remember that when
reading §4.

## 4. Invalidation story — how a newly-flagged work stops being served, and how long that takes

**Sequence for "we discover post X is adult" (or reconcile flags a twin):**

1. Fix the ledger row (`is_18_plus=1`, or the reconcile run writes it).
   The live API stops listing it **immediately** — `redact.adult_clause` is
   evaluated per request. That path has zero TTL lag; measured as 0.
2. The **static** copy does *not* fix itself. It is rewritten only when the
   exporter next runs; the twin/adult clauses live inside the export query
   (`guarded_posts_where`), so the next build simply omits the work.
3. Between the next build landing (§2.3 swap) and downstream caches aging out,
   stale bytes can still be served. The `Cache-Control` above bounds that at
   15 min (`must-revalidate` forces nginx-side expiry but browser copies hold
   `max-age` for the same 15 min).

**Maximum exposure window, stated plainly:**

```
   (time until next scheduled export run)
 + (build+copy step cadence; ~0 if cron'd together)
 + 15 minutes  (browser-held max-age)
```

With an hourly export: **≤ 75 minutes**, and every minute of that is a window
that the live API does not have. With the export never scheduled: **forever** —
which is why §0.1/§6 exist.

**Kill switch (bytes-level, immediate, no rebuild):** repoint the symlink at an
empty quarantined release; nginx starts answering 404 on the next request.

```bash
install -d /var/lib/radd-static/releases/quarantine
ln -sfn /var/lib/radd-static/releases/quarantine /var/www/radd-static.new
mv -Tf /var/www/radd-static.new /var/www/radd-static   # [APPROVAL-GATED]
```

Remaining exposure after the kill: only client-side copies already handed out —
≤ 15 min by design. (No `proxy_cache` is configured for this location; if one
is ever added upstream of nginx, its purge story must be written here first or
this runbook's numbers are wrong.)

**Serving a flagged row is a defect, not a policy** (AGENTS.md invariant), so
§0.1 (per-work reconciliation) is what makes step 2 complete: until the ledger
reconciles twins, an unflagged twin of a flagged work passes both the export
query's *row* clause and the prefetcher — and the export's twin clause is the
only thing hiding it. That clause exists (`catalog_exporter.guarded_posts_where`,
belt); `reconcile_adult.py` is the braces. Both must be true before publish.

## 5. Rollback

One pointer move, because releases are immutable and the last three are kept:

```bash
ln -sfn /var/lib/radd-static/releases/<previous-good-stamp> /var/www/radd-static.new
mv -Tf /var/www/radd-static.new /var/www/radd-static    # [APPROVAL-GATED]
```

No nginx reload is needed for a rollback (path unchanged, bytes swapped). The
≤15-min stale-cache bound from §4 applies in this direction too: a rollback
replaces disk, not client caches.

## 6. Honest machine ceiling (why the prefetcher's spec number parks the worker here)

Measured 2026-11-04/05 on this box (40 × 15 s samples, fleet active):

| metric | value |
|---|---|
| `nproc` | **1** |
| 1-min loadavg min / p25 / median / p75 / max | 4.59 / 5.57 / **6.25** / 7.69 / 9.52 |
| samples below the mandated ceiling of 2.0 | **0 / 40** |
| busiest processes | the five `qodercli` fleet sessions (~40% CPU) + tmux |
| cost of one 200-title prefetch sweep | ~60–100 s CPU + serialized HTTP ≈ **7–11% of the only core** continuously if daemonized at 15-min cycles |

So the spec's `< 2.0` gate is not "tight" here, it is **unreachable while the
fleet runs** — and that is the throttle working: a blocked sweep resolved zero
links in 300 s and logged why. What the mandate assumed was a box with idle
headroom; this box's idle is somebody else's peak. Deployment truth:

* **Prefetcher:** a **quiet-hours timer (overnight cron), not a continuous
  self-throttling daemon**, until an overnight loadavg sample provides a real
  idle baseline; then `--load-ceiling = measured_idle_median + 1.0`, exposed as
  the existing `--load-ceiling` flag. Never loosen the number to make the
  worker look successful.
* **Exporter:** cheap (read-only SQL passes, pages bounded; a 20-page export
  runs in well under a minute of CPU) — safe for an hourly cadence even at
  median load, and §4's exposure math assumes exactly that hourly cadence.

## 7. Re-checklist before EVERY publish (copy into the crown order that authorizes it)

- [ ] 0.1–0.6 prerequisites re-verified *at the commit being published*
- [ ] fresh build passed gates 1a/1b, manifest's
      `works_suppressed_by_canonical_key_clause` reviewed against expectation
- [ ] Emperor's approval quoted for the exact path + config snippet
- [ ] `nginx -t` output read by a human
- [ ] previous-good release retained (§5) and its stamp written in the order
- [ ] export cron scheduled **before** the symlink goes live, so §4's interval
      is a fact and not a hope

*Nothing past §1 has been run by any agent. Sections 2–3, 5 and the quarantine
step of 4 are `[APPROVAL-GATED]` and stay unexecuted until the Emperor answers.*
