# Session 2026-10-30 (q2 lane) — `[Q2-MB-MINT]`: the play-info mint is account-gated; MovieBox stays catalog-only

Branch `q2-mb-mint` off trunk `072158f`, worktree `/tmp/q2_moviebox`. Task #43, run under a
12-request budget (`curl -sS -m 20`, `nice -n 19`), captures under `/tmp/q2_mint/` and never
committed. The JS chunks were deleted after grepping; the quoted call source survives in
`/tmp/q2_mint/mint_call_source.txt`.

## What was wrong before this

qoder4 measured it and the owner proved it: the site *does* publish playable URLs. 1DM+ captured,
for *Five Friends 2: Mount Klawih* (`subjectId 7295930638539411024`):

- DASH `https://sbcdnw.hakunaymatata.com/dash/7295930638539411024_0_0_1080_h265_600/index_web.mpd`
- SRT `https://cacdn.hakunaymatata.com/subtitle/<id>.srt?Policy=…&Signature=…&Key-Pair-Id=…`

The bare `.mpd` answers 403 `ERROR: ACCESS DENIED`, so the file is real and the CDN grant is
signed. The sentence "this site publishes nothing playable" is retired from `SITES.md` §25.

## The path, found in the site's own player chunk

`_nuxt/6BbZTDSB.js` holds the play call:

```
GET {origin}/wefeed-h5api-bff/subject/play
    ?subjectId=…&se=…&ep=…&detailPath=<slug>&streamSignType=0|1
Accept: application/json, X-Request-Lang, X-Client-Info, X-Source,
Authorization: Bearer <mb_token>   ← added ONLY when the cookie exists
```

`streamSignType` is `1` in a plain browser (no `window.hola_navigator`) and depends on an app
version check inside the app. The endpoint is therefore designed to answer anonymous callers.

## The answer, and it is not a mint

Three unauthenticated probes on the owner's exact subject (same headers that make `/detail`
answer 200; no token, no cookie, nothing replayed):

| Probe | Result |
|---|---|
| `se=0&ep=0&streamSignType=1` | 200, `code: 0`, `streams: []`, `dash: []`, `hls: []`, `hasResource: false` |
| `se=0&ep=0&streamSignType=0` | identical |
| `se=1&ep=1&streamSignType=1` | identical |

Every answer carries `limited: false`, `freeNum: 999`, `vipLocked: false`,
`playConfig: {maxResolution: 480}` and a **fresh anonymous token**:
`set-cookie: token=…` with payload `{"atp": 3, "uid": "<different every call>", "ext": <iat+300>}`.
`atp: 3` is a guest session, and a guest session is handed no resource.

**Verdict: CREDENTIAL-GATED.** The path is public and needs no credential; the grant is not —
it requires a signed-in (or VIP) session, which is an account, not a header. The owner's 1DM+
grant is not replayed, no UA is spoofed and no clearance is solved. **MovieBox stays
catalog-only**: it must not be presented as playable, and no signed URL may be written to the
vault, because a week later it is a dead link wearing `status="active"`. If the mint ever
becomes public, the deliverable is the *recipe* (template, height, codec, bitrate, subtitle
track id) with `is_temporary=1`, JIT-resolved — never the URL.

## Code and docs in this commit

No importer change: there was no mint to wire. `Fast_Fetch/SITES.md` §25 gains the probe with
its evidence and the rule above, and the two stale "no playable URL" claims are corrected to
"neither public surface carries one, and the mint that does is account-gated".

## NOT verified

Nothing was played or downloaded; no signed URL was written anywhere; the app-only surface was
not exercised (that is the owner's device, not this host). JOB 2's bounded crawl follows on its
own branch.
