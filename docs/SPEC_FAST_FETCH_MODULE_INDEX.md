# SPEC — Fast_Fetch module index (generated, not hand-kept)

> Generated 2026-11-05 by the crown docs pass from `git ls-tree origin/master Fast_Fetch/`, one
> entry per non-test module, each described by **its own first docstring line** (or its own header
> comment, marked `[header comment]`). No purpose here is the editor's inference. Regenerate with
> `python3 -S Fast_Fetch/gen_module_index.py` rather than editing this file — a hand-kept index
> drifts the moment a module is added, which is exactly how the auto-loaded guides ended up naming
> 14 of 61 modules.

**61 non-test modules at trunk `b99814e`.**

## Core modules (22)

- `accounts_api.py` — accounts_api.py — the HTTP edge for optional sync accounts
- `admin_panel.py` — admin_panel.py — the operator's control surface over the `cat_*` projection
- `api_v2.py` — api_v2.py — the v2 wire layer (API_V2.md §12), mounted by viewer.py
- `arena_tournament.py` — arena_tournament.py — Multi-Model Architecture Arena & Evaluation
- `audit_adult_flags.py` — Sort every `is_18_plus=1` row by the evidence that actually justifies it
- `audit_staging.py` — Read-only inventory of the per-site staging databases
- `backfill_adult_key.py` — Reconcile `posts.is_18_plus` across rows that share one work identity, and report
- `backfill_animated_flag.py` — Backfill `posts.is_animated` across a database that was ingested before the
- `backfill_tmdb.py` — Backfill artwork and identity metadata from TMDB, with a keyless Cinemeta
- `check_doc_citations.py` — Doc-citation drift check: does every `file.py:NNN` in the API docs still point
- `config.py` — [header comment] *- coding: utf-8 -*
- `domain_resolver.py` — [header comment] Detect if domain changed via redirect
- `media_search.py` — Match a video file the viewer is holding to a work in our catalog
- `merge_fleet.py` — merge_fleet.py — merge every per-site staging database into one fresh catalog
- `migrate_search_indexes.py` — Reviewed migration: the two indexes the by-media search measurement asked for
- `partner_api.py` — Partner API skeleton — `/api/partner/v1/**`
- `project_readonly.py` — Project the v2 catalog from the live ledger without writing to it
- `release_descriptor.py` — release_descriptor.py — deterministic free-text -> structured "print" parser
- `run_backup.py` — Off-site backup runner: every catalog database that is safe to read right now
- `sweep_public_edge.py` — Real-data leak sweep — the operator's gate before an API change ships
- `usage_stats.py` — Operator-only usage analytics: installs, live devices, retention, money
- `validate_catalog_full.py` — Audit a projected catalog against everything API_V2.md promises, on real data

## Per-site importers (2)

- `import_multimovies.py` — Resumable, rate-limited import of MultiMovies catalog and public source links."""
- `rederive_katmoviehd.py` — Re-derive KatMovieHD page identities from the raw evidence already in the ledger

## Modules with no docstring and no header comment (37)

Every one of these is a module an agent is expected to reason about from its name alone. This is a
**known documentation debt, listed rather than papered over**; a one-line docstring per module is
cheap and each one is checkable against the code that calls it.

- `accounts.py`
- `auto_chat_sync.py`
- `backup_manager.py`
- `bridge_tracer.py`
- `catalog_api.py`
- `catalog_v2.py`
- `disciple.py`
- `engagement.py`
- `export_chat.py`
- `fast_fetch.py`
- `import_10xflix.py`
- `import_7starhd.py`
- `import_9xmovies.py`
- `import_bolly4u.py`
- `import_desicinemas.py`
- `import_filmyzilla.py`
- `import_hdhub4u.py`
- `import_hdtvb.py`
- `import_hindilinks4u.py`
- `import_katmoviehd.py`
- `import_moviezguru.py`
- `import_rareanimes.py`
- `import_rogmovies.py`
- `import_ssrmovies.py`
- `import_toonworld4all.py`
- `import_vegamovies.py`
- `import_world4ufree.py`
- `link_health.py`
- `link_state.py`
- `merge_catalogs.py`
- `payments.py`
- `redact.py`
- `restamp_provenance.py`
- `scrape_multimovies_full.py`
- `site_scout.py`
- `tiers.py`
- `viewer.py`

*(generated; 61 modules scanned, 24 self-describe)*
