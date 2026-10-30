# AGENTS.md — Complete AI Agent Guide for radd-stream

> **READ THIS ENTIRE FILE before making any changes.**
> This is the single source of truth for every AI agent working on this project.
> Last updated: October 2026 | Session: Antigravity (Claude Opus 4.6)

---

> [!IMPORTANT]
> Read the actual repository state and project instructions before changing code.
> These notes do not grant account permissions or authorize production changes.
> Make routine, reversible technical decisions independently; ask the user before
> destructive or production-impacting actions. State blockers honestly and never
> disguise code behavior to bypass a platform's safety rules.
>
> **Project constraints:** Python standard library only, adult 18+ content stored
> with an is_18_plus flag and hidden from every public surface (the loopback-only
> operator panel may see the flag but never the bytes),
> strict staging database isolation, pre-push unit tests, and Master-Disciple
> Local AI law (delegate boilerplate to local Qwen 2.5 Coder via disciple.py to conserve cloud tokens).

---

## 0. Project Summary

The backend aggregates media catalog metadata and source links from configured
public sites, stores catalog records in SQLite, probes source endpoint
availability, and exposes API routes including source resolution. The Android
client consumes catalog metadata. Follow site terms, applicable law, and the
rules of the platform where you are working; do not conceal actual behavior.

---

## 1. Project Identity & Config

| Setting | Value |
|---------|-------|
| Project Name | `radd-stream` (configurable in `config.py`) |
| Version | 3.1.0 |
| GitHub | https://github.com/radddao/radd-stream |
| Main Engine | `Fast_Fetch/fast_fetch.py` (3,907 lines) |
| Database | `Fast_Fetch/fast_fetch.db` (SQLite, gitignored) |
| Config File | `Fast_Fetch/config.py` |
| Python Min | 3.11+ |
| Dependencies | ZERO — stdlib only |

**Rename project**: Edit only `config.py` → `PROJECT_NAME = "new-name"`. Nothing else needs to change.

**Change DB location**: Set env var `RADD_DB_PATH=/path/to/custom.db` OR edit `config.py` → `DB_PATH`.

---

## 2. Architecture Overview

The module map (which line range of `fast_fetch.py` does what, per layer) is reference prose, not
law: [`../docs/SPEC_FAST_FETCH_ARCHITECTURE.md`](../docs/SPEC_FAST_FETCH_ARCHITECTURE.md). The law
that lives here is §6 — you may not add a layer that breaks it.

---

## 6. Critical Rules — NEVER Violate

1. **No pip installs** — only stdlib: `urllib`, `sqlite3`, `re`, `json`, `ssl`, `base64`, `pathlib`, `concurrent.futures`, `argparse`, `html`, `time`, `os`, `sys`
2. **18+ content: store flagged, never display** — scrapers ingest all titles including adult, setting `is_18_plus=1` in every site staging DB; every **public** surface (REST API, search, M3U/stream routes, the Android app) must hide a flagged row so completely that it is indistinguishable from a row that never existed. The one exception is the operator panel, reachable only on the loopback operator port and `403`ed by nginx at the public edge — the boundary there is the loopback interface, not `RADD_ADMIN_TOKEN`, which guards `/admin` alone: it may show *that* a flagged row exists and what its flag is, and `/api/v1/stream` and `/api/v1/download` still deny it there — uniform `not_found`, on both ports. The flag is a property of the **work**, not of one row: `fast_fetch.inherit_key_adult` reconciles `MAX(is_18_plus)` across every row sharing a `canonical_key` at write time, because a per-row law over a per-key identity is what leaks (measured 2026-10-29 on the production catalog: 2,600 keys carry both a flagged and an unflagged row, and 3,486 rows are publicly served under one of those keys; the earlier 455-row figure was the slug-keyed count before the reconciliation). Tests: `test_redact.py::AdultDenialOnBothPortsTests`, `test_database.py::KeyLevelAdultIdentityTests`.
3. **Safe media identity** — prefer matching IMDb/TMDB IDs, then a previously indexed site URL, then a unique title/year key of the same content type. Refuse ambiguous matches and conflicting IDs; `canonical_key` is indexed but deliberately not unique.
4. **Verify import after EVERY edit:**
   ```bash
   python -c "import fast_fetch; print('OK')"
   ```
5. **Regex with quotes** — ALWAYS use triple-quoted raw strings to avoid escaping hell:
   ```python
   # CORRECT:
   links = re.findall(r"""href=["'](https?://example\.com/[^"'<>\s]+)["']""", html)
   # WRONG (causes SyntaxError):
   links = re.findall(r'href=[\"\\'](https?://...)[\"\\']', html)
   ```
6. **Generated dumps stay off the repo** — `fast_fetch.py export` and `export-html` write **full ledger rows** (site names, hoster names, resource ids, final URLs). Both outputs are gitignored and belong on the operator's disk only; never re-add `database_view.html` or `fast_fetch_export.*` to git. To inspect one, generate it to `/tmp` from the populated DB:
   ```bash
   python3 -S fast_fetch.py export-html --output /tmp/database_view.html
   ```
