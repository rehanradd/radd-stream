# 2026-10-31 — q2 lane, `[Q2-HUMTV-STATUS]`: the importer exists, and the crawl waits on load

Token: `Q2-HUMTV-STATUS` from qoder1. Light work only — one vCPU, load oscillating 3.1–4.2, so
nothing below was executed except a module import.

## Rotated verbatim from `Fast_Fetch/CONTINUITY.md` (former open items 8–9)

Moved out unchanged to keep the pointer file under the 12,000 B ceiling that
`Fast_Fetch/test_docs_invariants.py::ByteBudgetTests` enforces. Nothing reworded.

8. Landed tonight (docs): the documentation diet — the five auto-loaded files 779,799 →
   68,679 B (−91.2 %, `wc -c` on the rebased tree) as a conservation-checked SPLIT (nothing
   deleted), guarded by
   `Fast_Fetch/test_docs_invariants.py` (18 tests OK as of the merge-marker guard).
   `grep -c 'name: 🧪' .github/workflows/backend-ci.yml` = **32** at this merge — step 30 is
   `[Q3-OPS-READS]`'s `test_operator_read_bounds.py`, steps 31-32 are `[Q3-LADDER]`'s
   `test_engagement_ladder.py` and `test_operator_adult_projection.py`. Re-count it, never remember it.
   `checkpoints/20261030-04xx-q3-lane-the-documentation-diet-split-not-delet.md`.
9. **Trunk moved while the diet was open, and the rebase absorbed it rather than dropping it.**
   `q3-docs-diet` was rebased onto `4fe6f65`; the three doc edits written after the rotation are
   verbatim in `checkpoints/`, indexed above — q2's MovieBox detail-API session, and in
   `docs/checkpoints/` q4's `[Q4-SAFETY]` halt-band entry and q2's checkpoint entry. `SITES.md` §25
   was never rotated by this lane, so q2's corrected site notes are live in place. The merged CI was
   **29 `🧪` steps / 28 `python3 -S` matches** — the diet's guard ran last then; item 10 put
   `test_operator_read_bounds.py` after it and q2's `test_themoviebox_detail_api.py` sits where
   trunk put it.

## `[Q2-HUMTV-STATUS]` — measured 2026-10-31

- `Fast_Fetch/importers/import_humtv.py` (34,388 B) and `test_import_humtv.py` (17,990 B, **23**
  `def test` methods across 8 `unittest.TestCase` classes) exist on trunk as landed by `35f9e89`
  and are **byte-identical** to branch commit `296ac5e` (`git diff --stat 296ac5e origin/master --
  <both files>` is empty). No second importer was written.
- **Import-clean, measured:** `python3 -S -c "import sys; sys.path.insert(0,'Fast_Fetch/importers');
  import import_humtv"` → `import ok: import_humtv`, `site: humtv`, `main` callable. Module guard is
  `if __name__ == "__main__"` (line 867); the only module-level work is importing `fast_fetch` (path
  insertion, no DB open, no network).
- Deltas against the mission text, unchanged: default vault is `humtv_staging.db`, not `humtv.db`
  (the queued command passes `--db` explicitly); `synopsis` is written as `None`; no genre literal
  "Pakistani Drama" is set; the earlier bounded run stored 47 works / 205 releases, not the whole
  5,625-post catalogue.
- The 23-test module and the live crawl are **queued, not run** — one vCPU, load 3.1–4.2.

## The queued crawl, exactly (also rows 5–6 of the CONTINUITY "🕒 Queued" table)

```
nice -n 19 python3 -S Fast_Fetch/importers/import_humtv.py sync  --db /home/ubuntu/radd-stream-data/humtv.db
nice -n 19 python3 -S Fast_Fetch/importers/import_humtv.py crawl --db /home/ubuntu/radd-stream-data/humtv.db --workers 1 --delay 0.5
nice -n 19 python3 -S Fast_Fetch/importers/import_humtv.py verify --db /home/ubuntu/radd-stream-data/humtv.db --limit 200 --delay 0.4
```

- Expected cost: sync ≈ 57 REST pages × (0.3 s delay + RTT) ≈ 1–2 min. Crawl is one HTTP page per
  pending post, serial by construction (`workers != 1` is refused in code), so ≈ 5,625 pages ×
  (0.5 s delay + fetch) ≈ 2.5–4.5 h. Verify ≈ 5 min for 200 links.
- Stop condition: do not start unless load1 < 3.5; stop (Ctrl-C) if load1 crosses 4.0. The script
  also stops itself: `memory_ok()` refuses to start below MemAvailable 2,500 MB or SwapFree 800 MB
  and is re-checked mid-crawl; a 429 pauses the queue and leaves the row queued; Ctrl-C sets
  `STOP_REQUESTED` and the remainder stays `scraped=0`, so every run is resumable.
- Blast radius: the staging vault only — never `fast_fetch.db`, never the merged catalog.
