# Q4-DEEPLINK-HONESTY — measured findings and implementation plan

Supervisor: qoder1. Lane: App (qoder4 pane). Base: `origin/master` = `origin/main` =
`6a441ec`. Branch: `q4-deeplink-20261030`, worktree `/tmp/q4_deeplink`.

Status: **stopped before any code edit**, on the supervisor's load hold. Nothing in `App/app/src`
was modified. Everything below is read-only measurement plus the plan that follows from it.

## 1. The three cited lines, re-measured on trunk

All three are true as written. None had already been fixed.

1. `App/app/src/main/AndroidManifest.xml:59-65` — the deep-link filter is
   `<intent-filter android:autoVerify="true">` with `action.VIEW`, `category.DEFAULT`,
   `category.BROWSABLE` and exactly one `<data android:scheme="${brandScheme}" />` — no host, no
   path, no port. The comment immediately above it (`:59`) reads
   `Deep link: <brand.deeplink.scheme>://stream/12345`. The app registers no `stream/...`
   destination anywhere, so the comment names a shape the app cannot route, and the filter accepts
   every other `radd://` URI for the same reason it has no host or path.
2. `ui/navigation/NavGraph.kt:168` and `:223` are the only registered patterns, on the `Browse` and
   `Detail` composables:
   `androidx.navigation.navDeepLink { uriPattern = Brand.deepLinkUri("browse/{type}") }` and
   `... Brand.deepLinkUri("detail/{postId}")`. Confirmed by a repo-wide grep: `deepLinkUri` has
   exactly three call sites in `app/src` — those two plus its own definition.
3. `ui/screens/DetailScreen.kt:216` calls `shareTitle(context, post)` (guarded by
   `if (post != null)`), and `shareTitle` is defined at `:1037` as a `private` fun that sets
   `EXTRA_SUBJECT = title` and `EXTRA_TEXT = Brand.copy("share_template", "", "title" to title)` and
   nothing else. **No URI is attached**, so the share can never open the app.

## 2. Measurements the brief did not contain, each of which changes the plan

- `brand.properties:178-181` — `[deeplink]` carries `deeplink.scheme=radd` **plus
  `deeplink.host.browse=browse` and `deeplink.host.detail=detail`**. Those two host keys are read by
  nothing: not `app/build.gradle.kts` (which emits only `manifestPlaceholders["brandScheme"]` at
  `:140`), not `Brand.kt`, not any test. The host half of the vocabulary already exists in the brand
  file and is simply not wired — which is where the manifest and the router should both read from.
- `Brand.kt:163` — `fun deepLinkUri(path: String): String = "$deepLinkScheme://${path.trimStart('/')}"`.
  So `deepLinkUri("detail/42")` = `radd://detail/42`, which `android.net.Uri` parses as
  scheme=`radd`, **host=`detail`, path=`/42`**. The nav patterns therefore already imply
  host-based manifest filters; the two unused brand keys describe exactly those hosts.
- `Screen.kt:36-43` — `Screen.Browse.route == "browse/{type}"` and
  `Screen.Detail.route == "detail/{postId}"`, i.e. **byte-identical to the strings `NavGraph` passes
  to `deepLinkUri`**, and `Screen.Detail.createRoute(postId) == "detail/$postId"`. So a resolvable
  per-work URI is `Brand.deepLinkUri(Screen.Detail.createRoute(id))` with **zero new literals** —
  the route owner and the URI owner compose it, which is exactly what deliverable 1 asks for.
- `MainActivity.kt` — `launchMode="singleTop"` (`AndroidManifest.xml:52`) and **no
  `onNewIntent` override**; a repo-wide case-insensitive grep for `handleDeepLink|onNewIntent` over
  `app/src` returns **zero hits**. `RaddStreamNavGraph` accepts
  `navController: NavHostController = rememberNavController()` (`NavGraph.kt:65`), and
  `MainActivity:140` calls it without passing a controller, so no code outside the composable ever
  holds the controller that could handle a warm intent.
- `navigation-compose = 2.7.7` (`gradle/libs.versions.toml:6`).
- `brand.properties:167` — `copy.share_template=Check out "{title}" in RADD Stream.` — the words
  stay exactly as they are; the link rides beside them.

Consequence for honesty: the filter is not merely under-specified, it also advertises a claim the
process cannot currently keep twice over (no `stream/...` route at all, and no warm-start handler).
Deliverable 3 says pick "matches the shapes the app routes" or "stops claiming" — picking the first
without also handling the warm start would be replacing one overclaim with another. See §4.

