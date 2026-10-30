# Session 2026-10-29 (qoder5 backend lane) — "Uncut" was never an adult word `[Q5-UNCUT-FALSEHIDE-P1B]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-29 (qoder5 backend lane) — "Uncut" was never an adult word `[Q5-UNCUT-FALSEHIDE-P1B]`

**What the owner found.** He ran my key-level backfill against prod at 10:48. The flip
verified mechanically (135,779 → 135,324 public), but the audit line next to it said the
truth: `flipped, adult by their OWN stored text = 0`, `flipped ONLY because a SIBLING
matched a pattern = 375`, `flipped, no pattern anywhere = 80`, and inside those siblings
`\buncut\b` appeared **300** times. Uncut and Unrated are *edition* vocabulary — they live
in `release_descriptor.py`, `catalog_api.py`, `catalog_v2.py` and every SEO slug regex — and
the site writing them is desicinemas, so the works they hid were mainstream Indian cinema
(Kanguva, Hi Nanna, Guntur Kaaram, Junior, Election, Double iSmart, Das Ka Dhamki, Gangs of
Godavari, Kannur Squad, DeAr, Dharmaveer 2, Ratham, Yaathisai, Extra Ordinary Man). **He
was right that my design amplified someone else's bad pattern**: per-key reconciliation
means one mislabelled sibling now buries every copy of a work, so a false positive stopped
being one hidden row and became one hidden film. He reversed his own damage (preimage
`/home/ubuntu/radd-stream-backups/adult_flip_preimage_20261029_104859.json` + `.ids`, kept 48 genuine
flips, undid 407, journal `adult_flip_rollback_journal.txt`); prod is back to
posts 150,799 / `is_18_plus=1` 15,068 / public 135,731.

**Scale, measured read-only by the owner before this fix:** of 15,068 flagged rows,
**7,663 (51%) were justified only by `uncut`/`unrated`**, 2,647 match no adult pattern at all
(tags, `raw_meta`, or a site-wide rule), and the true-adult markers run
`18+ 3,309 | adult 1,480 | ullu 807 | naughty 169 | hunters 128 | xxx 73`.

**The fix.** `r"\buncut\b"` and `r"\bunrated\b"` are gone from `ADULT_TITLE_PATTERNS`
outright — no context-gating, no co-occurrence rule, because I could not write a test showing
one catches anything the remaining patterns miss. The redundant `r"\b18\+"` collapsed into
`r"\b18\s*\+"`. Nothing else in the list changed and no parser, site or pattern was deleted.
The same two words were in **seven other lists** that the brief did not name, and leaving them
there would have kept the bug alive at the ingest boundary: the inline `adult_patterns` in
`extract_post_data_multimovies`, and the per-site lists in `import_9xmovies`, `import_bolly4u`,
`import_world4ufree`, `import_moviezguru`, `import_filmyzilla`, `import_multimovies`. Corroborated
by the already-merged `importers/test_filmiyin_import.py::test_uncut_is_not_adult_on_this_site`.

**Tests (88 → 119 in `test_database.py`).** Both directions pinned on the real shapes:
`Kanguva (2024) HDRip Uncut HD` → 0, `Hi Nanna 2023 Unrated Director Cut` → 0, the named films
→ 0, and the slug `kanguva-2024-hindi-uncut-hd-download` stored through `save_scraped_data` →
`is_18_plus=0` and still publicly served; `Something 18+ Adult Erotic` → 1, `Ullu` → 1, an adult
studio carrying the word "uncut" → 1. The law added in P1 is re-proved *after* the pattern
change: a flagged twin hides the key, an unrelated key does not leak across. Plus an AST guard
that sweeps every non-test module for any `*adult*`-named list literal still holding a version
word — **proven non-vacuous** by re-adding the pattern and watching it fail (the first version
of that guard was vacuous: `re.findall(r"[a-z]+", "\buncut\b")` returns `['b','buncut']` because
a backslash is not a letter, so it stripped regex punctuation first).

**The un-flag tool is written and pointed at nothing but temp databases.**
`Fast_Fetch/audit_adult_flags.py` classifies every flagged row as
`true-adult-in-stored-text` / `version-word-only` / `no-stored-evidence`, resolving the last
class from the source site's own staging vault (`config.DATA_DIR/<site>.db`, opened lazily per
site), and reports. Only `version-word-only` rows are candidates, and only where no sibling
under the same `canonical_key` carries true-adult evidence. **I did NOT mass-unflag the 7,663**
— that is an exposure event and the owner's to run. `--apply` refuses without `--owner-go`,
refuses the live catalog without `--prod`, and fsyncs then re-reads a
`(id, canonical_key, old flag)` preimage before the first UPDATE, self-verifying
flipped == rows and public-total change == rows, else rolling back.
One finding from building it, and it cuts the other way: freeing a `version-word-only` row whose
sibling is flagged-but-unresolved **re-opens a mixed key** — one copy served, one still hidden.
The tool always reports `mixed_keys_after`, and `--require-clean-siblings` is the tighter law if
the owner wants no key left mixed at the cost of deferring rows.