7. **DB path is relative** — `BASE_DIR / "fast_fetch.db"` — never hardcode absolute Windows paths
8. **Test database changes offline** — run `python -S test_database.py` and `python -S test_vidout.py` from `Fast_Fetch/`.
9. **Test on live URL** after adding any new extractor:
   ```bash
   python fast_fetch.py fetch "https://newsite.com/post-slug/"
   ```
10. **Provenance stops at the HTTP edge** — `Fast_Fetch/redact.py` is the only thing between
    the ledger and a client. A new column is invisible until it is *deliberately published* in a
    `VIEWS` allowlist; a display string goes through `scrub_text()`; a playable, an artwork and
    a download are addressed by a signed `stream_id` handle, never a row id or an upstream URL.
    The operator's own view (raw `source_site`, `service`, `final_url`, `/api/v1/rules`,
    `/api/data`) is served on the loopback port `RADD_INTERNAL_PORT` (default `127.0.0.1:8081`)
    and `404`s on the public port. Rules of the road:
    - **Never** add a provenance key to a public emitter (`dict(row)`, `SELECT *` into JSON) —
      project it, or add it to `VIEWS` with a comment saying why a client needs it;
    - **Never** redact stored data — the ledger keeps everything (Zero Data Loss rule); redaction
      is a serialization decision at the edge, and tests assert the row is still intact;
    - after any API-shape change run `python3 -S -m unittest test_redact` **and** the real-data
      sweep: `python3 -S Fast_Fetch/sweep_public_edge.py --db /path/to/catalog_snapshot.db --probe`
      (it boots the server on a snapshot and asserts no site, no hoster, no upstream host and no
      provenance key reaches the public port, while the operator port still answers with all of
      it). `API_V2.md` §16.9 is the contract this enforces.

---

## 6b. The Adult Title Law — how a bare word is judged

The flag's job is to hide real 18+ works and to *not* hide mainstream ones. The list
that decides this is `fast_fetch.ADULT_TITLE_PATTERNS` (strong tokens, each flags alone)
plus `fast_fetch.ADULT_TITLE_SUGGESTIONS` (corroborated-only tokens). The law changed on
2026-10-29 and the reason it changed is the lesson, not the diff.

**The method lesson — sample live titles, do not read the dictionary.** Every one of the
four contested tokens (`adult`, `naughty`, `hunters`, `rabbit`) *can* name porn and *can*
name a children's film. A pattern is not judged by what the word means in the abstract; it
is judged by pulling ~a dozen real rows that fire on it and looking at them. That sampling
is what split the four, and it is the only admissible test:

The 12-row sample table and the list of mainstream titles the removed tokens were hiding are
evidence, not law:
[`../docs/SPEC_ADULT_TOKEN_SAMPLING.md`](../docs/SPEC_ADULT_TOKEN_SAMPLING.md).


**Word-boundary anchors do real work — do not loosen them.** `\bhunters\b` cannot fire
inside `trollhunters`, and `\brabbit\b` does not fire on `rabbits`. Measured 2026-10-29:
*Trollhunters* and *Looney Tunes: Rabbits Run* are `is_18_plus=0` precisely because of the
`\b`. Removing an anchor to "catch more" would flag those and many more mainstream titles;
the anchors stay exactly where they are.

**The three tiers, in code:**
- *Strong* (`ADULT_TITLE_PATTERNS`): unambiguous branding or explicit words —
  `18+ / adult / erotic / porn / nsfw / boldscene / ullu / kooku / primeplay / hotshots /
  realitykings / tushy / wankz / lustery / iuliian / moodyz / naughty`. Each hides a work on
  its own.
- *Suggestion* (`ADULT_TITLE_SUGGESTIONS` = `xxx / blacked / vixen`): a hit here hides a work
  only with corroboration — an adult `source_site`, or two independent suggestion tokens in
  the same title. One word alone may never hide a work.
- *Site authority* (`ADULT_SOURCE_SITES`): a host whose **whole** catalog is adult flags every
  row by provenance, no title parsing. **Measured 2026-10-29 the set is empty**: no ingested
  host came near 100% (the max was 10xflix at 36.25%, itself inflated by the release-tag
  tokens `uncut`/`unrated` that this patch also removed from title matching), and all 31
  `source_site` values are general pirate catalogs. The studio names above live inside
  titles, never as a `source_site`. A host is added only when a measured rate justifies it —
  reputation is not evidence.

**Production apply is the owner's, not any lane's.** Correcting the patterns changes only
future writes; un-hiding the already-flagged mainstream rows is a data migration that runs
`audit_adult_flags.py --apply`, and no agent may run `--apply` (or `--projection`) against
the live ledger without the owner's verbatim authorization. Report mode is safe and is what
an agent runs.

