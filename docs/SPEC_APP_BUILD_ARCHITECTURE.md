# Spec App Build Architecture

> Moved **verbatim** out of `App/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `App/AGENTS.md`
> carried at this sha. Law stayed in `App/AGENTS.md`; this is the reference prose it now links to.
### from `App/AGENTS.md` lines 88-104

```
Code edit (anywhere)
    │
    ▼ git push
GitHub repo (radddao/radd-stream)
    │
    ▼ triggers
GitHub Actions (Ubuntu runner, free)
    │
    ├── ci.yml      → tests + lint + assembleDebug → uploads APK artifact (7 days)
    ├── release.yml → assembleRelease → signs → creates GitHub Release
    │
    ▼
APK available at:
  Debug:   github.com/radddao/radd-stream/actions  (Artifacts tab)
  Release: github.com/radddao/radd-stream/releases
```
