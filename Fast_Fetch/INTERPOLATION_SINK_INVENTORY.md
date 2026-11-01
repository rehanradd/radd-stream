# Interpolation-sink inventory — `viewer.py`, `admin_panel.py`

**What this file is.** A census of every place these two modules put a value into HTML,
measured against the code at trunk `6014dd5` (host time 2026-11-01 ~05:40). It is an
inventory, not a change set: nothing here was edited. Phase 3's admin work lands on top of
this list, which is why it lives in the branch rather than in a chat window.

**How it was produced.** A nesting-aware template walker over `viewer.py`'s own source
lines (a backtick inside `${ … }` belongs to an inner template, so the outer literal is not
mis-paired — the earlier pass got this wrong and reported 11 phantom unescaped sinks inside
the already-escaped media card). Every line number below is a line you can open. Comment
lines are excluded, so prose about a retired defect is not inventoried as a defect.

---

## The contract these modules are measured against

`ESCAPE_CORE_JS` (`Fast_Fetch/viewer.py:923`) is spliced into **both** page constants —
`DASHBOARD_HTML` at `viewer.py:1531` and `MOBILE_CLIENT_HTML` at `viewer.py:2506` — and ships
four things and only four:

| helper | line | contract |
|---|---|---|
| `escapeHtml` | `:937` | `& < > " '` → entities |
| `raw` | `:940` | wraps a string in `{__raddRaw: …}` — an **object**, and the only thing `esc` will not escape |
| `esc` | `:941` | tagged template; escapes every interpolation **unless** it is a `raw` object |
| `safeHttpUrl` | `:952` | parses, then allows only `http:`/`https:` — a scheme check, because an escaper defends delimiters, not schemes |
| `num` | `:962` | `Number()`, and anything not finite becomes `'0'` — the only way an id reaches markup |

Two consequences that matter to anyone adding a card:

1. `raw()` is **infectious by identity, not by syntax**. `const indBadge = raw(esc\`…\`)`
   followed by `${indBadge}` inside an `esc` template passes markup through unescaped, and
   there is no `raw(` at the interpolation site to warn you. Section C lists those.
2. A plain (untagged) template literal is only a sink if its result reaches **markup**.
   Several of the ones below build a *fetch URL*, an `innerText`, or a DOM **id string** and
   never touch `innerHTML`. They are correct, and they are listed so the next reader does not
   have to re-derive that.

`test_html_escape_guard.py` enforces the shape (unescaped markup template, `on*="…${…}"`,
a second escaper, an unhandled `data-action`, `?token=` in code). It does **not** enforce
anything about Section C, which is why Section C is a file and not a shrug.

---

## A. `DASHBOARD_HTML` — template literals with no `esc` tag

`viewer.py:966-2150`. Verdict column is my reading of where the value goes, not the guard's.

| line | interpolation | reaches markup? | verdict |
|---|---|---|---|
| `:1652` | `${API_BASE}`, `${encodeURIComponent(query)}`, `${encodeURIComponent(currentSitemapSite)}` | no — `fetch()` URL | **correct.** Encoded at the site; `API_BASE` is derived from `location.pathname` at `:1531` |
| `:1663` | `${rows.length}` | no — `innerText` | **correct.** Array length, and `innerText` is not a parser |
| `:1709` | `${slug}` | no — `getElementById(\`btn-fetch-${slug}\`)` | **correct.** Id *lookup*, not markup; the matching id is written through `esc` |
| `:1754` `:1760` | `${num(s.…_count)}` ×5 | no — `innerText` | **correct,** but see the note below on the shadowed `num` |
| `:2037` | `${s.http_status}`, `${s.status}` | yes, as an **attribute value** — the string is `statusTooltip`, interpolated at `:2052` inside `title="${statusTooltip}"` in an `esc` template | **correct** *because of that second hop*: `esc` escapes it at `:2052`. Fragile by construction: a future author who writes `title="` + statusTooltip into a plain template loses the escape. **Watch.** |
| `:2090` | `${window.location.origin}`, `${sourceId}` | no — `video.src`, `.href`, `innerText` at `:2093` | **correct.** Fixed `/api/v1/stream?id=` prefix so the scheme cannot change; `sourceId` is numeric by producer (see `:2600` note). **Watch:** `sourceId` is interpolated *unencoded*, so it is only as safe as the `num()` that made it |
| `:2093` | `${sourceName}` | no — `innerText` | **correct** |
| `:2099` `:2100` | `${streamUrl}` in `vlc://` and `intent:…#Intent;…;end` | no — `.href` **property** assignment | **correct.** The scheme is a literal prefix of the template, and `streamUrl` is the fixed-shape value from `:2090` |

