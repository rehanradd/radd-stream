# Session 2026-10-30 (q3 launch-readiness lane, JOB B) `[Q3-LADDER]`

**Branch `q3-engagement-ladder`, base trunk `682a65a`.** Written in `/tmp/q3_engagement_ladder`-class
worktree `/tmp/q3_ladder`; `/opt/radd-stream` was not read as a workspace, not edited, not reset, not
committed from. No service restart, no deploy, no crawl, no Gradle, no tag, no new cron, no network,
no credential in argv/URL/log, no production path touched.

## The brief (qoder4/master)

Tasks #22/#30: the admin schema is "missing ad cadences, the coin wallet, the streak, and the Rs
20/50/250 payout ladder" — build the schema and the panel fields, stdlib only, with four hard rules:
money as an integer minor unit and **never a float**; the ladder **as data** (`tier → amount →
eligibility rule`), not as `if/else` scattered across the panel; refusal of any field the edge would
rewrite, non-numeric prices rejected, and **NOTHING written on refusal** — "that is the behavior
`Fast_Fetch/test_admin_panel.py` already proves for the existing panel, so match it and extend it";
and `is_18_plus` badge rendering staying operator-only with the panel **never emitting a
stream/download token for a flagged row**.

## What was already true, measured before writing anything

The first four words of the brief — "the admin schema is missing" — do not describe trunk at
`682a65a`, and saying so is part of the job:

- **The wallet, the streak and the ad cadences already have schema**: `coin_ledger`, `streak_state`,
  `ad_cadence_state` (`engagement.py:288/297/305`, `ensure_schema`, `SCHEMA_VERSION`), with the ledger
  append-only enforced by triggers, not by a docstring.
- **The panel fields already exist**: 16 engagement knobs in `MONETIZATION_FIELDS`
  (`admin_panel.py:1110-1147`) — coin per rewarded ad, rewarded daily cap, the three coin redeem
  costs, the three pass PKR prices, streak day-1/day-3 grants, day-7 hours, rollover hour, `streak_tz`,
  and the three ad cadences — all `_INT`/`_MONEY`, all validated in `_validated` (`:1335`) and saved
  all-or-nothing in `_save_monetization` (`:1432`).
- **The ₨20/50/250 ladder already ships** as `PASS_LADDER`, and the public `/api/v1/app/remote-config`
  already publishes it through `_engagement_public` over `engagement.remote_view()`.
- **Money is stored as an integer, in whole rupees.** Not paise. `_validated`'s `_MONEY` branch refuses
  any decimal string outright (`_int_or_none`), `payments.amount_pkr` is an `INTEGER` column
  (`accounts.py:462`), and `payments` reads it back with `int()`. Converting the wire to paise would
  have rewritten the `pkr` contract another lane landed at `68f0def` an hour before my base, so I did
  not do it unilaterally. The `cat_entitlements.price_minor` precedent for minor units is noted in
  `docs/` and belongs to master's gate, not to this branch.

What the brief's four rules actually caught is listed next; those are the changes.

## The four defects this branch closes

### 1. The ladder branched on a tier name, *after* the coins were gone

`redeem_pass` did:

```python
spend = spend_coins(...)          # durable debit
spec = PASS_LADDER[plan]
if plan == "weekend":             # …then find out how long the pass runs
    expires = _weekend_expiry(...)
else:
    expires = moment + int(spec["duration_seconds"])
```

A tier whose name the branch did not know, or whose `duration_seconds` the data did not carry, cost the
wallet and minted nothing: the debit commits before the shape of the product is known. That is the one
failure a spend cannot have, and no re-ordering of `if/else` fixes it — the ordering *is* the bug.

Now the tier declares its own expiry in data (`"expiry_rule": "after_seconds" |
"local_weekend_end"`) and `EXPIRY_RULES` dispatches it; `tier_expiry(plan, moment, tz, ladder)` resolves
whole seconds, and `redeem_pass` resolves **cost and expiry before** `spend_coins`. A tier that names a
rule the module does not have, names `after_seconds` without a `duration_seconds`, carries a
non-positive or boolean duration, or has no usable coin cost raises `BadLadder`/`BadAmount`/
`UnknownPlan` with the wallet untouched and no `coin_ledger` row added — tested, seven ways, in
`RefusalWritesNothingTests`. `test_no_computation_in_this_module_branches_on_a_tier_name` walks the
module's **AST** and fails if any `ast.Compare` ever tests a value against a tier name again; prose
cannot keep that true, syntax can. `pass_ladder()` — dead code that returned a second copy of the
table — is now `resolve_ladder(values)` under its older name, so there is one ladder to read.

### 2. The published price and the charged price were two mappings of one row

