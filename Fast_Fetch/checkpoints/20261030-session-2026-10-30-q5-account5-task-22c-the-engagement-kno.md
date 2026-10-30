# Session 2026-10-30 (q5 account5 — Task #22c: the engagement knobs are admin-controllable) `[Q5-ENGAGE-KNOBS]`

> rotated out of `Fast_Fetch/CONTINUITY.md` by the 2026-10-30 documentation diet; text unchanged.

## Session 2026-10-30 (q5 account5 — Task #22c: the engagement knobs are admin-controllable) `[Q5-ENGAGE-KNOBS]`

Deliverable (c) of #22, on a fresh worktree off the tip q3's search lane pushed (`git worktree add
/tmp/q5-monet-fields-live 1d483ee`, branch `q5-engagement-knobs-20261030`). The four pillars from
`eebdec8` now have 16 knobs in `MONETIZATION_FIELDS` (17 fields → **33**, `admin_panel.py:1076`) and one
published block in `remote_config()`, so an ad cadence, a coin cost, a streak grant and the PKR ladder are
changed in `/admin` instead of by a code push. Full spec update in
`docs/MONETIZATION_PILLARS_SCHEMA.md` §11; the shape and every number in it are one assertion away from
drift (`test_the_engagement_block_is_the_ledgers_own_projection`).

**Landed on a newer base than it was written on — six shas, five CI gates.** `a638e03` was gated green on
`1d483ee` (run `40945093282`), but by the time the run came back `master`/`main` had moved to `87b7b6f` (the
search lane's `test_posts_query_plan.py`, the MovieBox importer, four doc corrections), so it was
cherry-picked onto `87b7b6f` as `41cb049` and gated again (run `40945927750`, `completed success`). That came
back green while the refs sat at `079fcbb`/`7b7a31e`; cherry-picked there as `582e2c3`, gated a third time
(run `40946874655`, `completed success`, **20** `🧪` suite steps success, none skipped) — and the refs had
moved again, to `52f08b0`, so it became `fec8910`, gated a fourth time (run `40948111468`, 20/20). That came
back to find `c3459b3` (Q4's adult-twin probe: a new test module plus **8 lines in `backend-ci.yml`**, making
the list **21**), so it became `3f5bb8a`, gated fifth (run `40949404738`, `completed success`, **21** suite
steps, none skipped) — and that came back to find `54662d2` (Q4's capacity doc, no Python), which is the base
under this entry. **The pattern is the fleet fact worth recording: while one lane pushes every five to eight
minutes and a Backend CI run takes about nine, a strict "gate the exact sha, then fast-forward" landing loses
the race by construction.** Nothing was ever forced, reset or merged around it — each step was a fresh
cherry-pick onto the tip and a non-forced push, which Git rejects outright if the tip moved in between, so a
silent revert of another lane's work was never possible. No intervening commit touched `admin_panel.py`,
`test_admin_panel.py` or `engagement.py`; `git diff 3f5bb8a -- Fast_Fetch/admin_panel.py
Fast_Fetch/test_admin_panel.py Fast_Fetch/engagement.py docs/MONETIZATION_PILLARS_SCHEMA.md` on this landing
commit is **empty** — the module content is byte-identical to what CI gated fifth.
`test_admin_panel.py` + `test_engagement.py` were re-run on the landing base anyway: **90 OK**. The only
conflicts were tail appends to `CONTINUITY.md` and `docs/SESSION_CHECKPOINT.md`, resolved by keeping the other
lane's entry and putting mine after it. **This paragraph's own count went stale twice more while it was being
written, which is the honest end of the story:** the base kept moving by other lanes' commits, each of them
docs-only and none touching `admin_panel.py`, `test_admin_panel.py` or `engagement.py`, so each landing was
another cherry-pick onto the newest tip plus another hosted gate, and the count of shas and of CI runs in this
entry should be read as "at least this many". Not one of them was forced, reset, merged or `--no-verify`d, and
not one of them overwrote a byte of another lane's work — a non-forced push to a ref that had moved is simply
rejected, which is the property that made this whole sequence safe rather than merely tedious. **Fleet note for
the orchestrator:** with one vCPU and a Backend CI run of six to nine minutes, any lane that commits at a
cadence shorter than that makes "gate the exact sha, then fast-forward" unwinnable by construction; the fix is
an eight-minute docs freeze on the landing refs, not a weaker gate.

**What the diff is.** A new field kind `_INT = "count"` (`:1060`) for whole numbers that are neither money
nor flags, with its branch in `_column_ddl` (`INTEGER NOT NULL DEFAULT <n>`, so both CREATE and the
`PRAGMA table_info`-guarded ALTER build the same column from the same spec) and its branch in `_validated`
(refuses a bool — `True` is `1` to Python and a count is not a flag — a negative, a non-number, and
anything over its ceiling). `_MAX_INT` refuses a paste that cannot be a setting; `_INT_MAX` (`:1169`)
refuses the four the consumer would silently rewrite: `engagement.CAP_MAX`'s 1440/5000 and `_clamp_hour`'s
0..23. A saved number, a published number and an enforced number are the same number or the save fails.

**Two decisions worth the reading, because they are the ones a later lane could "fix" wrongly.**

1. **`remote_config()["engagement"]` is `engagement.remote_view()` with the operator's row applied over
   it** (`_engagement_public`, `:1505`) — not a block invented in the settings module. §4/§6 of the design
   doc had sketched `ads.cadence` plus a `wallet` shape written twice; what landed reuses the projection
   `engagement.py` itself promised at `/api/v1/app/remote-config.engagement`, so on an untouched
   deployment the two dictionaries compare **equal**, and the equality is the drift guard. `ads.cadence` is
   retired from the doc. `admin_panel` already imported `payments`, `accounts` and `usage_stats`, so
   importing `engagement` breaks no layering; the earlier plan's "the settings module must not import the
   ledger" argument did not survive contact with the file.
2. **A stored `0` means "use the default", never "unlimited" and never "free"** — the owner's rule, and it
   is resolved by the consumer's own `resolve_caps`, not by a copy of its logic. Two honest exceptions,
   both written down where they are read: `streak_day_boundary_hour` 0 is **midnight** (a real rollover,
   so `_rollover_hour` publishes it), and PKR prices are published exactly as stored because nothing
   clamps a price — the same treatment `vip.monthly_pkr` already gets. `pass_monthly_vip_pkr` **250** is
   the plan doc's number for the 30-day *pass* and is a different product from `vip_monthly_pkr`, the
   *membership* price `payments.py` reads; two knobs, and a test keeps them from being linked.

**The landmine, measured.** `_column_ddl` creates every text column `DEFAULT ''` whatever the field spec
says, so a fresh row's `streak_tz` stores `''` and a non-empty spec default would never reach the row. The
fix is in the projection (`zone or <spec default>`), not in the DDL: an empty string means "never typed",
and the client is given the zone `_day_bucket()` will actually roll days with. No existing column changed,
so a row already on disk is untouched apart from the additive ALTER.

**`_count` collision — the defect this session found in its own diff.** The first version of the settings
helper was named `_count`, which silently shadowed `admin_panel._count(conn, table)` (`:539`), the row
counter every projection screen uses. My own 65-test file stayed green; the shadowing surfaced only in
`test_operator_isolation.py` as **four 500s** (`/admin`, `/admin/api/projection`, the evidence writeback)
with the detail swallowed by `GENERIC_ERROR`. Reproduced the failure in a clean `1d483ee` worktree to prove
it was mine (base: OK), got the real traceback by monkeypatching `_problem`, renamed it
`_setting_count`, and both suites are green again. Two rules came out of it: no new module-level helper in
this file without a duplicate-name check (`ast` over the tree, top-level dupes: none), and a full-file run
before any push, not only the new tests.

**Not wired, and said out loud.** Three published numbers are still read from `engagement`'s constants on
the *server-side enforcement* path: `engagement.py:534` (`REWARDED_DAILY_CAP`), `:710`
(`STREAK_GRANTS_COINS`), `:753` (`PASS_LADDER[plan]["coins"]`). `ad_grant(caps=…)` already accepts
overrides, so the cadences bind the moment a route hands it the row; the other three need a
caller-side parameter, which belongs with the route that owns each spend and is a follow-up brief — not an
edit smuggled into a settings commit. **The direction of the gap is the reason it cannot be shrugged
off:** an operator who *lowers* `coin_redeem_day` today publishes a price more forgiving than the 30 coins
the ledger still charges, which is the one thing §A forbids. The three docstring statements that claimed
otherwise (`engagement.remote_view`, this file's §11 first draft) were corrected in this commit, and the
safe operator action until a spend route reads the row is to leave those three knobs at their defaults.
The next lane that wires a spend route must read it, and the drift test is the reason it can notice it
hasn't. **The only `engagement.py` lines this commit changes are those docstrings** — no statement, no
constant, no signature; the module's semantics are what `eebdec8` shipped and its 25 tests still pass.

**Held, on purpose (and measured).** `admin_panel.py:1080` still carries `vip_monthly_pkr` default **200** and
`payments.py:85` `PLAN_DEFAULTS["vip_monthly"] = (200, 30)`, while Q4 ruled ₨250 authoritative from
`MONETIZATION_AND_FLEET_PLAN.md:46`. Two tests pin the 200 today (`test_admin_panel.py:380`,
`test_payments.py:267`). I did **not** touch either: the price reconciliation is the payments/admin lane's
file and changing it would have broken tests I did not write. Flagged for #24/Q4, not silently "fixed".
`test_download_endpoint.py` fails **2 of 20** (`test_operator_port_accepts_a_plain_id_and_returns_the_resolved_url`,
`test_operator_port_is_never_monetized_by_a_shortener`) — reproduced identically on the clean base in its
own worktree, so pre-existing, in a module that is not in CI's list. Not mine to fix here.

**Gate (local, on a box at load 6.1–8.0, five lanes, everything offline `-S` stdlib on a printed
`tempfile` fixture).** `test_admin_panel.py` **65 OK** (7 new; 20 s), `test_engagement.py` **25 OK**,
`test_payments.py` **85 OK**, `test_operator_isolation.py` **28 OK** (37 s); re-run together on the landing
base, **90 OK** in 25 s. Hosted Backend CI is the authoritative gate and it judged this content three times —
`40945093282` on `a638e03` (19 modules then), `40945927750` on `41cb049` and `40946874655` on `582e2c3`, each
`completed success` with every `🧪` step success and none skipped. `test_engagement.py` and `test_admin_panel.py` are still **not** steps in
`backend-ci.yml` (the list is **21 modules** on the landing tip — the search lane added
`test_posts_query_plan.py` after my `1d483ee` base and Q4 added `test_adult_twin_probe.py` on `c3459b3`;
`19` is what my first gated sha ran); adding one
edits a workflow five lanes share, so it is reported as a follow-up rather than done unilaterally.

**Fleet rules kept.** `/opt/radd-stream` untouched (worked in `/tmp/q5-monet-fields-live`), no live
`/api/data`, no `fetch_database_payload(full=True)`, no `/api/v1/stats` poll, no Gradle, no merge run, no
scraper swarm, **no service restart**, no production `app_remote_config` write. Push to `master`+`main` by
the heredoc askpass in `ORACLE_DEPLOYMENT.md` — never `printf`, never a token in argv or a URL, never the
`origin` remote.
---