**The shadowed `num`.** `renderStats` defines a local `num` at `viewer.py:1751`
(`null → '—'`, else `toLocaleString()`) that shadows the core `num` (`non-finite → '0'`).
Same name, different semantics, one file apart. Both are safe for `innerText`, but `:1754`
and `:1760` are governed by the local one and `:1989` by the core one. `test_html_escape_guard.py`
matches by *name presence*, so it cannot see this and does not claim to.

## B. `MOBILE_CLIENT_HTML` — template literals with no `esc` tag

`viewer.py:2152-2732`.

| line | interpolation | reaches markup? | verdict |
|---|---|---|---|
| `:2527` | `${encodeURIComponent(query)}`, `${encodeURIComponent(type)}` | no — `fetch()` URL | **correct** |
| `:2600` | `${postId}` in `/api/v1/posts/${postId}` | no — `fetch()` URL | **correct by producer, and only just.** `postId` is `openDetail(num(el.dataset.value))` (`:2513`), and the `data-value` it reads is itself `${num(p.id)}` (`:2546`) — a *path* segment, so an uncoerced value could traverse (`1/../…`) rather than merely encode. The `num()` at `:2513` is load-bearing. **Watch.** |
| `:2607` | `${p.year}` | no — `innerText` | **correct** |
| `:2643` | `${window.location.origin}`, `${sourceId}` | no — `video.src` | **correct** (same shape as `:2090`) |
| `:2654` `:2655` `:2656` | `${streamUrl}` in three `intent:` literals | no — `.href` | **correct** (same shape as `:2100`) |

## C. `raw()` passthroughs — markup injected into escaped templates on purpose

Each of these is safe **because of how the variable was built**, not because of anything at
the interpolation site. That is the part of the surface a source scan cannot check, so it is
written down.

Deliberate `raw(…)` calls at the site (all inside `esc` templates):

| line | what it wraps | why it is safe |
|---|---|---|
| `:1612` `:1613` `:1614` | `' disabled'`, `' · <b …>CLAMPED</b>'`, `' · more'` | closed set of string literals — no data inside |
| `:1700` | `btnHtml` | built at `:1687` from `esc` |
| `:1976` `:1977` `:1983` | `esc\`…${p.year}…\`` / `${p.seasons}` / `${p.imdb_rating}` | the inner `esc` escapes the value, then `raw` marks the finished fragment |
| `:1978` `:1979` `:1991` | `'🔞 18+ ADULT'`, `'🎨 ANIME'`, the no-playlist badge | literal markup; `:1991` is the **adult suppression** badge and its placement behind `p.is_18_plus` is pinned by `test_operator_adult_projection.py`, do not edit it without that suite |
| `:1985` `:2025` `:2026` `:2027` `:2618` | `esc\`…${genresHtml / r.size / r.languages / r.codec}…\`` | inner `esc` |
| `:2045`-`:2049` | `withheld` — the JIT play buttons | `raw(esc\`…\`)`; the only untrusted parts pass through `num(s.id)` and `esc` |

Named passthroughs — `const NAME = …raw(…)` then `${NAME}` inside `esc` (grep the name to
find its construction; every one of these was traced and is built from `esc` or a literal):

`DASHBOARD_HTML`: `:1694 siteTag` · `:1933 sourcePageLinks` · `:1970 posterImgHtml` ·
`:1973 siteBadges` · `:1980 indBadge` · `:1981 cntBadge` · `:1982 langBadge` ·
`:1985 genresHtml` · `:1994 originalPageLink` · `:1997 sourcePagesHtml` ·
`:2019 rSiteBadge` · `:2020 epBadge` · `:2056 resumableBadge` · `:2057 sizeStr` · `:2060 withheld`

`MOBILE_CLIENT_HTML`: `:2547 poster` · `:2552 typeBadge` · `:2553 yearBadge` · `:2554 imdbBadge`

