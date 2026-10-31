# 2026-10-31 ~08:2x — qoder1 supervisor `[Q1-RELEASE-TRUTH]`: the release workflow is not producing signed artifacts, and the log says exactly why

**Scope:** documentation and measurement only. No `.kt`, `.kts`, resource or workflow file was
touched; no Gradle invocation (the owner's build hold stands until load is under 0.5); no scraper
run; no database write; **no service action of any kind** — `radd-stream.service` was not restarted,
reloaded or stopped, and no tag was created, moved or deleted.

## 1 — the claim retired

Root `AGENTS.md` carried "the official release workflow (`🚀 Release — Sign & Publish APK + AAB`) is
now active and **producing signed release artifacts**", and the `App agents:` line contradicted it in
the same section ("now active and verified as of 2026-10-30" beside "which are **currently absent**
(measured above)"). Both were append-only edits stepping on each other. Measured on the API:

| Claim | Measurement |
|---|---|
| secrets configured | **true** — run `41104217171` cleared `🗝️ Verify signing secrets are present` at `18:08:05Z` ("All four keystore secrets present (values not printed)"), the preflight that killed the 2026-10-29 attempt in 10 s |
| producing signed artifacts | **false** — the same run ended `failure`; all four release runs in history are `failure`; `GET /releases` returns `[]` |
| a signed build exists | **it never has** — no signed APK or AAB has existed for this product |
| `v1.0.0` is releasable | **stale** — the tag resolves to `6a441ec77`, a trunk point that predates the adult merge-time fold `4a8c163`, so re-running that tag ships pre-law code |

## 2 — the cause is in the log, not in a guess

The run log (`/actions/runs/41104217171/logs`, 39 KB, authenticated) gives it exactly:

```
* Where: Build file '.../App/app/build.gradle.kts' line: 120
* What went wrong: Last unit does not have enough valid bits
java.lang.IllegalArgumentException: Last unit does not have enough valid bits
	at Build_gradle$3$2$1.execute(build.gradle.kts:120)
BUILD FAILED in 4s
```

It died during **configuration**, inside `signingConfigs`, four seconds in — before a single Kotlin
file was compiled, so no compile error and no lint error was ever reached. The 120 s of job wall time
is SDK setup, not the build.

`Base64.getDecoder()` (imported `java.util.Base64` at `build.gradle.kts:3`) is the strict **basic**
codec: it accepts no line breaks and refuses a final quantum that is not a whole group. "Last unit
does not have enough valid bits" is that decoder saying the **stored secret value** is malformed —
padding lost or characters dropped when `KEYSTORE_BASE64` was pasted into GitHub.

The keystore itself is sound. Measured against the VM copy, credential-safe (lengths and a round-trip
boolean only, no value read or printed): `/home/ubuntu/raddstream-release.jks` is 2,752 bytes, encodes
to 3,672 base64 characters (`len % 4 == 0`, ends with two `=`), and strict-decodes back to the same
bytes. A copy with the trailing `=` stripped is exactly the shape that throws in a decoder that
tolerates a 2-char tail but not a 3-char one.

**Therefore the fix is owner-side secret re-entry (`base64 -w 0` of that file into
Settings → Secrets → Actions), not a build-script change.** Switching to `getMimeDecoder()` or
catching the exception would silently accept a truncated keystore instead of refusing it, which is
the opposite of what a signing gate is for.

## 3 — the doc defect that hid this, retired

`App/AGENTS.md` §10 printed a signing sample using **`android.util.Base64.decode(...)`** — an Android
runtime API that is not on the Gradle script's classpath, so the documented code could never have
configured any build. An agent trusting it would "fix" the wrong file. §10 now carries the real block
(`App/app/build.gradle.kts:110-126`, verified at `a51c0c4`): the config applies only when **both**
`KEYSTORE_BASE64` and `KEY_STORE_PASSWORD` are non-empty, the keystore is written to
`app/build/radd-release.jks` (never the source tree), and decoding is `Base64.getDecoder()`.

## 4 — a guard pin that enforced a stale state

`Fast_Fetch/test_docs_invariants.py` pinned the phrase
`"the *signed release* needs the 4 keystore secrets, which are **currently absent**"` — so the docs
guard **refused** the correction that told the truth. This is the same defect class as the
missing-backticks pin retired at `dcf2ea1`: a pin quoting a date-stamped *state* instead of the
*law*. Re-pinned to `the *signed release* needs the 4 keystore secrets` (always true) and two laws
added so this cannot be re-falsified silently:
`"No signed APK or AAB has ever existed for this product"` and
`"Moving or re-cutting a tag is an owner action"`.

**Rule for every lane: never add a pin without running `python3 -S Fast_Fetch/test_docs_invariants.py`
on it — 0.2 s, markdown only, light work even at load 6.** Two pins of this class have now been
caught by a green run rather than by reading.

## 5 — the App merge landed, and how it was gated

`902d0df` (q4's hosted-green onboarding `88b1b02` merged onto trunk `dcf2ea1`) was **red on exactly one
CI step**: 30 python suites passed and `test_docs_invariants.py` alone failed with
"docs/SESSION_CHECKPOINT.md claims 56 archive files, docs/checkpoints holds 57" — the merge added a
checkpoint file and the archive count is a tested claim, not prose. Corrected to **57 files / 55 dated**
(README excluded, per the guard's own glob), then landed as `a51c0c4` on **both `master` and `main`**:
2,003 insertions / 13 deletions across 14 files (`OnboardHonestyTest` 374, `DeviceTrialTest` 312,
`SettingsViewModel` +291, `SettingsScreen` +155, `SESSION_HISTORY.md` +123). **Android CI is
`completed success` on both runs at `a51c0c4`** (measured on `/commits/a51c0c4/check-runs`). No
backend run triggered at `a51c0c4` because the merge's `Fast_Fetch/**` delta is empty — that is the
path filter working, not CI being off; the docs guard was instead run directly at that tree, 18 tests
OK.

## 6 — what is still owed, by whom

- **Owner (agent-forbidden):** re-enter `KEYSTORE_BASE64`; deploy/restart `radd-stream.service`
  (production is still pre-law — no `adult_fold_journal`, live `redact.py` fail-open); move or re-cut
  `v1.0.0`; the §13 hue decision; `DynamicServerDiscovery` and episode-offset keep-or-cut.
- **q3:** the coins-engine sha and a real branch (`/api/v2/account/coins*` + `test_coins_engine.py` +
  a CI step); `q3-adultkey-net` still needs a rebase onto trunk and its 13.9 KB / 139-line ceiling
  breach in `Fast_Fetch/CONTINUITY.md` fixed.
- **q4:** the nine mixed-file recovery judgements on the preservation branch `2106e53`, the
  `CommentBalanceTest` lone-apostrophe scanner repair, and the Room **version 8 + `MIGRATION_7_8`**
  landing shape for the favourites rescue (`583fd54` is not landable as v7).
- **q2:** Hum TV `humtv.db` ingest + census numbers (frozen above load 4) and its tip sha.
- **q5:** nothing outstanding; `test_docs_invariants.py` is now 18 green tests on trunk.

Ceilings after this entry: root `AGENTS.md` **31,657 B** of 32,000 (343 B of headroom — the next
root-law addition must displace text, not append it); `App/AGENTS.md` **14,061 B** of 15,000;
`Fast_Fetch/CONTINUITY.md` untouched at 11,991 B / 109 lines of 12,000 / 120.
