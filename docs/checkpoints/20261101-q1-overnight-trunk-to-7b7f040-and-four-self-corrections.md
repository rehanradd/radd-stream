# Checkpoint — 2026-11-01 overnight, qoder1 (supervisor): trunk to `7b7f040`, and four claims I corrected

Lane: qoder1 (fleet steward, under Muse). Window 23:30 → 01:3x host time.
Full narrative for the owner: `/home/ubuntu/OVERNIGHT_SUPERVISOR_REPORT.md` (outside the repo, as dispatched).
This file is the in-repo record. `Fast_Fetch/CONTINUITY.md` is at 11,983 B against the guard's 12,000 B ceiling — 17 bytes of headroom — so nothing new goes there; dated checkpoints only.

## Trunk state

| Sha | What | CI evidence |
|---|---|---|
| `1f97bfe` | coins: ten concurrent spends never overspend | 41 steps read individually, 36 🧪 executed, `non-green: []` on both refs |
| `0a1894d` | docs(checkpoint) §8 | docs-only; `backend-ci.yml` path filter produced no run — correct, not disabled |
| `836c31f` | merge of q4 `27c1034` — phone-number-as-credential deleted from `SyncContract` | `git diff 27c1034 836c31f -- App/` empty, so the tested tree *was* the landed tree; runs `41234817540` / `41234814880` both `completed/success` |
| **`7b7f040`** | **merge of q4 `461e142`** (CommentBalanceTest +30, BUILD_PLAN.md +73/−7) — **current trunk on both refs** | judged on **its own sha**, not on `41234044459`'s branch green, because the merge also carries trunk's newer `PhoneCredentialGuardTest` (591 lines) and `SyncContractTest` (+108). At `7b7f040`: `python3 -S offline suites` success **and** `assembleDebug + testDebugUnitTest` success |

Nine arm64-excluded Robolectric cases (`ScreenSnapshotTest` 6, `PosterCardProvenanceTest` 3) executed and **passed on the hosted x86_64 runner** at `836c31f` — the first time in the repo's history. They remain unexecuted here by design; nothing in this window is device evidence.

## Four things I got wrong and corrected by re-measuring

1. **"q2 is editing the deployment tree."** Its process cwd is `/opt/radd-stream`, but it writes `/tmp/q2_admin_auth`, touched at 00:40–00:41; the in-place `viewer.py` edit there is dated 2026-10-29 22:41. The dispatch I wrote was aimed at a stale situation, so I re-sent a correction instead of letting it stand.
2. **"The preapply backup has already been consumed."** I inferred a live writer from `-shm`/`-wal` mtimes at 00:26. Re-measured: main-file mtime is still `2026-10-29 18:57:12`, `-wal` is **0 bytes**, no process holds it. Something read it. Left uncorrected, q3 would have copied 6,396,899,328 bytes at load 4.0 on my say-so. Only the ordering rule survives: checkpoint-then-copy **before** applying a merge.
3. **"A MIME decoder would hide the keystore error."** Not mine first — it was instructed into q4. I ran `java.util.Base64` against six inputs: a wrapped secret throws `Illegal base64 character a`, **not** our message; a bad final group throws `Last unit does not have enough valid bits` **identically under both decoders**. So the swap cannot fix our failure. q4's own `BUILD_PLAN.md:144-156` already said don't touch `build.gradle.kts` and proved the keystore file is sound (2,752 B → 3,672 chars ending `==` → strict decode round-trips), so only the stored string is damaged. Their doc is the authority; I said so.
4. **"My reads are authenticated."** They were not. The helper's case label is `*[Pp]assword*)`, so a literal `Password*)` regex extracts **zero characters**, the header becomes `Authorization: token ` and GitHub answers `401 Bad credentials` — indistinguishable from a revoked token. Diagnosed by printing the extraction **length** (0), never the value. Separately, this host's single IP has a 60/hour **anonymous** quota that I exhausted while polling CI, which makes an exhausted anonymous budget look like an auth failure. Corrected test: pass the header through stdin (`curl -K -`), read `resources.core.limit` — 5000 authenticated, 60 anonymous. With that in place the askpass credential returns 5000, and `~/.bashrc`'s `GITHUB_TOKEN` still returns 401 when passed **correctly**, so that one is genuinely revoked.

## Fleet actions

- **qoder2**: took "report the 401 finding, don't auto-merge" on its behalf — trunk landing is reviewed, not incidental. Re-sent the four `/admin/login` gate questions (KDF + storage; login failure cost/bucket; the 8081 trust boundary must not reopen a token-free `/`; one escaper + a build-breaking guard).
- **qoder3**: selected "run the L3 review before push" on its dialog. Merge stays **gated**: target is provably wrong (both `fast_fetch.db` files are 56-byte empty SQLite headers while the service reads `merged_catalog_20261025.db`, 6.4 GB), the three staging sources need `wal_checkpoint(TRUNCATE)` before read, and the 442 mixed-flag `canonical_key` reconciliation must happen inside the merge or the merged catalog is not deployable.
- **qoder4**: refused the MIME change and the `v1.0.2` re-tag; landed its branch on evidence instead.
- **qoder5**: still the only lane whose cwd is a worktree (`/tmp/q5_ci`). CI-registration candidate awaits a sha.

## Not done, not claimed

No signed release exists — `GET /releases` is `[]` and all five release attempts are `failure`. Only debug APK artifacts (22,204,160 B at `836c31f`, 7-day retention). No tag created or moved. No `radd-stream.service` action. No Gradle run by me. `/opt/radd-stream` still sits on non-trunk `bf9e565` with in-place backend edits lacking `bounded_int` and `_withhold_playable`, plus a hand-copy `viewer.py.bak_dashboard` in the served path — a restart there reverts landed compliance work, and that is the owner's call on a window where a restart is acceptable. The server-side half of the phone-key exposure is untouched: `accounts.py:895-922` `create_account()` is create-on-present and `accounts.py:22` says the server cannot tell a derived key from a minted one, so accounts already provisioned from phone numbers stay openable beside the coins wallet.
