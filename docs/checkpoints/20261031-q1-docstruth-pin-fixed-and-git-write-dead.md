# 2026-10-31 ~07:15 — qoder1 supervisor `[Q1-DOCSTRUTH]`: q5's citation re-pin verified and merged, one self-failing guard pin fixed, and git write is dead again while the API is not

Lane: qoder1 (Chief Supervisor / gatekeeper). Docs-only landing. No `.py` behaviour file,
no database, no service, no tag, no build.

---

## 1 — what landed, and how each claim was checked rather than accepted

`q5-adultkey-docs-truth` (`4bc6264`, authored 07:07) re-pins the root `AGENTS.md` adult-law
citations that the corroborated-fold merge moved, and adds the sentence naming that
reconciliation. Before merging I read **all nine cited lines out of trunk `d97980f4`**:

| Citation | What is actually on that line |
|---|---|
| `fast_fetch.py:4598` | `data["is_18_plus"] = int(` — the title re-derivation |
| `redact.py:1077` | `def adult_clause(alias: str = "posts") -> str:` |
| `redact.py:1083` | `def link_is_adult(source_id: int, db_path) -> bool:` |
| `viewer.py:2780` | `def api_v1_get_posts(query: str = "", content_type: str = "", page: int = 1,` |
| `viewer.py:887`, `:2956` | both `if not post or post["is_18_plus"]:` — the two per-post bails |
| `viewer.py:917` | `DASHBOARD_HTML = """<!DOCTYPE html>` |
| `viewer.py:557` | `def fetch_database_payload(search_query: str = "", full: bool = False,` |
| `viewer.py:1919` | the `🔞 18+ ADULT` badge template |

Nine for nine resolve. `AGENTS.md` is 30,324 B against its 32,000 B ceiling. The sentence
about `link_is_adult` answering True for an unknown link id is now true **of trunk** — the
fail-closed flip shipped in `4a8c163` — which is the distinction the production note below
exists to keep people from blurring.

## 2 — the defect in the branch, fixed inside the merge commit

The commit added one phrase pin to `Fast_Fetch/test_docs_invariants.py`:

```python
"merge_catalogs.reconcile_adult_on_merge() folds a work's flagged row onto its siblings only"
```

while `AGENTS.md` carries that law sentence **with two backticks**:

```
`merge_catalogs.reconcile_adult_on_merge()` folds a work's flagged row onto its siblings only
```

The guard compares with `flat(phrase) in flat(text)`, where `flat` is
`re.sub(r"\s+", " ", text)` — whitespace-normalised, punctuation **not** stripped. So the
pin could never match: a backtick sits between `)` and ` folds` in the file and nowhere in
the pin. I proved it by replicating those two lines in a throwaway script (`pin found:
False`) before spending any process, because the failure mode of a docs guard is a red
`🧪 test_docs_invariants.py` on trunk after a "docs only, no suites run (load ~6)" commit.
The branch's own message says no suites were run — that is exactly how this survived.

Fix: the pin now quotes the file verbatim, backticks and all. No existing pin was touched,
no assertion weakened, no skip added.

## 3 — a stale sentence I owned, retired

`Fast_Fetch/CONTINUITY.md` item 15 still said the fold's *tests were "queued under the load
freeze"*. They had run: hosted run `41156831610`, all 39 steps, then the merge. Item 15 now
reads `green on 41156831610, landed 4a8c163; **production still pre-law**`. The clause was
**compressed**, not extended: `CONTINUITY.md` is 11,991 B / 109 lines against a
12,000 B / 120 line ceiling enforced by the guard, i.e. 9 bytes of headroom, so there is no
room for a longer pointer and I did not shorten any other lane's line to manufacture room.

## 4 — gate

`python3 -S Fast_Fetch/test_docs_invariants.py` → **18 tests OK**, run twice at `nice -n 19`
(1.3 s in a candidate worktree at `4bc6264` with only the pin fixed, then 2.9 s on the merged
tree). That module is markdown-only — no network, no catalog, no DB — which is why it was
allowed at all while load measured 3.83–4.40; nothing else was started. No Gradle, no crawl,
no merge job, no production read.

## 5 — refused, and why

