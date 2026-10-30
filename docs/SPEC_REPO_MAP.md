# SPEC REPO MAP

> Moved **verbatim** out of `AGENTS.md` by the 2026-10-30 documentation diet.
> The diet splits LAW / LOG / SPEC and never deletes: every line below is
> byte-identical to what `AGENTS.md` carried at `dc73ac7`.
### from `AGENTS.md` lines 12-56

```
radd-stream/                        ← repo root
│
├── AGENTS.md                       ← THIS FILE — start here
├── README.md                       ← public-facing project description
├── DISCLAIMER.md                   ← legal / framing notice
├── setup_check.py                  ← system sanity check for backend
├── run.sh / run.bat                ← one-command launchers (backend)
├── requirements.txt                ← empty (zero pip deps)
├── .gitignore                      ← excludes local .replit, databases, build and cache files
├── ORACLE_DEPLOYMENT.md             ← Oracle access, GitHub auth, and deployment runbook
├── docs/
│   ├── AI_HANDOFF_PROMPT.md         ← short prompt to resume in another AI tool/account
│   ├── AGENT_BOOTSTRAP.md           ← project context and safe onboarding steps
│   ├── PROJECT_MAP.md               ← verified locations, branches, CI, and server status
│   └── SESSION_CHECKPOINT.md        ← concise cross-agent progress and next action
│
├── Fast_Fetch/                     ← 🐍 PYTHON BACKEND (data engine + REST API)
│   ├── AGENTS.md                   ← deep backend-specific agent guide (read this for backend work)
│   ├── DAO.md                      ← eternal mission directive
│   ├── CONTINUITY.md               ← session log + milestone tracker (update every session)
│   ├── API_V2.md                   ← catalog v2 data model + REST contract (read before designing any endpoint)
│   ├── SITES.md                    ← per-site scraping reference
│   ├── SETUP.md                    ← setup instructions for backend
│   ├── ANDROID_INTEGRATION.md      ← how Android app consumes the backend
│   ├── fast_fetch.py               ← MAIN ENGINE (6,513 lines, stdlib only)
│   ├── viewer.py                   ← REST API + dashboard HTTP server
│   ├── config.py                   ← project-level constants
│   ├── test_database.py            ← 124 offline unit tests (measured 2026-10-29)
│   ├── test_vidout.py              ← 6 VIDOUT-specific tests
│   └── test_all_sites.py           ← live 10-site audit
│
└── App/                            ← 📱 ANDROID APP (Kotlin + Jetpack Compose)
    ├── AGENTS.md                   ← deep app-specific agent guide (read this for app work)
    ├── README.md                   ← app architecture overview
    ├── .github/workflows/          ← nested here; GitHub requires repo-root .github/workflows
    ├── docs/
    │   ├── PLAN.md                 ← 3-phase feature roadmap
    │   ├── TECH_STACK.md           ← Kotlin/Compose/Media3 rationale
    │   └── BUILD_PLAN.md           ← full CI/CD strategy (no local Android Studio needed)
    ├── design/
    │   ├── DESIGN_SYSTEM.md        ← colors, fonts, spacing, components
    │   └── SCREENS.md              ← ASCII wireframes for 7 screens (NavGraph registers 13 routes)
    └── app/src/                    ← Gradle Android app source (Kotlin)
```
