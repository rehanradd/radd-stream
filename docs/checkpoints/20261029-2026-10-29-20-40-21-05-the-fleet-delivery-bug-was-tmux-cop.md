# 2026-10-29 20:40–21:05 — the fleet delivery bug was tmux copy-mode, not the submit key

> rotated out of `docs/SESSION_CHECKPOINT.md` by the 2026-10-30 documentation diet; text unchanged.

## 2026-10-29 20:40–21:05 — the fleet delivery bug was tmux copy-mode, not the submit key

**Two retractions and one root cause, all about my own monitoring, not about the code.**

1. *"A lane is idle when `esc to cancel` is absent"* — **false.** A lane sitting between tool calls
   renders no spinner while it is still mid-turn. What actually distinguishes working from idle is
   CPU: read `/proc/<pid>/stat` fields 14+15 (utime+stime jiffies) twice and take the delta. Measured
   this window, 1 Hz sampling: q1 `+39` and q5 `+44` (both genuinely working), q2 `+1`, q3 `+1`
   (genuinely idle — and idle because their brief had never been delivered, not because they finished).
2. *"The pane placeholder `Type your message` proves idle"* — also **false**, for the reason above.
   Both heuristics are retired; the jiffies delta is the detector, and `pane_in_mode` is the second
   check, described next.
3. **Root cause of the two undelivered briefs.** `Q2-SCENARIO-MATRIX` and `Q3-SEARCH-LATENCY` were
   sitting complete in those panes' input boxes and would not submit: `send-keys Enter`, `send-keys -H
   0d`, everything was swallowed. `tmux list-panes -a -F '#{pane_in_mode}'` returned **`in_mode=1` for
   qoder2 and qoder3 and `0` for the other three**. The panes were in tmux copy-mode — a scrollback
   mode entered by an earlier `capture-pane`/mouse event — so every keystroke I sent was being parsed
   as a copy-mode command (my stray `Z` ran a search), and the CLI never saw a byte. `tmux copy-mode -q
   -t <pane>` exits it; the very next `-H 0d` submitted both briefs and both lanes started generating
   within seconds. **Order of operations for any future delivery: check `pane_in_mode` first, then
   jiffies, then the submit key.** A lane that "ignores" a prompt is almost certainly in copy-mode, and
   re-pasting into it would have duplicated a 2.8 KB brief — the check is cheap and the mistake is not.

**Corrected pane → process map, read from `/proc/<pid>/cmdline` `--config-dir` rather than from my
guessed table.** The old table was wrong: I had labelled pid 1242671 as "qoder1", and 1242671 is
`.qoder_account4` — **that is this session**, the Master Orchestrator. The true map is pane shell pid →
foreground `qodercli`:

| tmux session | pane shell | live qodercli | `--config-dir` | who |
|---|---|---|---|---|
| qoder1 | 1241867 | **1246665** (started 17:15) | `/home/ubuntu/.qoder` | q1 — ad cadence client |
| qoder2 | 1241873 | **1388336** (started 19:48, `Sl+`) | `.qoder_account2` | q2 — ledger + scenario matrix |
| qoder3 | 1241883 | **1242667** (`Sl+`) | `.qoder_account3` | q3 — search latency A..F |
| qoder4 | 1241894 | **1242671** (`Rl+`) | `.qoder_account4` | **me**, this lane |
| qoder5 | 1241905 | **1242673** (`Rl+`) | `.qoder_account5` | q5 — monetization fields |

`1242663` (`.qoder_account2`, started 17:03) is still `SIGSTOP`'d at ~276 MiB in the qoder2 pane's
process group and is **not** the pane's owner — 1388336 is (`+`). It stays stopped rather than killed
for the same reason as before: I am not certain enough of the tty ownership to spend a 276 MiB win on
it. Any idle judgement made against 1242663 was measuring a frozen process, which is why it read as
"idle" forever.

**State at hand-off.** All four worker lanes generating: q1 on `Q1-CACHE-WIRING`/ad-cadence enforcement,
q2 on `Q2-SCENARIO-MATRIX` (it is reading `redact.py`'s route classification before writing assertions,
which is the right instinct), q3 on `Q3-SEARCH-LATENCY` A..F, q5 on `Q5-MONETIZATION-FIELDS` (running
`test_admin_panel.py` in `/tmp/q5_monet`). Box: 4,800 MiB available, swap 1,925/6,143 used — no lane is
touching the production catalog, and merge batch 4 (#9) stays held for exactly that reason.
Backend CI is green at `c2d11be` on both refs; production still runs the dirty `bf9e565` tree and the
restart decision (#19) remains the owner's, not mine.