`_engagement_public` walked its own tuple list (`("day", "coin_redeem_day", "pass_day_pkr"), …`) while
`redeem_pass` read `PASS_LADDER[plan]["coins"]`. Both were derived from the same settings row by two
different pieces of code. Now `resolve_ladder(values)` is the only function that turns an
`app_remote_config` row into a ladder, the panel projects it with `engagement.passes_projection(...)`
(itself what `remote_view()` uses), and `redeem_pass(values=…)` charges it. `test_engagement_ladder.py`
asserts, for a row that reprices the day pass to 12 coins / ₨33 and the VIP to 250 coins / ₨400, that
the body a phone reads and the debit the wallet takes are the same numbers — and the whole-dictionary
equality with `engagement.remote_view()` that `test_admin_panel.py:641` already held still holds
(65/65 OK).

`resolve_ladder` keeps the two asymmetric readings that already existed, now in one place and tested
from both sides: a coin cost of `0` or an unparseable paste is "use the shipped number" (a 0-coin pass
would be a bug), while a PKR of `0` is **0** (a free tier is an act of the operator's will, and
`_validated` stores both kinds). Two enforcement sites still read constants instead of the row —
`_enforce_rewarded_cap` and `record_engagement_day` — and `remote_view()`'s docstring now says which,
and says which way that mistake runs (a lowered cap would publish a stricter ceiling than the ledger
hands out).

### 3. One money field was a `float`

`usage_stats._payments()` read `COALESCE(SUM(amount_pkr), 0)` and cast it with `float()` into
`by_tier[*]["amount_pkr"]` and `total_pkr`. It was the only place in the money path that turned a whole
number of rupees into a number with a decimal point on the way out, and it disagreed with its own
ledger of record, which casts the same column with `int()` (`payments.payment_detail`,
`list_payments`). Both are now `int`. This is not a wire migration: nothing stored changed, no field
name or unit changed, and `assertEqual(1500, 1500.0)` is why `test_usage_stats.py` stayed green — so
its two `…0.0` literals were corrected to `1500`/`200` and the test now asserts `type(...) is int`,
which is the claim it was always meant to pin.

### 4. The operator panel published playable handles for a flagged work

`fetch_database_payload(full=True)` returned `dict(row)` for every source and release of a flagged post,
so `/api/data` carried its `source_url`, `final_url`, `resource_id` and the release's
`intermediate_url`, and `DASHBOARD_HTML` rendered **▶ Play JIT**, **📋 Copy Direct URL**, **⚡ Stream /
DL** and a **📺 VLC Playlist** anchor for an 18+ title. The endpoints behind those buttons refuse
unconditionally (`redact.link_is_adult`, on the operator port too — `viewer.py:3593`), so nothing ever
played. But a raw hoster file URL pasted into a browser never asks our endpoints anything, so "the
endpoint refuses" was not the whole law: the panel was *publishing* the thing the rule is about.

`_withhold_playable` is a projection, not a deletion — the ledger keeps every column (Zero Data Loss),
the JSON does not carry them, and `playback_withheld: "18+ — stored, never played here"` says what
happened instead of leaving an empty button. The flag, the badge data, the hoster name, `service`,
status, health, size, mime, `http_status` and the row's own `id` all stay, because an operator auditing
flag coverage needs the audit. The dashboard renders the note in place of the three source buttons and
a `🔞 no playlist` span in place of the anchor. `is_18_plus` badge rendering was not moved: it is still
`viewer.py` `DASHBOARD_HTML` only, still fed by `/api/data`, still 403 at the edge, and the public
payload still never lists the flagged work (`test_the_public_payload_never_lists_the_flagged_work`).

The row `id` is deliberately **kept**, and that judgement is stated rather than hidden: on the operator
port `/api/v1/stream?id=` accepts a bare row id (`parse_token(signed_only=not full)` — the operator's
own curl and healing scripts depend on it), so the panel showing an id is showing something addressable.
`test_a_flagged_source_id_never_reaches_the_resolver` proves it is not a play: over a real loopback
socket, both `/api/v1/stream?id=<flagged>` and `/api/v1/download?id=<flagged>` answer 404 `not_found`
and the resolver is recorded as never called. Stripping the id too would have made the row unaddressable
in the audit for no additional refusal.

## One measurement that contradicts two documents — reported, not fixed

`redact.link_is_adult`'s docstring says "An unknown link answers True too, so a vanished row, a typo and
a flagged title are indistinguishable — and none of them plays", and root `AGENTS.md` repeats it ("which
answers True for an unknown link id so a typo cannot play"). Its last line is
`return bool(row and row[0])`: for an unknown id `row is None`, so it answers **False**. Probed on this
branch's fixture — `/api/v1/stream?id=999999999` reaches `fast_fetch.resolve_live_source`, which fails on
the missing row and answers 404 `no_playable_source`. The *effect* survives (a typo does not play); the
*named mechanism* does not exist, and an unrecognized id does server work rather than being refused at
the gate. Changing that return value alters the play path on both ports, so it is master's call, not a
rider on this branch. `test_an_unrecognized_link_id_reaches_the_resolver_today` pins today's behaviour
by name so a fix flips a stated expectation instead of sliding past a silent suite.

## Tests

