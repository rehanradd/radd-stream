# Update banner — the two questions that are the owner's, not a lane's

> **Ruling being obeyed.** Muse, 2026-11-01: *keep the existing banners unchanged, add no new offer
> banner, document the two banner questions for the owner later.* This file is that documentation.
> It changes no code, adds no string, and lands nothing. Written on
> `q4-update-banner-questions-c2528e1` off trunk `c2528e1`; every line number below was read off
> `c2528e1`, not off a branch of mine.

---

## 1. What the banner is on trunk today — measured

| Fact | Where | Measured |
|---|---|---|
| The offer fires on **any non-empty http(s) URL**, and on nothing else | `App/app/src/main/kotlin/com/raddstream/app/viewmodel/HomeViewModel.kt:80-84` (`AppUpdate.from` → `WireText.isHttpUrl`) | read 2026-11-01 |
| Nothing about the build is known to the client: no version code, no digest, no size | the `AppUpdate` data class carries `url` and `publishedAt` only, `HomeViewModel.kt:74-79`; its own KDoc says *"The published body carries no version code, so this cannot compare versions"* | read 2026-11-01 |
| The dialog is rendered on Home and dismissible for the session | `ui/screens/HomeScreen.kt:171-172`, `HomeViewModel.kt:172-175` (`dismissUpdate` remembers the URL), `:181-192` (`checkForUpdate`) | read 2026-11-01 |
| Remote config is decoration: a thrown read or a malformed body produces **no** banner and no error | `HomeViewModel.kt:177-193` — the catch returns without touching `_uiState` | read 2026-11-01 |
| The operator panel already has the three fields the client cannot see | `Fast_Fetch/admin_panel.py:1671-1676` (defaults `""`, `0`, `0`), `:2283-2285` (written to the config), `:3172-3175` (the form rows) | read 2026-11-01 |

**And what the running deployment actually serves.** `GET http://92.4.95.252/api/v1/app/remote-config`,
read 2026-11-01:

```
keys        = [ads, apk_update_url, currency, feature_flags, link_shorteners,
               maintenance_mode, payments, success, updated_at, vip]
apk_update_url = ''          updated_at = 0          maintenance_mode = False
apk_update_sha256 / apk_update_size_bytes / apk_update_version_code : ABSENT from the body
```

So the banner is **silent today and has never shown a build to anyone**: there is no URL. It also
cannot become honest by client code alone, because the three fields that would make it honest are
not on the wire yet — the panel can write them, this deployment's response does not carry them.
That is a deployed lag, the same shape as the `settings_unavailable` lag reported on 2026-10-31:
the code is ahead of what `92.4.95.252` is serving.

## 2. The offer that was declined

`ede66f4` on `q4-phase2-upd1b-c2528e1` (hosted Android CI `success`, run `41267702882`; six paths:
`VipRemoteConfig.kt`, `WireText.kt`, `HomeViewModel.kt` + `VipRemoteConfigTest`, `WireTextTest`,
`AppUpdateTest`). It required **all three** before showing anything:

1. a link the app can honestly call verifiable — `https` anywhere, plain `http` only to the
   device's own loopback (`WireText.isVerifiableDownloadUrl`);
2. a 64-character lowercase SHA-256 published beside it;
3. a published `versionCode` strictly newer than the one this build carries.

The reason it was escalated instead of gated is the consequence in its own commit message: **the
banner goes quiet** for a deployment whose operator published only a URL, which is every
deployment. The ruling kept the existing banner, so nothing here changes either way.

## 3. Question 1 — is a banner that goes quiet until the owner fills the panel the right banner?

> UPD-1a gave the panel a digest, a size and a version code. The stricter offer would show nothing
> until those are filled in. Is that the product you want?

The two answers are genuinely different products, and neither is a bug:

- **For the strict offer.** An empty digest is *unchecked*, not *checked and fine*. `openDownload`
  fires `ACTION_VIEW` and never asks `REQUEST_INSTALL_PACKAGES`, so this app receives no bytes and
  can hash nothing; whatever the wire delivers is what installs, silently, with no version compare
  to notice a rollback. On that reading a banner that only appears once the owner has typed a
  digest is a banner that has earned its verb.
- **Against it.** Today nobody has filled those three fields in — measured: the public body carries
  none of them. A strict rule therefore does not "hide a risky offer", it **switches the update
  channel off** until an operator who does not know the fields exist decides to fill them. On a
  deployment where the fix might be urgent, the quiet banner is the one that never tells anyone.

