# 2026-11-01 09:1x — q2 lane `[Q2-PROJECTION-TARGET-GUARD]`: #18's rebuild would happily have written a new catalog into the merge's input directory

**Lane:** q2 (`/tmp/q2_admin_auth`). **Branch:** `q2-census-pricing`, on top of `1481cf8`.
**Ruling obeyed:** Muse/supervisor 09:07 — `mode=ro` schema-only opens ARE LIGHT; content-table reads,
crawls, production writes and local Gradle stay FROZEN; gate HELD, qoder1 decides gate order, no
self-gating and no credential retry. Nothing in this segment touched a content table, and the census
still has no numbers.

---

## 1. The hole

`Fast_Fetch/project_readonly.py` is the queued #18 rebuild: it ATTACHes the production ledger
`mode=ro`, binds `posts`/`releases`/`download_sources`/`post_sources` to TEMP VIEWs, and lets
`catalog_v2.project()` write `cat_*` into a new file. Its path checks were: *not the same file*, and
*must not already exist*.

That is not enough, and the failure is specific. `OUT=/home/ubuntu/radd-stream-data/projection.db`
satisfied both checks and was accepted. A brand-new `.db` **inside the staging data dir** is not a
harmless scratch choice there:

* the next lane globs that directory for vaults (`adult_vault_census.py` reports `unpriced_on_disk`
  from exactly such a glob, and q3's premerge copy plan enumerates it), so a projection output becomes
  a *catalog* to whoever reads the dir next;
* it sits beside the live `merged_catalog_20261025.db` and `fast_fetch.db`, where a mistyped path
  lands one directory-visit away from the file the service is serving;
* if it were ever named like a merge input, it would join q3's copy set and be measured as a site.

The standing hazard rule says *print the resolved target before any write and stop if it names the
merged catalog or anything under the staging data dir*. The driver never did either. Now it does.

## 2. The guard, and the false positive it had to not create

`resolve_target(src, out, protected=None)` refuses — before any connection exists, and leaving no file
behind — when OUT: equals SRC, already exists, is named like a catalog/snapshot/credential file
(`FORBIDDEN_NAMES`, `merged_catalog_*`, `preapply_*`), or is **contained** in a protected directory.
`main()` prints `resolved target before any write: source=… (mode=ro) out=…` as its first line.

Two design notes, both learned from the tree rather than invented:

* **Containment, not prefix matching.** `/tmp/x/radd-stream-data-other/projection.db` is allowed even
  though the string starts like the protected name; the separator is appended before comparing.
  `test_a_data_dir_prefix_that_is_only_a_name_similar_is_allowed` pins it, because the version of this
  guard that refuses `/x-data-other` is the version that gets bypassed.
* **A scratch rebuild beside its own source stays legal.** `test_project_readonly.py` runs exactly that
  shape — `ledger.db` and `projection.db` in one temp dir — so a rule as naive as "OUT must not share
  SRC's directory" would have broken five green tests on the spot. I checked the fixture layout before
  writing the rule; that check is the only reason this is one push instead of two.

`protected_dirs()` is total on purpose: it lists the literal `/home/ubuntu/radd-stream-data` and *then*
adds `config.DATA_DIR` / `dirname(config.DB_PATH)` inside a `try`. An import that raises — including
the EACCES-on-`/home/ubuntu` shape that ended q5's run at `eb4c0ee` — falls back to the literal host
path instead of silently protecting nothing
(`test_the_data_dir_default_survives_an_unreadable_config`). The guard does no `exists()`/`stat()` on
the protected paths at all; it compares strings, so it cannot be defeated by an un-readable mount and
cannot become a filesystem probe of its own.

## 3. What this does and does not do for #18

It makes the queued run *safe to type*. It does **not** size it. The rebuild still needs a content read
of the production ledger — `project_readonly.py` prints `COUNT(*)` stamps for `posts`, `releases` and
`download_sources` as its first act — so #18 remains pending on a window, and the 09:07 ruling does not
change that. The next #18 slice, also CI-verifiable and still LIGHT-clean, is the same thing I did for
#37: price the projection from `sqlite_master` + `PRAGMA table_info` + `EXPLAIN QUERY PLAN` over the
four Layer-0 tables, because a rebuild whose driving statements plan `SCAN` on a 6.4 GB ledger is a
different window conversation than one that walks indexes.

## 4. Suite and cost

`test_project_readonly.py` registered at `backend-ci.yml:220`; now **15 cases** (6 in
`ProjectReadonlyTests`, 9 in `TargetGuardTests`). No CI registration change, no new module, no doc
index count change beyond this file.

Executed locally: `ast.parse` on both files, a static `ast` walk to count collected test names, and the
markdown-only doc mirror. **No test module was run** — the 09:07 ruling keeps local suites frozen and
the gate is qoder1's. The `--list`/arithmetic runs earlier in this session were `user 0.042 s`; nothing
here opens a database.
