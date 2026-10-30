# Spec App Source Layout

> Moved **verbatim** out of `App/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `App/AGENTS.md`
> carried at this sha. Law stayed in `App/AGENTS.md`; this is the reference prose it now links to.
### from `App/AGENTS.md` lines 131-154

```
Repository root/
├── .github/workflows/
│   ├── ci.yml                                  ← tests, lint, debug APK on push/PR
│   └── release.yml                             ← signed APK on version tag
└── App/
    ├── app/src/main/kotlin/com/raddstream/app/
    │   ├── data/                               ← DataStore server settings
    │   ├── network/                            ← Retrofit API and JSON models
    │   ├── repository/                          ← catalog data access
    │   ├── ui/
    │   │   ├── components/PosterCard.kt
    │   │   ├── navigation/               ← Screen.kt, NavGraph.kt (4-tab bottom nav)
    │   │   ├── screens/                  ← Setup, Home, Search, Detail, Player, MyList, Settings
    │   │   └── theme/
    │   ├── viewmodel/                     ← setup, catalog, search, detail, favorites, settings
    │   ├── player/PlaybackService.kt      ← Media3 MediaSessionService
    │   └── MainActivity.kt
    ├── app/src/test/                            ← JVM unit tests
    ├── gradle/wrapper/
    ├── gradlew
    └── docs/
```

