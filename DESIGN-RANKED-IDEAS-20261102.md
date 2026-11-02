# Radd Stream — ranked design ideas (for owner batch approval)

Lane: qoder8. Date: 2026-11-02. Supervisor order ~08:45 PKT.
**Status: proposals only — no code change, no redesign started, nothing pushed.**
This file is deliberately UNTRACKED (`git status` shows it, it is not committed, not pushed).
Reason: `q8-fix-resume-key-20261102` @ `f97b6f4` is a CI-verified gate-ready tip, and a notes
commit on top of it would supersede the sha a gate may be in flight against. Ask qoder8 to commit
this to a separate docs branch after that gate lands if the owner wants it in Git history.

Sources: our own App code read-only (`/tmp/q8_resume/App`; the 6 commits between `f97b6f4` and trunk
`7f4cc64` touch no UI/viewmodel files, so layout code here == trunk), `themoviebox.xyz` and
`m1.multimovies.courses` public pages (MovieBox's detail page returned a 444 / "high risk" upstream
error, so its playback UI is inference from that site's own CSS class names), and 2024–2026 UX
articles. Rules honored: no sign-in, no video download, no challenge bypass, no copying of
logos/posters/artwork/code, no verbatim text beyond a short UI label.

Totals: **51 items** = 44 screen ideas + 7 article-derived patterns. Marks: **KS** Keep it simple /
**NL** Nice to have later / **TC** Too complex — skip.

---

## Part A — global ranking, cheapest-and-highest-impact first

### Batch 1 — copy, removal, and reorder only (no new screens, no new settings)

| # | Screen | Idea (one sentence) | Mark |
|---|---|---|---|
| 1 | Detail | Stop the quality badge from ever rendering the server's raw `releaseTitle`, closing the one place a hoster name can reach the screen. | KS |
| 2 | Player | Strip HTTP codes, decoder error names, raw exception text, and the retry/backoff policy line out of the visible UI and replace them with one plain "This one didn't work — trying the next". | KS |
| 3 | Detail | Replace the words "print" and "prints" in user-visible strings with plain "quality" and "source". | KS |
| 4 | Player | Drop "HLS", "expiring link", and the codec-plus-GB second line from the player chrome, keeping only the quality name the user chose. | KS |
| 5 | Continue Watching | Move the Continue Watching rail to the very top, above the hero, because a pinned resume row is what retention data supports and leaders put it first. | KS |
| 6 | Continue Watching | Add long-press "Remove from Continue Watching", the single most-requested fix in this category. | KS |
| 7 | Continue Watching | Auto-drop a title from Continue Watching once it is finished, so the row stops lying. | KS |
| 8 | Home | Make the hero's "Watch Now" start playback directly instead of opening Detail, cutting the path to playing from two taps to one. | KS |
| 9 | Region | Say plainly on the Region screen that the choice only changes audio and subtitle defaults plus ordering, not which titles exist. | KS |
| 10 | VIP | Retire the "Watch Ad for 4-Hour VIP Pass" button or its "this build has no ad player yet" note, because a control that admits it is fake costs trust. | KS |
| 11 | Search | Fill the empty search box with recent searches plus trending titles instead of the static "Search your catalog" line. | KS |
| 12 | Search | Make the no-results state explain the cause and drop active filters in one tap, so a filtered-empty result never blames the user's query. | KS |
| 13 | My List | Draw the existing progress bar on My List tiles too, since the card already supports it and My List just does not pass progress. | KS |
| 14 | Detail | Collapse the movie's full source list behind a "More qualities" tap the way episodes already do, so Detail reads as poster → Play → synopsis. | KS |
| 15 | Downloads | Show one plain "Not enough space" line rather than raw byte arithmetic and "unknown size". | KS |
| 16 | Maintenance | Add a retry-and-last-checked line to the Maintenance screen, which currently offers no way back except changing server. | KS |
| 17 | Home | Keep autoplay previews off and do not add them, since users revolted enough to force an official opt-out elsewhere. | KS (a do-not-do) |
| 18 | Settings | Leave the Server URL field and the "catalog server you operate" text where they are, since Setup genuinely requires them. | KS (a do-not-do) |
| 19 | Player | Keep the double-tap ±10s gestures and the ~3.8s auto-hide, which already match the mainstream convention. | KS (a do-not-do) |
| 20 | VIP | Keep the price always visible and never gate browsing behind it, which our current honesty line already does right. | KS (a do-not-do) |
| 21 | Setup | Keep Setup's "test connection before Continue" gate, which is already better than the norm. | KS (a do-not-do) |

### Batch 2 — small code, one existing widget reused

| # | Screen | Idea | Mark |
|---|---|---|---|
| 22 | Settings | Add an autoplay-next-episode toggle, the one playback switch we lack. | KS |
| 23 | Search | Keep the 300ms debounce and drop the separate submit path so typing and submitting cannot disagree. | KS |
| 24 | Browse | Add numbered pagination or a load-more label instead of silent infinite scroll. | NL |
| 25 | Region | Offer to skip the first-run Region screen in one tap, so a mandatory screen is not a wall. | NL |
| 26 | Settings | Group the current loose sections into three (Playback, Downloads & storage, Account). | NL |

### Batch 3 — medium: reuse Search's facets or Downloads' list machinery

| # | Screen | Idea | Mark |
|---|---|---|---|
| 27 | Browse | Give Browse the genre and language filters that Search already has, since Browse today is one unfiltered grid. | KS |
| 28 | Browse | Copy the collapsed "Filter & Sort" panel that shows an active-count badge, using our existing facets. | NL |
| 29 | Player | Persist subtitle style and default language across sessions, since caption preferences should outlive one viewing. | NL |
| 30 | Downloads | Let in-app "keeps" pause and resume like device downloads do, since keeps are Play-or-cancel only today. | NL |
| 31 | Downloads | Choose download quality on this screen too, not only on Detail. | NL |
| 32 | My List / Continue Watching | Give Continue Watching a bottom-nav entry, or keep it Home-rail-only if the four tabs must stay four. | NL (needs owner decision) |
| 33 | Detail | Show runtime and a cast row, the two things our Detail screen is missing versus every comparable app. | NL (data-dependent) |
| 34 | VIP | Show what VIP actually unlocks in the catalog rather than only the entitlement state. | NL (needs product definition) |
| 35 | Home | Add a numbered "Top rated" list row using the rating field we already render. | NL |
| 36 | Home | Grow past the current four rails toward genre and language shelves as soon as the backend can serve them honestly. | NL |
| 37 | Detail | Add a "more like this" row at the bottom from the same genre. | NL (needs a backend route) |
| 38 | Detail | Surface a "this source is slow" state before Play, since abandonment rises per second past a two-second start and we already store link health. | NL |

### Batch 4 — too complex, skip or simplify (nothing here is a small change)

| # | Screen | Idea | Mark |
|---|---|---|---|
| 39 | Home | Build a "because you watched" personalised recommendation row now, while only four rails are honest today. | TC — skip |
| 40 | Search | Add natural-language or semantic search. | TC — skip |
| 41 | Detail | Show a per-source provider picker screen with diagnostics per link. | TC — skip |
| 42 | Player | Add skip-intro and skip-credits, which needs per-title timing data we do not have. | TC — skip |
| 43 | Downloads | Add smart downloads that auto-delete a finished episode and fetch the next. | TC — skip |
| 44 | Settings | Add profiles or kids modes, or a theme picker. | TC — skip |

---

## Part B — every idea, grouped by screen (batch number from Part A in brackets)

**Home (hero + rows)** — [5] continue-watching rail above the hero (KS); [8] hero "Watch Now" plays directly (KS); [17] keep autoplay previews off (KS); [35] numbered top-rated row (NL); [36] more rails when the backend can serve them (NL); [39] personalised "because you watched" row (TC — skip).

**Browse** — [27] add genre and language filters from Search (KS); [28] collapsed Filter & Sort with active count (NL); [24] numbered pagination or load-more label (NL).

**Search** — [11] recents plus trending in the empty box (KS); [12] zero results that explains and one-tap clears filters (KS); [23] unify debounce and submit paths (KS); [40] semantic search (TC — skip).

**Detail (Play/Download work in progress)** — [1] never render raw `releaseTitle` in the quality badge (KS); [3] say quality and source, not print (KS); [14] collapse the movie source list behind "More qualities" (KS); [33] runtime and cast (NL); [38] "this source is slow" preflight (NL); [37] more-like-this row (NL); [41] per-source provider picker screen (TC — skip).

**Player (MX-style work in progress)** — [2] remove failover and HTTP internals behind one plain message (KS); [4] drop HLS, expiring-link, codec and GB chrome (KS); [19] keep double-tap seek and auto-hide (KS); [29] persist subtitle style and default language (NL); [42] skip-intro and skip-credits (TC — skip).

**Downloads** — [15] plain "Not enough space" line (KS); [30] let keeps pause and resume (NL); [31] choose download quality here too (NL); [43] smart downloads (TC — skip).

**My List / Continue Watching** — [6] long-press remove (KS); [7] auto-clear finished titles (KS); [13] progress bars on My List tiles (KS); [32] nav entry for Continue Watching (NL, owner decision).

**Settings** — [22] autoplay-next toggle (KS); [18] keep Server URL and About text (KS); [26] regroup into three sections (NL); [44] profiles, kids mode, or theme picker (TC — skip).

**VIP** — [20] price always visible, browsing never gated (KS); [10] retire the fake ad-pass control or its note (KS); [34] show what VIP unlocks (NL).

**Region selection** — [9] state what a region choice actually changes (KS); [25] allow one-tap skip on first run (NL).

**Maintenance / Setup** — [16] retry and last-checked on Maintenance (KS); [21] keep the test-connection gate on Setup (KS).

---

## Part C — the 7 article-derived patterns (ranked into the same list)

| # | Source + date | What users like / hate / want | Carried by | Mark |
|---|---|---|---|---|
| A1 | CTAM/Hub "Value by Design", Jul 2026 | 36% of viewers and 43% of under-25s cancelled over UX, not price or content, so home clutter and dead ends are retention bugs. | items [5][12][27] | KS |
| A2 | TYPENORM Prime Video teardown, Oct 2026 | An ambiguous control that hides which provider and what it costs is the most-hated pattern, so every Play label must state what will happen. | items [1][3][14] — see the owner decision below | KS |
| A3 | r/DisneyPlus Mar 2024, then Disney+ help article Nov 2025 | A Continue Watching row that never clears is hated enough that the service shipped manual removal. | items [6][7] | KS |
| A4 | Fast Company, Feb 2020 | Autoplay previews annoyed users into an official opt-out. | item [17] | KS |
| A5 | NN/g site-search suggestions, 2018 and 2022 | Plain text suggestions beat enriched ones and zero results must never be a dead end. | items [11][12] | KS |
| A6 | MX Player review analyses, 2024–2026 | An excellent player is forgiven; an ad-choked interface is not, so keep ads out of rows and player chrome. | items [10][20] | KS |
| A7 | Forasoft, Oct 2026, citing Akamai | Abandonment rises about 5.8% per second past a two-second start. | item [38] | NL |

---

## Two things the owner must decide, not qoder8

1. **Source naming (A2 vs our redaction policy).** The teardown evidence says users want to know which
   provider a button plays; our design deliberately names nothing ("Nothing here can name a site, a
   hoster or an address") and both studied catalog sites are judged harmful for leaking hoster brands.
   Proposal: name the *behaviour* — "Plays here", "Opens in the provider's page", "Download only" —
   never the hoster, and keep that wording consistent across Detail, Player and Downloads.
2. **Four tabs or five.** Continue Watching wants a nav entry (item [32]), but that breaks the current
   four-tab bar; the cheap alternative is keeping it as the top Home rail only (item [5]).

## Batch recommendation

Batch 1 alone (21 items, all copy, removal, and reorder) fixes the entire technical-vocabulary leak and
the two loudest complaints in this category, with no new screens and no new settings. Batch 4 should stay
unfunded.
