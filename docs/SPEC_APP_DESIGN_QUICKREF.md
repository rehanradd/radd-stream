# Spec App Design Quickref

> Moved **verbatim** out of `App/AGENTS.md` by the 2026-10-30 documentation diet. The diet splits
> LAW / LOG / SPEC and never deletes: every line below is byte-identical to what `App/AGENTS.md`
> carried at this sha. Law stayed in `App/AGENTS.md`; this is the reference prose it now links to.
### from `App/AGENTS.md` lines 210-228

See [`design/DESIGN_SYSTEM.md`](../design/DESIGN_SYSTEM.md) for full spec. Key values:

```kotlin
// Colors
Background:     #0A0A0F    // near-black
Surface:        #141420    // cards / nav bar
AccentPrimary:  #6C63FF    // buttons, active state (purple)
AccentRed:      #FF6B6B    // favorites heart

// Spacing
Horizontal page padding: 16.dp
Card corner radius:       12.dp
Play button height:       52.dp

// Typography — Inter font (Google Fonts)
Title:    18.sp SemiBold
Body:     16.sp Normal
Label:    12.sp Medium (muted metadata)
```