## 3. Planned change (App lane only; no `.py`, no build)

1. **One URI owner, one vocabulary.** Keep `Brand.deepLinkUri` as the sole composer — do not add a
   second. Add to `ui/navigation/Screen.kt` (the route owner, so the arg names and the path cannot
   drift from it) a small `DeepLinks` object whose members are *derived*, never retyped:
   - `val browsePattern get() = Brand.deepLinkUri(Screen.Browse.route)`
   - `val detailPattern get() = Brand.deepLinkUri(Screen.Detail.route)`
   - `fun forDetail(postId: Int): String = Brand.deepLinkUri(Screen.Detail.createRoute(postId))`
   - `fun routeOf(uri: String): String?` — the pure, JVM-runnable definition of *resolvable*: returns
     the in-app route (`"detail/42"`, `"browse/movie"`) **iff** the URI's scheme matches
     `Brand.deepLinkScheme`, its host is one of the two pattern hosts, and its path has exactly the
     one non-empty segment the registered pattern asks for; `null` for anything else, including
     `radd://stream/12345` and `radd://detail` and `radd://detail/1/2`.
   Then `NavGraph.kt:168`/`:223` become `uriPattern = DeepLinks.browsePattern` /
   `DeepLinks.detailPattern`, and the share uses `DeepLinks.forDetail(...)`.
2. **Share carries the link.** Extract the payload from the Intent so it is JVM-testable:
   `internal fun shareDraftFor(post: PostDetail?): ShareDraft?` (data class
   `ShareDraft(subject, text, deepLink)`), returning `null` when there is no loaded work.
   `text = Brand.copy("share_template", "", "title" to title) + " " + deepLink`, deepLink built
   through `DeepLinks.forDetail(post.id)`. `shareTitle` becomes a thin adapter that puts
   `EXTRA_SUBJECT`/`EXTRA_TEXT` from the draft and adds `EXTRA_TITLE`. `internal` (not `private`) for
   the same reason `VipUpgradeScreen`'s sections were made internal in Session 17 — a JVM test cannot
   reach a `private`.
   Post.id nullability must be checked against `Models.kt` before writing this (not yet read).
3. **Honest manifest.** Replace the bare-scheme filter with one `<data>` per routed shape, each with
   scheme + host + `android:pathPrefix="/"` — a plain `startsWith` test on the platform, chosen over
   `pathPattern` deliberately: `pathPattern` is a *glob* (`PatternMatcher.PATTERN_GLOB`) whose
   translation is subtle and unverifiable on this box, and a wrong guess silently breaks every share.
   Drop `android:autoVerify="true"` (it means "Android will verify this host's asset links", which is
   meaningless and therefore untrue for a custom scheme), and rewrite the comment to say exactly
   what the app does: two hosts, one path segment each, resolved by `NavGraph`; anything else opens
   the start destination or nothing.
