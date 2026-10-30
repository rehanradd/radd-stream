# Spec Adult Token Sampling

> Moved **verbatim** out of `Fast_Fetch/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `Fast_Fetch/AGENTS.md`
> carried at this sha. Law stayed in `Fast_Fetch/AGENTS.md`; this is the reference prose it now links to.
### from `Fast_Fetch/AGENTS.md` lines 176-188

| Token | Live sample (12 rows each) | Verdict | Decision |
|---|---|---|---|
| `adult` | 10/12 are real Brazzers/TeamSkeet *"Adult Short Film …"* studio releases; the only false hits are two *Shin-chan* rows | mostly REAL branding | **KEEP** `\badult\b` |
| `naughty` | 13/14 real (studio "Naughty ..." titles) | overwhelmingly REAL | **KEEP** `\bnaughty\b` |
| `hunters` | 0/12 adult — every hit is a mainstream title | never a porn brand | **REMOVE** `\bhunters\b` |
| `rabbit` | 0/12 adult — every hit is a mainstream title | never a porn brand | **REMOVE** `\brabbit\b` |

**Mainstream works the removed tokens were hiding** (real, family/general catalog, must
come back clean): *KPop Demon Hunters* (and its *Sing-Along* concert), *Wallace & Gromit:
Curse of the Were-Rabbit*, *1001 Rabbit Tales*, *Rabbit School*, *Transformers Prime: Beast
Hunters*, *Holy Night: Demon Hunters*, *Peter Rabbit*, *Jojo Rabbit*. *Shin-chan: The Adult
Empire Strikes Back* stays flagged only because of `\badult\b` — that is accepted (10 of 12
`adult` hits are genuinely adult), it is the deliberate cost of keeping the token.