**TLS, the appended task.** The engine held a module-level `SSL_CONTEXT` with
`verify_mode = CERT_NONE` and two resolvers rebuilt the same context by hand — three copies of
one decision, and no way to make a single host stricter. Now `config.tls_context()` is the
project's only SSLContext factory (cached per policy, not per host, because building one reloads
the CA store and the crawl calls it per request), `RADD_TLS_VERIFY` ∈ permissive|strict
**defaults to today's permissive handshake so nothing changes behaviorally**, and
`RADD_TLS_VERIFIED_HOSTS` graduates one host at a time to a real certificate check. All
**eight** policy-bearing call sites in `fast_fetch.py` route through `_tls_context` (six
`urlopen`, two `HTTPSHandler` — AST-counted, parent and child both 6+2, so the commit moved
posture for nothing and changed behavior for nothing), and `_tls_context` takes the
**strictest** peer when a call knows more than one host. `TlsPolicyTests` mints a self-signed cert with openssl and
serves it on 127.0.0.1 to prove the no-downgrade law: a listed host presenting an untrusted chain
raises `URLError(reason=SSLCertVerificationError)` instead of returning the body, and
`http_get` returns status 0 with no bytes. AST guards, not line matching: no
`create_default_context()` / `CERT_NONE` / `SSL_CONTEXT` may appear in `fast_fetch.py` again, and
every `urlopen`/`HTTPSHandler` `context=` must be a `_tls_context(...)` call (a *missing*
`context=` is accepted — urllib's default verifies, which is the safe direction).

**What I did not do, on purpose:** the default is still permissive — flipping it is the owner's
decision, and this report is the input for it. The de-duplication stops at `fast_fetch.py`,
which is the file the brief named: **25 more hand-rolled permissive contexts still exist** in
other owners' modules (`bridge_tracer`, `domain_resolver`, `site_scout`, `link_health`,
`scrape_multimovies_full` and 20 importers — AST-verified `verify_mode = ssl.CERT_NONE`
assignments on `ab78849`). Rewiring 25 other lanes' files under a privacy fix is exactly the
scope creep that breaks a shared tree; they should move to `config.tls_context` in their own
commits. `link_health.py` keeps its own context so the
prober stays loadable without the 4k-line engine; its comment now says the `verify=True/False`
flag used by `link_health` and the `unwrap_*` resolvers is **link-resolution** probing (a
512-byte Range request asking whether bytes exist), not TLS, and can neither enable nor disable
certificate checking.

**Two measured facts the owner needs for the strict-default decision.** (a) The bad-chain
population cannot be enumerated offline, and I did not hammer third-party sites to guess it:
**64** `.log`/`.txt`/`.out` files under the data dir and `journalctl -u radd-stream` together
record **zero** `certificate verify failed` / `SSLCertVerificationError` / hostname-mismatch
lines — which is expected, not reassuring,
because verification has essentially never been attempted on these paths. What the code *does*
name is the canary set: **121 distinct hostnames** appear in `https://` literals across the
non-test modules (measured on `ab78849`), so that is the list to move through
`RADD_TLS_VERIFIED_HOSTS` in batches, one host at a time, watching the crawl log. (b) The
permissive default is not actually engine-wide and never was: **three `urlopen` calls in
`fast_fetch.py` pass no context at all** — the TLD mirror auto-discovery at `:375`, the
Range/latency media probe at `:4942`, and the domain-health CLI at `:5816` — so they have always
used Python's verifying default and still do; AST comparison of parent vs child is 6+2 policy
sites and 3 context-less sites on both sides. Two consequences: those paths are living evidence
that at least some of this fleet completes a verified handshake, and `RADD_TLS_VERIFY=permissive`
is **not** a total rollback switch — it cannot make those three permissive, and I am not going to
make them permissive to fix that ("never set CERT_NONE anywhere new").

**Gate.** Ran CI's real 16-module list, one module per invocation, from a **clean worktree of the
shipping commit** (`git worktree add -d /tmp/q5_gate ab78849`, tree clean before and after):
`test_database` 119, `test_vidout` 6, `test_catalog_v2` 91, `test_release_descriptor` 24,
`test_link_health` 57, `test_link_state` 28, `test_evidence_writeback` 12, `test_api_v2` 46,
`test_redact` 58, `test_tiers` 23, `test_catalog_api` 127, `test_provenance_stamping` 12,
`test_merge_catalogs` 5, `test_site_scout` 25, `test_backup_manager` 14,
`importers/test_host_resolvers` 171 — **939 tests, 16/16 OK, 0 failures.**

**Push state.** `ab78849` pushed to `refs/heads/master` and `refs/heads/main` (both were at
`c401021`), fast-forward, via the temporary askpass helper; `git ls-remote --heads` confirms both
refs at `ab7884923215d07ab7ea24b5ec50ab31077b1457`. Production untouched throughout: no write to
`merged_catalog_20261025.db`, no backfill re-run, no restart of `radd-stream`.

**Still standing after this session:** (1) the owner runs the un-flag pass with `--owner-go`;
(2) the re-key migration is still design-and-blast-radius on paper first — under the correct
identity prod has **2,600 keys carrying both a flagged and an unflagged row, 3,486 publicly
served rows under those keys, and a 69,773-row re-key blast radius**; (3) **HOLD** — no merge
batch 4 and no kuttymovies/DesiSerials ingestion into prod until the un-flag pass has run, or
the poisoned pattern gets re-imported through the projection rebuild.