New, both registered in `.github/workflows/backend-ci.yml` as `🧪` steps (this branch: **31 steps / 30
`run: python3 -S` matches** — the delta is the timed `test_admin_panel.py`. JOB A's `q3-launch-reads`
adds `test_operator_read_bounds.py` as *its* step 30, so after both merge the count is 32, not 31;
re-count with `grep -c 'name: 🧪'`, never by reading my number):

- `Fast_Fetch/test_engagement_ladder.py` — **27 tests, OK, 2.97 s**. Tier data completeness, every tier
  naming a real `_FIELD_BY_KEY` knob whose stored default equals the shipped price, the AST no-branch
  law, a fourth tier as a data-only edit, seven refusal shapes each proving zero rows written, the
  published-vs-charged price equality under a reprice, the 0-coins/0-rupees asymmetry, and int-ness of
  every price and coin count in `remote_view`, `resolve_ladder`, `passes_projection` and the actual
  debit.
- `Fast_Fetch/test_operator_adult_projection.py` — **17 tests, OK, 3.99 s**. The withheld projection, a
  serialized-body scan proving none of the seeded upstream URLs/file ids reach the wire, the audit that
  survives withholding, an unflagged row losing nothing, the stored rows being untouched, the copy-not-
  mutate property, the badge staying operator-only, `generate_m3u_playlist` still empty on both modes,
  the socket refusals with a resolver recorder, and the two dashboard template invariants.

Neighbours run on this tree, all green: `test_admin_panel.py` **65 OK 9.66 s** (the recorded 266.312 s
was this box at load 6.9 — fleet rule 7: local timing measures the box, CI's timing is the record),
`test_database.py` 133 OK 25.26 s, `test_engagement.py` OK, `test_usage_stats.py` 94 OK 13.63 s,
`test_bounded_ledger.py` 10 OK, `test_catalog_api.py` 127 OK 64.93 s, `test_operator_isolation.py` 28 OK
34.39 s, `test_api_v2.py` 46 OK 18.62 s, `test_redact.py` 61 OK 17.57 s, `test_docs_invariants.py` OK.

## Not done, deliberately

- **No paise migration.** See above; it rewrites a contract another lane owns, and every money field is
  already an integer.
- **No change to `link_is_adult`.** Reported with its reproduction instead.
- **`_enforce_rewarded_cap` and `record_engagement_day` still read constants, not the row.** Wiring them
  belongs with the routes that own those grants, and the deception runs the other way (a published
  ceiling stricter than the one enforced). Named in `remote_view()`'s docstring.
- **No `redeem_pass` route exists**, so nothing hands it the settings row yet. The capability is
  `values=`/`ladder=`; the first caller that has a row must pass it, and
  `test_repricing_a_tier_moves_the_published_price_and_the_debit_together` will fail loudly if that
  caller is written to read `PASS_LADDER` directly instead.
- No restart, no deploy, no DDL, no crawl, no Gradle, no tag, no cron. Nothing measured against the
  production catalog or the live service — both viewer suites build temp catalogs and bind 127.0.0.1
  with port 0.

## For the lane that lands this

`q3-launch-reads` (JOB A, `2be6a86`) and this branch both edit `fetch_database_payload` — JOB A in the
page computation and the `return` dict (`truncated`/`clamped`/`ceiling`), JOB B inside the post loop and
the `sources`/`r_dict` branches. Different lines, same function, so expect a textual conflict that
resolves by keeping both halves. Neither branch is a fast-forward child of trunk as of `682a65a`; land
one, then rebase the other onto the merge.

---

## Rotated verbatim out of `CONTINUITY.md` open-items index (2026-10-31, qoder1)

11. **JOB B (tasks #22/#30), branch `q3-engagement-ladder` — and the brief's premise was already false.**
   The wallet/streak/ad-cadence tables and all 16 `MONETIZATION_FIELDS` knobs already existed, and money is
   an **integer in whole rupees** (`_MONEY` refuses decimals; `amount_pkr` is `INTEGER`) — not paise. The four
   rules caught: `redeem_pass` debited coins *before* branching on the tier name (now cost and expiry both
   resolve from the tier's own `expiry_rule`, enforced by an AST walk); `_engagement_public` priced the ladder
   from its own tuples while the spender read `PASS_LADDER` (now one `resolve_ladder` feeds both);
   `usage_stats._payments` was the last `float()` money field (now `int`); and
   `fetch_database_payload(full=True)` published `source_url`/`final_url`/`resource_id`/`intermediate_url` for
   a **flagged** row, which the dashboard turned into Play/Copy/Stream/m3u controls — `_withhold_playable`
   withholds them and names the refusal, the ledger keeps every column, the badge stays operator-only.
   27 + 17 tests, `test_engagement_ladder.py` + `test_operator_adult_projection.py`. Full text:
   `checkpoints/20261030-09xx-q3-lane-job-b-the-pass-ladder-is-data-and-a.md` — which also carries a
   measurement contradicting two documents: **`redact.link_is_adult` returns False for an unknown link id**,
   not the True its docstring and root `AGENTS.md` claim, so a typo reaches `resolve_live_source` and is
   stopped there rather than at the adult gate. Reported, not fixed.