4. **Tests** (JVM only, no Robolectric, so they run on this host's exclusion-free suites):
   - `ui/navigation/DeepLinkShareTest.kt` — a draft always carries a URI that `routeOf` resolves back
     to `detail/<the same id>`; the words from `copy.share_template` survive verbatim in the text;
     **no `radd://` URI is composed from a work that was never loaded** (`post == null` → no draft);
     an id of 0/negative produces no draft rather than a plausible-looking dead link.
   - `ui/navigation/DeepLinkRoutingTest.kt` — the adult invariant in its honest, testable form: a
     detail fetch that the server refused leaves `post == null`, therefore no share draft **and** no
     play affordance; `routeOf("radd://stream/12345")`, `routeOf("radd://detail")`,
     `routeOf("radd://detail/1/2")`, `routeOf("https://example.com/detail/1")` are all `null`; only
     the two registered hosts resolve. Plus the DetailViewModel error-path assertion that an error
     with no post yields no resolvable URI.
   - `tooling/DeepLinkCensusTest.kt` — the source-census guard, `StatsHonestyTest` pattern. Parse
     `<data>` elements out of `AndroidManifest.xml` (scheme placeholder + host + path attributes) and
     every `navDeepLink { uriPattern = ... }` out of `NavGraph.kt`, and fail if a pattern has no
     matching filter or a filter matches no registered pattern; fail on `autoVerify` present with a
     non-http scheme; fail on any `radd://`/`"${brandScheme}"` literal appearing in Kotlin outside
     `Brand.kt`/`Screen.kt` (the one-owner rule).
     **Positive controls, mandatory** (a scan that matches nothing must fail, not go green): assert it
     finds exactly 2 `<data>` hosts and 2 `navDeepLink` patterns, assert `deepLinkUri` is found at its
     definition and its call sites, and feed the parser one synthetic block it must reject — so a
     renamed file or an emptied regex cannot make the suite pass by finding nothing.
5. `App/AGENTS.md` §12/§14 session log entry with the honest-gap list below.

## 4. Honest gaps — what no test on this host can prove

- **Nothing here compiles.** The build hold means no `:app:compileDebugKotlin`, so every Kotlin above
  is hand-checked only. Session 25 and 31 both found real compile errors in hand-written Kotlin on
  this exact rule; treat the plan as unverified until the hosted runner says otherwise.
- **Manifest matching is platform behaviour.** The `pathPrefix="/"` choice rests on
  `PatternMatcher`/`IntentFilter` semantics, and `android.net.Uri` is not loadable in a plain JVM
  test. No test here can show a tapped share actually cold-starts `MainActivity`.
- **`navDeepLink` matching is Navigation's own** `UriPattern` code (2.7.7), not mine; my `routeOf`
  *mirrors* the rule I believe it implements (scheme, host, exactly one path segment). A mismatch
  between the two is only visible on a device or in a Robolectric test, and both
  `ScreenSnapshotTest`/`PosterCardProvenanceTest` are excluded on aarch64 here.
- **Warm start is not handled today** (`singleTop`, no `onNewIntent`, no `handleDeepLink`), and the
  controller is created inside the composable. Fixing it means hoisting `rememberNavController()`
  into `MainActivity` and calling `navController.handleDeepLink(intent)` from `onNewIntent`. I
  deliberately did **not** fold that uncompiled refactor into this pass: it is a behaviour change to
  the activity lifecycle on a box where I cannot build. **Decision needed from qoder1:** either (a)
  accept it as a second, gated commit in this same branch, or (b) let the manifest claim only what
  cold start can prove — which is why §3.3 is written as a *narrowing* of the claim, not an
  expansion.
- `MainActivity` picks `startDestination` asynchronously (`:95-110`, spinner until the DataStore
  read lands), so NavHost first composes *after* the deep-link intent would be consumed; whether
  2.7.7's NavHost still applies the starting intent in that ordering is unmeasured here.

## 5. Execution state at the stop, and the cost of what ran

Read-only work only. What this pane actually executed for this task:

| Command | Cost measured |
|---|---|
| `cat /proc/loadavg`, `ps`, `ls`, `sed`, `grep` over `App/` | negligible; all sub-second, single-pass over ~225 Kotlin files |
| `git ls-remote --heads https://github.com/rehanradd/radd-stream.git` | one HTTPS read, ~1 s wall, no local CPU of note; **this is the same shape as the 90-second poller already running in this pane (pid 1807491)** |
| `git worktree add -b q4-deeplink-20261030 /tmp/q4_deeplink 6a441ec` | **the only non-trivial thing**: 651 files checked out into a new working tree, completed in a few seconds, `Updating files: 100% (651/651) done`. Costs one-time disk + single-core unpack; adds a persistent tree at `/tmp/q4_deeplink` |

The next heavy command in my plan would have been the JVM gate —
`/tmp/qbuild.sh -Dorg.gradle.jvmargs='-Xmx1536m' :app:compileDebugKotlin :app:testDebugUnitTest`
— measured in Sessions 27/30/31 at **7–12 minutes of this box's entire CPU** per run. I had not
started it and would not have: this task's own brief forbids Gradle. No python, no sqlite, no test
module, no crawl and no build were run for this task at any point.

## 6. Two background jobs in this pane, as the brief asked before I started

Both belong to the previous (cleared) session of this same account and **both are still running**,
each at 0.0% CPU:

- `pid 1770529` (up ~18 h) — a resource health-watch loop: every 45 s reads `/proc/meminfo`,
  `SwapFree`, `loadavg` and the service cgroup, printing only on a state change. No writes, no builds.
- `pid 1807491` (up ~15 h) — a `git ls-remote --heads` poller every 90 s watching remote refs,
  writing `/tmp/q4_heads_baseline.txt` / `/tmp/q4_heads_now.txt`. Read-only network, no fetch into
  this repo.

I left both running rather than killing them (reversible, and the ref watcher looks like something
the supervisor may still want); say the word and I will stop either one.

## 7. Untouched, as instructed

`/tmp/q4_adultkey` (detached at `024f554`) was only listed, never read into or modified — handed to
qoder3. `/opt/radd-stream` was not committed from, reset, or cleaned; the only git write this pane
performed was creating its own worktree/branch.