Two of these deserve a sentence each. `posterImgHtml` (`:1962`) and `poster` (`:2541`) put
`posterHref` into `src="…"` — the value is the output of `safeHttpUrl()`, so a
`javascript:` poster URL from a poisoned scraper returns `''` and the branch is not rendered
at all. `sourcePagesHtml`/`originalPageLink` are the same pattern over `source.url` and `p.url`.
**Any new card that shows a URL must go through `safeHttpUrl`, not through `esc`.**

## D. `admin_panel.py` — the Python side, raw by construction

`_e` (`admin_panel.py:2951`) is the **only** `html.escape()` call in this module. Three
helpers escape one of their arguments and emit the other raw, so the caller owns the
security of the value:

| line | helper | escaped | emitted raw |
|---|---|---|---|
| `:2955` `_kv` | `<dt>{_e(key)}</dt><dd>{value}</dd>` | the key | **the value** |
| `:2963` `_table` | `<th>{_e(h)}</th>` / `<td>{cell}</td>` | the headers | **every cell** |
| `:3211` `card` | `<h2>{_e(title)}</h2>{body_html}` | the title | **the body** |

`_kv` and `_table` are therefore only safe because their callers pass `_e(…)`/`_num(…)`
output. **That claim is checked by grep, not by proof: I do not read every call site.** A
line-oriented scan for `("label", value)` pairs whose value carried no visible escaper
returned six hits — `:2351` (a Python-side default, never rendered), `:2830`/`:2832`/`:2877`/
`:2879` (all inside the *usage* page's own `card` at `:2812`, which escapes both halves, so the
scan's escaper test was simply looking at the wrong helper), and `:3118` (already `_e`-wrapped,
a regex artifact). **No live unescaped `_kv`/`_table` value was found.** That is a better result
than the scan's headline, and it is also exactly the kind of result that goes stale the moment
someone adds a card. The convention is unenforced, and it is the first thing Phase 3 will
break: a new screen that does `_kv([("note", row["note"])])` with a scraped or client-supplied
string is a stored-XSS in the operator console, and no suite here would notice.

The counter-example already in the file, worth copying: the *usage* page defines its own
`card(title, pairs)` at `:2812` that escapes **both** halves
(`<dt>{_e(str(key))}</dt><dd>{_e(str(value))}</dd>`), which is why the `card("Accounts", …)` /
`card(dim, pairs)` family at `:2822-2880` is safe even though one of its labels comes from a
client header. When adding a screen, prefer that shape.

| line | site | verdict |
|---|---|---|
| `:1076` | `{notice}` in the login page, `<form action="{_e(target)}">` | **correct.** `notice` is one of three literals (`:1037-1042`) chosen by a closed-vocabulary `reason` (`locked`/`signed_out`), never caller text — the username is *not* echoed, and the docstring at `:1030-1034` records that |

## E. What a new card must satisfy (checklist for Phase 3)

1. Text into markup → interpolate it through `esc`. Never `raw()` your own string.
2. A URL → `safeHttpUrl()` first, then `esc`. An escaper does not stop `javascript:`.
3. An id → `num()`. If it goes into a *path* segment, that `num()` is the only thing
   between a scraped value and route traversal (`:2600`).
4. A `data-action` → add the matching handler to the map that owns it, or
   `test_html_escape_guard.py` fails the build.
5. No `on*="…${…}"`, ever. Entity decoding runs before the JS parser inside an attribute, so
   no escaper survives there; use `data-*` and the delegated handler.
6. In `admin_panel.py`, if you use `_kv`/`_table`/`card`, escape your own values or copy the
   `_e(str(value))` shape from `:2812`.

## F. Stated limits of this inventory

- **Line numbers, not semantics.** `file:line` is where to look; the verdict column is my
  reading of data flow, made by tracing each variable to its assignment. It could be wrong
  about a value I did not trace, and Sections A/B verdicts rest on the producer site named.
- **Nothing here was executed.** No page was rendered and no browser ran this JS — that is
  why `test_operator_adult_projection.py`'s handle-definition case exists, and why the two
  `Watch` rows are marked as fragile rather than proven safe.
- **Only two modules.** `viewer.py` and `admin_panel.py`. Any other file that emits HTML is
  not in this inventory and is not covered by the guard.