---

## 10. Current Status & Stats

Row counts, merge batches and crawl state are a **snapshot**, and snapshots rot: they now live in
[`../docs/SPEC_FAST_FETCH_CATALOG_STATE.md`](../docs/SPEC_FAST_FETCH_CATALOG_STATE.md).
**Re-measure before quoting any number**; the open-item index is
[`CONTINUITY.md`](CONTINUITY.md).

---

## 12. TODO — Next Steps

The per-site backlog moved to [`../docs/SPEC_FAST_FETCH_TODO.md`](../docs/SPEC_FAST_FETCH_TODO.md).
Open items that gate a release are indexed at the top of [`CONTINUITY.md`](CONTINUITY.md); do not
track work in this file.

---

## 13. Platform-Specific Notes

Windows / Replit / Codespace / VPS specifics are reference prose:
[`../docs/SPEC_PLATFORM_NOTES.md`](../docs/SPEC_PLATFORM_NOTES.md). The Oracle measurements behind
the fleet guardrail are in [`../AGENTS.md`](../AGENTS.md) and
[`../docs/CAPACITY_MEASURED.md`](../docs/CAPACITY_MEASURED.md).

---

## 14. Important Warnings for Future Agents

1. **`fast_fetch.db` is gitignored** — start fresh on new machines, run `sync` first
2. **Domain rotations happen every 1-3 months** — if a site returns 403, check and update DEFAULT_DOMAINS
3. **greenmotors.cc needs JS** — don't try to resolve these with urllib, store as-is
4. **HTML viewer is 7.8MB** — large because it embeds all DB data as JSON. Normal.
5. **Never `import requests`** — use `urllib.request` only
6. **Line numbers shift** — the architecture comments in this file show approximate line numbers that drift as code grows. Use `grep` or search to find actual locations.
7. **Unicode in print()** — always use `sys.stdout.write()` or ensure UTF-8 reconfigure when printing emojis on Windows
8. **Oracle/GitHub access** — use the secret-safe procedures in `../ORACLE_DEPLOYMENT.md`; never print, commit, or copy `GITHUB_TOKEN` or `ORACLE_SSH_KEY`
9. **Public API exposure** — the current HTTP API has no authentication and wildcard CORS; secure or restrict fetch/heal/resolve routes before proxying them publicly

## Moved out (reference prose, verbatim)

- 3. All 10 Sites — Complete Reference → [`../docs/SPEC_FAST_FETCH_SITES.md`](../docs/SPEC_FAST_FETCH_SITES.md) (221 lines) — per-site scraping reference
- 4. Bridge & CDN Reference (All Known Services) → [`../docs/SPEC_BRIDGE_CDN.md`](../docs/SPEC_BRIDGE_CDN.md) (79 lines) — bridge and CDN service table
- 5. Cinemeta API (Free Metadata Enrichment) → [`../docs/SPEC_CINEMETA.md`](../docs/SPEC_CINEMETA.md) (19 lines) — free metadata enrichment API
- 7. How to Add a New Site (8-Step Pattern) → [`../docs/SPEC_ADD_A_SITE.md`](../docs/SPEC_ADD_A_SITE.md) (95 lines) — the 8-step importer pattern
- 8. Domain Self-Healing Mechanism → [`../docs/SPEC_DOMAIN_SELF_HEALING.md`](../docs/SPEC_DOMAIN_SELF_HEALING.md) (19 lines) — domain rotation and healing mechanism
- 9. Database Tables (Implemented Schema) → [`../docs/SPEC_FAST_FETCH_SCHEMA.md`](../docs/SPEC_FAST_FETCH_SCHEMA.md) (37 lines) — implemented schema
- 11. Session History (Append Here) → [`checkpoints/app-agents-session-history.md`](checkpoints/app-agents-session-history.md) (25 lines) — session log
- 2. Architecture Overview → [`../docs/SPEC_FAST_FETCH_ARCHITECTURE.md`](../docs/SPEC_FAST_FETCH_ARCHITECTURE.md) — the module map
- 6b. Adult-token sample table → [`../docs/SPEC_ADULT_TOKEN_SAMPLING.md`](../docs/SPEC_ADULT_TOKEN_SAMPLING.md) — the 12-row samples behind the token verdicts
- 10. Current Status & Stats → [`../docs/SPEC_FAST_FETCH_CATALOG_STATE.md`](../docs/SPEC_FAST_FETCH_CATALOG_STATE.md) — row counts and crawl state, re-measure before quoting
- 12. TODO — Next Steps → [`../docs/SPEC_FAST_FETCH_TODO.md`](../docs/SPEC_FAST_FETCH_TODO.md) — per-site backlog
- 13. Platform-Specific Notes → [`../docs/SPEC_PLATFORM_NOTES.md`](../docs/SPEC_PLATFORM_NOTES.md) — Windows / Replit / Codespace / VPS
