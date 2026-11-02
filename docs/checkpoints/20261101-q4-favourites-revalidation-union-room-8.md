# 2026-11-01 — q4 App lane: the favourites re-validation union, landed as Room version 8

**Lane:** qoder4 (account4), App. **Branch:** `q4-fav-revalidation-v8-c2528e1`, one commit off trunk
`c2528e1`. **No Gradle ran on this box** — it cannot (no SDK `platforms/`, no `licenses/`), and the
supervisor ordered hosted-CI-only regardless. **No trunk write, no tag, no service action, no
production DB read or write, no credential touched.**

## What this union is

Two preserved halves existed on this repo and neither compiled alone:

| Piece | Where it lived | State |
|---|---|---|
| `AdultPolicy` + `UnavailableWork` + `AdultPolicyTest` + `AdultListingGuardTest` | `q1-rescue-untracked` @ `1c83e1c` (q1's copy of work that was uncommitted in `/opt/radd-stream`) | never built |
| the favourites re-validation itself (DAO, entity fields, repository, My List, schema guard) | `q4-fav-recheck-rescue` @ `583fd54` | **hosted CI `failure`, 35 errors** in `FavoritePost`, `FavoritesRepository`, `MyListScreen` (run `41157938495`) — it references `Post.is18Plus`, `AdultPolicy`, `UnavailableWorkDao`, `MyListUiState.hiddenCount`, none of which were on its parent |

This branch is the union: the two preserved halves, renumbered onto trunk's schema, plus the
callers that make them run. The `583fd54` diff applied to `c2528e1` without a single conflict; every
change below is what the compiler and the schema required on top of it.

## The Room version collision, and why 8 is not cosmetic

Trunk owns **`version = 7`** for `ad_cadence` (`MIGRATION_6_7`). The rescue's `MIGRATION_6_7` was a
*different* 6→7 step — `is18Plus`, `checkedAt`, `unavailable_works`. Landing that as written means a
device already on 7 never re-runs the step, `favorite_posts` keeps missing its two columns, Room's
runtime schema check fails on open, and `DatabaseModule.kt:43` registers
`fallbackToDestructiveMigration()` — so the failure is not a crash, it is **the viewer's saved list
deleted**, which is the exact second bug this feature exists to prevent.

Landing shape, as recorded in the 2026-10-31 entry: `MIGRATION_6_7` (ad_cadence) untouched, new
`MIGRATION_7_8` with the three statements, `version = 8`, registered on the builder. All four are
pinned by `FavoritesSchemaGuardTest`, whose newest-step test was renumbered from 6→7 to 7→8 — the
refusals (`DROP TABLE` / `DELETE FROM` / `RENAME TO` may not appear in that step) came along
unchanged, and the bound stays self-tightening: a future 8→9 becomes the new end of the scan.

## Measured first, and it changed the design: the flag is not a wire field

`GET http://92.4.95.252/api/v1/posts?limit=1` and `GET /api/v1/posts/158`, read 2026-11-01:

```
post_brief keys  : … is_animated … work_ref …            is_18_plus ABSENT
post_detail keys : … is_animated … option_groups …       is_18_plus ABSENT
```

That is not a projection gap, it is the design: the public route answers 404 for a flagged id, so a
row that arrives at all arrived unflagged. Consequences, all of them departures from the rescue:

- **`Post.is18Plus` / `PostDetail.is18Plus` were NOT added.** A field mapped from a key the API
  never returns is permanently null and is exactly the class of phantom `App/AGENTS.md` §6 already
  retired once. `FavoritePost.is18Plus` stays as a *local* column, written only by
  `FavoriteDao.recordAnswer` when a payload genuinely carries a flag, and `toPost()` / `fromPost()`
  do not map it (the three mapping lines in the rescue were dropped). `AdultListingGuardTest` now
  refuses a phantom field instead of requiring one, and its KDoc says what to do if a projection
  ever publishes the key.
- Therefore **`FavoritesRepository.addFavorite` records `flag = null`**, and the half of the rule
  that fires against this server is the **refusal ledger**: an id the public route 404s is hidden by
  `unavailable_works`, not by a flag. `AdultPolicy`'s own KDoc already said this; the union makes
  the code match it instead of leaving a `Post.is18Plus` that could never be true.

## What fires on this branch

- `CatalogRepository.probePost` reports **primitives** (`httpStatus`, `bodyClaimsSuccess`,
  `noAnswer`) and never a verdict, so "refused", "served" and "could not ask" stay distinguishable —
  `getPostDetail` collapses a 404 and a dead socket into one `null`, which is right for a screen and
  fatal for a compliance ledger.
- `FavoritesRepository.recordAnswer` — `LISTED` clears the refusal *and* stamps; `GONE` stamps then
  records; `UNANSWERED` writes nothing, not even the stamp, so an outage leaves the row due instead
  of quiet for a TTL.
- `revalidateSavedRows()` — at most 12 rows per pass, only rows whose answer is ≥ 24 h old or
  missing, never-checked first. Called from `MyListViewModel.init` without awaiting it, so opening
  My List a second time the same day asks nothing and a failed pass costs the viewer nothing they can
  see.
- **Both cached surfaces filter at render**, the one place a `WHERE` clause on the server cannot
  reach: My List (`MyListViewModel`, over the stored rows before any sort or map, with
  `hiddenCount`/`hiddenNotice` — a count, never a title) and Continue watching (`HomeViewModel`,
  keyed on the resume row's own `postId`, `flagOf` a constant null because `watch_history` models no
  flag).
- `Brand.adultFilterEnforced` is **computed**, not returned: `= AdultPolicy.enforcesAdultListing`.
  Nothing in the app read the old literal, so this costs no behaviour and retires a name that reads
  as evidence without being any.

## Two doors this slice deliberately does not open

Recorded here because `AdultListingGuardTest` does not pin them, and an unpinned gap is how
`adultFilterEnforced` stayed a `true` for months:

1. **The detail screen's 404 arm still calls a refusal a connection error.**
   `DetailViewModel`'s `catch (HttpException)` needs `AdultPolicy.serverAnswerFor(...)` →
   `recordAnswer(..., GONE)` in the refused arm only, with the other arm keeping
   `friendlyNetworkError`. Not in this slice: `DetailViewModel` is a mixed live-tree file (another
   lane's deletions ride in it), and the rescue commit says so. Its snapshot is in
   `/tmp/q1_rescue_app_20261031/` for that owner.
2. **The stream door.** `UnavailableWorkEntity.REASON_STREAM` is declared and nothing writes it:
   `recordStreamRefusal` was dropped from `FavoritesRepository` rather than landed uncalled. A
   `/api/v1/stream` refusal about a saved handle belongs in the player/Detail wiring, with the same
   one ledger.

## Verification

Hosted `🔨 CI — Android Build & Test` is the only judge available and the only one used; the verdict
is appended to this entry once read. Local `testDebugUnitTest` is impossible on this host, and the
two Robolectric suites remain excluded on aarch64 (robolectric/robolectric#9166), which is why the
surfaces are guarded as text.

## The verdict is NOT read: this branch cannot be pushed, measured 2026-11-01

> **Superseded later the same afternoon — the branch did push and CI did run; read the last section
> before repeating anything below.** Kept as written because the credential failure it records is the
> reason the recovery bundle exists, and that is worth knowing even now.

Three attempts, all with the sanctioned flow (`GIT_ASKPASS=/home/ubuntu/bin/git-askpass.sh`,
`GIT_TERMINAL_PROMPT=0`, explicit clean URL `https://github.com/rehanradd/radd-stream.git`, never
`origin`), all against `refs/heads/q4-fav-revalidation-v8-c2528e1`. The third carried this entry's
own failure record, so the refusal is not an artifact of the union's content — a docs-only push on top
of `53767c3` is refused identically:

```
remote: Invalid username or token. Password authentication is not supported for Git operations.
fatal: Authentication failed for 'https://github.com/rehanradd/radd-stream.git/'
```

The credential is not merely unblessed for this ref: **the same helper, the same clean URL, the same
session pushed `380d148` earlier the same day**, and it is verifiably still there
(`refs/heads/q4-update-banner-questions-c2528e1 = 380d1481a96085f6c670530f658e066be494b12c`, read with
`git ls-remote --heads`). So the write path went bad between the two pushes rather than never having
worked. `git ls-remote` answering 200 proves nothing here — a public repo serves anonymous reads, and
this repo's own history already records that conclusion (`bf9e565`: "a public repo's green ls-remote
is not write access").

What was **not** done to work around it, deliberately: no push to `origin` (its stored remote URL
still embeds the owner's unrevoked token), no token in a URL, argv, file or log, no credential read
or print, no second credential (q1 reported its own write credential blocked the same morning, so
this is a repo-wide state, not my lane's config), no retry loop (three attempts, spread over the work
that had to be pushed anyway, then stopped), no force-push, no merge, no tag. `53767c3` is therefore
**local-only and unjudged**: the compile risk this union
carries — `583fd54` alone was 35 errors — has had no verdict, and I do not claim one.

**Recovery:** the commit is exported outside the repo tree so it survives a worktree cleanup while the
credential is out — `/home/ubuntu/q4-recovery/q4-fav-revalidation-v8-head.bundle`, a `c2528e1..HEAD`
bundle. `git bundle verify <path>` prints the tip it currently holds and its prerequisite; regenerate
it after any new commit on this branch with
`git bundle create /home/ubuntu/q4-recovery/q4-fav-revalidation-v8-head.bundle c2528e1..HEAD`.
Pushing it later is one more command, and reading the verdict is one after that:
`GIT_ASKPASS=/home/ubuntu/bin/git-askpass.sh GIT_TERMINAL_PROMPT=0 git push <clean URL> HEAD:refs/heads/q4-fav-revalidation-v8-c2528e1`
then `/repos/rehanradd/radd-stream/commits/<sha>/check-runs`. **Gate order stays q1's call.**

## One correction to `53767c3`'s message

Its body line 42 reads `NO GUIN PIN COVERS IT`; the intended phrase is **no *guard* pin covers it** —
`AdultListingGuardTest` does not pin the two doors that section lists. The commit is not amended for
a typo (never amend; the correction belongs beside it, which is what this entry is).

## 2026-11-01 16:4x — it pushed, and hosted CI is RED. What that rules in and out

The write path came back the same afternoon (q1's `a5c5805` and q2's `f6acef3` both landed), and the
sanctioned push then succeeded first try: `* [new branch] HEAD -> q4-fav-revalidation-v8-c2528e1`,
remote tip confirmed at `98933db` by `ls-remote`. Flow unchanged — helper, clean URL, never `origin`,
no credential read or print, no force-push, no merge, no tag.

Before pushing I proved the recovery bundle rather than trusting its header, and that produced a
correction to the section above: the pack starts at **byte 208, not 1024**, and standing alone
`git index-pack --stdin` answers **`pack has 30 unresolved deltas`** — it is a **thin** pack,
delta-dependent on trunk. So it restores only into a repo that already holds `c2528e1`, which is what
`git bundle verify` declares as its prerequisite. The decisive test then did exactly that: clone a
**trunk-only** repo, confirm it did *not* contain the tip, fetch the bundle → tip
`98933db7ac7d74a16fdc2c1b055a436ec894ae15`, tree `71c3b51…` identical to local, three commits in
order, `17 files, +1212/−9`, and **all 712 path+sha entries identical**. Nothing was pushed that the
bundle could not reproduce.

**The verdict** (`🔨 CI — Android Build & Test`, run `41302639884`, job `124836585688`):
`completed / failure`, and the failing step is `7 🏗️🧪🔍 Gradle: debug APK + unit tests + lint`, after
**178 s** — a green run of that same step takes about 7 m 02 s. Steps 1–6 (checkout, JDK, cache
restore, SDK install, `gradlew` chmod) all succeeded, and step 8 uploaded an `app-debug` artifact of
22,222,414 bytes.

What that evidence supports, and what it does not:

- **`:app:assembleDebug` is not the failure.** The one Android run we have that *did* fail in
  compilation — `583fd54`, 35 errors, run `41157938495` — published **zero artifacts**, because there
  was no APK to publish. This run published a real 22 MB APK. So the union's main sources compiled,
  including `MIGRATION_7_8`, the four-flow `MyListViewModel`, and the three-flow `HomeViewModel`.
- **The failure is in `:app:testDebugUnitTest` or `:app:lintDebug`**, and the API will not say which:
  the check run carries one annotation, `Process completed with exit code 1`, its `output.summary` is
  empty, and both the job log and the `ci-reports` artifact (445,281 bytes, where the test and lint
  XML live) answered **404 anonymously**. Reading them needs authentication, which the
  no-credential standing order puts on q1/Muse, not on me.
- **So the guards were run the only way they can be run without a runner: simulated.** They are pure
  file-text scans, so their assertions are reproducible with reads — no Gradle, no SDK, nothing
  heavier than a `--single-branch` clone. `FavoritesSchemaGuardTest` came out clean on every rule
  (entity columns ≡ DDL columns, one favorites `CREATE`, all added columns nullable, six migration
  steps each climbing one, `version = 8` equal to the newest step, the 7→8 body containing both
  `ADD COLUMN`s and none of `DROP TABLE`/`DELETE FROM`/`RENAME TO`, the ledger's three columns in both
  files with `PRIMARY KEY(postId)`, every declared `MIGRATION_*` registered on the builder).
  `AdultListingGuardTest` came out with **one violated pin, and it was mine.**
- **Root cause, and it is a guard bug rather than a policy bug.** The last assertion of
  `the flag is a stored answer, never a phantom wire field…` read
  `assertFalse(models.contains("is_18_plus"))`. `Models.kt:34` is the header rule that forbids
  modelling the key, and it *names* the key to forbid it: "`is_18_plus` is deliberately NOT modelled
  anywhere in this app." The pin therefore failed on the documentation of the very rule it was
  enforcing — a text scan treating prose as code, which is the same class of mistake this repo's
  guard culture keeps calling out, only in the over-strict direction rather than the vacuous one.
  Fixed by scanning the two shapes a field can actually have (`@SerializedName("is_18_plus"` and a
  `\bis18Plus\b` property), with a positive control fed a real phantom field so the narrowed scan
  cannot go green by matching nothing. The key's prose is left in place on purpose: deleting the
  documentation must not be a way to satisfy a guard.
- **Two Kotlin-lexer hazards found on the way, both before pushing.** The replacement regexes
  originally ended in a four-quote run (`…"is_18_plus""""`), which Kotlin resolves greedily — the
  pattern silently gains a trailing `"` or fails to compile depending on the parse. They now end at
  `\b`, which is unambiguous. Verified separately: no test file references the `recordStreamRefusal`
  I dropped; `listableRows` and `selectForRevalidation` exist as generic `fun <Row>` declarations (an
  earlier grep of mine missed them and I re-checked instead of reporting a missing symbol); no manual
  call site depends on the old `HomeViewModel`/`FavoritesRepository` constructor arity, Hilt injects
  both; and `DeadCodeGuardTest` looks only for orphan resources and `*ForTest` names, neither of
  which this diff introduces.
- **Trunk is not the reason.** `c2528e1` has no Android check-run at all — `ci.yml` filters on
  `App/**` and trunk's tip is a docs commit — so the last green Android judgement is `718a8ef` and
  `1cbd54d`, both on this same base and both `success`. My union is the delta.

**What is still not proven:** that the violated pin was the *only* thing CI objected to. It is the
only violation simulation can find, it is consistent with an APK that built and a test task that
failed, and it is mine — but the next red/green on the fixed tip is the evidence, not this reasoning.

**Next step, and whose it is:** the fix is pushed to the same branch and CI re-ran on it; the verdict
is appended below when it lands. If it is red again, the thing to obtain is the authenticated
`ci-reports` artifact (that is q1's/Muse's call, not a credential action on my side), because
simulation has run out of what it can see. Until a green run exists on a sha, nothing on this branch
may be gated on the strength of my reasoning.

## 2026-11-02 06:1x — the verdict is read, and it is GREEN

Measured with one anonymous `GET /repos/rehanradd/radd-stream/commits/0fa2d65/check-runs` → HTTP 200,
`total_count: 1`:

| Check run | Status | Conclusion | Run / job |
|---|---|---|---|
| `assembleDebug + testDebugUnitTest + lintDebug` | `completed` | **`success`** | run `41304087249`, job `124840815235` |

That closes the open question from the previous section. The violated `is_18_plus` prose pin was the
*only* thing CI objected to: `98933db` was `failure` and `0fa2d65` — which differs from it only by
that one guard rewrite and this checkpoint — is `success` on the same runner, with the same
`assembleDebug + testDebugUnitTest + lintDebug` step and no code change in between. Simulation found
one violation, the fix corrected exactly that violation, and the hosted run agreed. Nothing here rests
on my reasoning any more; it rests on a green check-run at a named sha.

**What this is, and what it is not.** It is the first green Android judgement on the favourites
re-validation union + Room 8. It is not a merge, not a gate decision, and not a release: q1 alone
gates trunk, and there is still no tag and no signed release (signing remains blocked on the owner's
four keystore secrets — see the root `AGENTS.md` measured note).

**Remaining unproven, stated rather than glossed:** the two Robolectric suites
(`ScreenSnapshotTest`, `PosterCardProvenanceTest`) are excluded on this aarch64 host
(Robolectric #9166), so the hosted runner is the only judge of them and it has now judged them —
which is exactly why "CI-verifiable rather than locally runnable" is the plan here. And a green JVM
scan still cannot prove a `LazyColumn` filters at render; the guards pin the *call*, not the pixels.
Device verification of playback and of the My List surface stays pending, as it has been all along.

**Branch state at this record:** `q4-fav-revalidation-v8-c2528e1` @ `0fa2d65`, pushed, working tree
clean, recovery bundle refreshed.