What would settle it is not code but a decision about who operates these installs: if the owner
expects to fill the digest in the panel as a matter of routine, the strict rule costs nothing and
buys a real claim. If the owner expects an install base to be told about a fix by an operator who
will only ever paste a URL, the strict rule is a mute switch.

**Second half of the same question, and it is smaller:** what does the banner *say*? Trunk's copy
claims "a new build is available" while `AppUpdate` has no version, no date the server actually
stamped (`updated_at = 0` on this deployment) and no size. If the banner stays as-is, the wording is
the only thing standing between the claim and the check — and this repo's own precedent (a card that
advertises what the build cannot deliver sends the reader hunting) says the wording is where the
honesty has to live.

## 4. Question 2 — must the APK link be on the viewer's own server?

> Every hand-off in this app — external player, download, share — is refused unless its URL is the
> same host and port as the catalog server the viewer configured (`ApiProvider.isSameOriginAsServer`,
> `App/app/src/main/kotlin/com/raddstream/app/network/ApiProvider.kt:101-107`, whose KDoc states
> *"Every hand-off in the app ... checks this first"*). The declined offer did **not** apply that
> rule to the APK link; it required `https`-or-loopback and nothing about who hosts it. Intentional,
> or an oversight?

Both readings are defensible, and the code cannot tell you which one the product wants:

- **Required.** The rule already exists, already covers the three hand-offs a viewer can take, and
  an install is the most consequential hand-off in the app. Same-origin also collapses a phishing
  shape: an operator's own server handing out its own APK has no third-party host to impersonate it.
- **Deliberately not required.** The other three hand-offs carry *media* through *our* redirector
  (`streamRedirectUrl` is, in that file's words, *"the ONLY playable address this app ever builds"*),
  so same-origin is almost free there. An APK is a *release artifact*: the natural home for it is a
  GitHub release, a CDN, a mirror. Requiring same-origin means a deployment behind cleartext
  `92.4.95.252` may only hand out an APK over cleartext `92.4.95.252` — which is strictly worse for
  an install than for a video frame. The `https`-or-loopback rule in `ede66f4` was written as the
  *weaker but coherent* limit: it restricts the **wire**, not the **host**.

This matters more than it looks because the two rules point in opposite directions on today's
deployment: same-origin would *force* the cleartext host, `https`-required would *forbid* it. Only
the owner can say which half of that trade they want, and neither is derivable from the code.

## 5. Consequences of the ruling, stated so nobody re-derives them

- **`ede66f4` is withdrawn from the gate queue.** It is not "partially landable": its one
  general-purpose fix, the IPv6 bracket handling, lives inside `isVerifiableDownloadUrl` — a
  predicate that exists only in that slice (`git grep -c isVerifiableDownloadUrl c2528e1` → no
  matches). Landing the fix without the feature would add a function nothing calls.
- **Therefore the IPv6 false refusal at `a1bfaaec` is not a trunk defect** and needs no trunk fix.
  It was a bug in the new predicate: cutting the host at the closing bracket left `"[::1"`, which
  matched nothing. Fixed in `ede66f4` with the refusals that stop it degrading into "any bracketed
  host is loopback" (`WireTextTest`). If the banner is ever revived, that test suite is the reason
  the bug does not come back.
- **`apk_update_size_bytes` would be read by nothing even if it were published.** This app has no
  download of its own to put a progress meter in; the field is decoded for completeness and
  displayed nowhere. That is a deliberate dead value, not a wiring TODO.
- **No new offer string was added anywhere by this doc**, and no existing banner, dialog, or
  copy line was modified. Verified with `git diff --name-status c2528e1 HEAD` on this branch: one
  file, this one.

## 6. What a lane needs from the owner to act later

One line each, in the owner's words, is enough:

1. *Quiet until the digest and version code are filled in: yes or no* — decides Question 1 and
   whether `ede66f4` is revived as-is, weakened, or deleted.
2. *The APK link must / need not be on the viewer's own server* — decides Question 2 and whether
   `isSameOriginAsServer` gains a fourth caller.

Until both are answered, the banner on trunk stays as `c2528e1` wrote it, and the alternative is
preserved on `q4-phase2-upd1b-c2528e1` at `ede66f4` — CI green, unmerged, and not waiting on a gate.