- **`q5-adultkey-prod-gap` (`36a47a2`)** — an 87-line `Fast_Fetch/checkpoints/` file whose
  facts already shipped verbatim in
  `docs/checkpoints/20261031-q1-supervisor-the-adult-gate-landed-and-production-is-stale.md`,
  plus a `CONTINUITY` count bump to 58 that a 9-byte-headroom file cannot absorb without
  cutting another lane's line. Its one genuinely new truth — item 15's stale clause — is
  landed here instead. The branch stays on the remote as q5's record; standing it down does
  not delete it.
- **`q4-player-zero-buffer-20261031` (`269fec0`)** — needed no gate: `ahead=0/behind=13`
  against trunk and `merge-base == its own tip`, i.e. already an ancestor of `d97980f4`. Its
  `git diff --shortstat` against trunk reads **3,440 deletions**, which is pure lineage, not
  a finding. Rule for every lane: never judge a branch by a shortstat against a moving head;
  compute the merge-base first.

## 6 — the blocker: git write is dead while the API is not

`git push` to the explicit clean URL through the `ORACLE_DEPLOYMENT.md` askpass flow failed
**three times, identically** — `master`, then `main`, then my own lane branch
`q1-docstruth-20261031` — all `Invalid username or token. Password authentication is not
supported for Git operations.`

Measured, not assumed:

- `GET /user` with `$GITHUB_TOKEN` → **200**. `GET /repos/rehanradd/radd-stream` → **200**
  (and **200** anonymously, because the repo is public, so that read proves nothing about the
  token).
- The value is well-formed: 40 chars, `ghp_`-class. Never printed, only classed.
- The askpass provably ran: a variant that logged only the prompt *strings* recorded
  `Username for 'https://github.com':` and `Password for 'https://x-access-token@github.com':`
  and nothing else was consulted — no credential helper is configured (local and global both
  empty). So this is GitHub refusing the credential for **git operations**, not a stale helper
  shadowing it, and not a transport fault.
- Timeline on this box: my own trunk push succeeded at **07:03** (`d97980f`), and the first
  refusal is at **07:13**. A token that reads 200 on `/user` and is refused for `git push`
  with that message is the shape of a **narrowed or re-scoped credential** (repo write
  removed) rather than a deleted one.

**Consequence, stated plainly:** the landing is **local only**, on durable branch
`q1-docstruth-20261031` at `c06da68`, parent `d97980f` — fast-forwardable onto both refs the
moment a write credential returns (`ls-remote` still reads `main` = `master` = `d97980f`,
verified after the failures). Trunk is not red and not broken; it is simply missing one docs
re-pin and one stale sentence retired. I did not retry a fourth time, did not borrow another
account's process environment, and did not touch `origin`, whose stored URL still carries the
owner's unrevoked token.

**Next agent with a live write credential:** `git push <clean URL> q1-docstruth-20261031:master`
and the same to `main`, then confirm `backend-ci.yml` green at that head — the docs guard is
the only step this can move.

## 7 — what is still owed by the lanes as of this pass

- **qoder3** — no `q3-coins-engine` branch exists on the remote; the coins work is running a
  `test_database.py` from `/tmp/q3_coins` **during a load freeze** (seen again at 07:1x).
  Owed: a real branch + sha, and suites stopped until I post load under 4.
- **qoder4** — owed the read-only completeness verdict on `q4-fav-recheck-rescue` (`583fd54`,
  260 added / 0 deleted, explicitly ungated) — specifically whether `AppDatabase` carries a
  Room migration for the `checkedAt` column that `FavoriteDao.recordAnswer` writes. The build
  I asked for is **withdrawn**; no Gradle until load is under 0.5.
- **qoder2** — the Hum TV ingest into `humtv.db` and the census `--census` numbers, both frozen.
- **Owner, not any agent** — the running service is still pre-law: the live tree carries no
  `adult_fold_journal`, `redact.py` there is still fail-open, and its `viewer.py` is 466 lines
  shorter than trunk's. Deploying that is a restart of `radd-stream.service`, which no agent
  may perform.

## Rules kept

No `.py` behaviour file touched (only a test *string literal*), no service restart, no nginx
change, no tag, no `git add -A`, no credential printed or logged, one module at a time at
`nice -n 19`, no build, no production read, work done in `/tmp/q5docs_gate` and
`/tmp/q1_docs_pass3` — never in `/opt/radd-stream`.
