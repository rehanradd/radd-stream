# 🎨 Design System — RADD Stream Android App

## Philosophy
> **Dark. Cinematic. Effortless.**  
> Every pixel serves the content. UI disappears when you're watching. Navigation is obvious to a first-time user.

---

## Color Palette

### Base Colors
| Token | Hex | Usage |
|---|---|---|
| `background` | `#0A0A0F` | App background (near-black with blue tint) |
| `surface` | `#141420` | Cards, bottom sheets, dialogs |
| `surface_variant` | `#1E1E2E` | Input fields, chip backgrounds |
| `on_background` | `#FFFFFF` | Primary text |
| `on_surface` | `#E0E0EE` | Secondary text, labels |
| `on_surface_muted` | `#7070A0` | Hints, metadata, timestamps |

### Accent Colors
| Token | Hex | Usage |
|---|---|---|
| `accent_primary` | `#6C63FF` | Primary buttons, active tabs, Play button glow |
| `accent_secondary` | `#FF6B6B` | Favorites/heart icon, badges, error states |
| `accent_gold` | `#FFD700` | Rating stars, premium badges |
| `accent_green` | `#4CAF50` | Connected status, success toasts |
| `accent_red` | `#F44336` | Error states, disconnect indicator |

### Gradient
```kotlin
// Hero banner gradient (bottom fade to background)
Brush.verticalGradient(
    colors = listOf(Color.Transparent, Color(0xFF0A0A0F)),
    startY = 0f,
    endY = Float.POSITIVE_INFINITY
)

// Play button gradient
Brush.linearGradient(
    colors = listOf(Color(0xFF6C63FF), Color(0xFF9C88FF))
)

// Card shimmer gradient (loading state)
Brush.horizontalGradient(
    colors = listOf(
        Color(0xFF1E1E2E),
        Color(0xFF2A2A3E),
        Color(0xFF1E1E2E)
    )
)
```

---

## Typography

```kotlin
// Font: Inter (Google Fonts — free, clean, highly legible)
// Fallback: System default sans-serif

val RaddTypography = Typography(
    displayLarge  = TextStyle(fontSize = 32.sp, fontWeight = FontWeight.Bold,   letterSpacing = (-0.5).sp),
    displayMedium = TextStyle(fontSize = 26.sp, fontWeight = FontWeight.Bold),
    headlineLarge = TextStyle(fontSize = 22.sp, fontWeight = FontWeight.SemiBold),
    headlineMedium= TextStyle(fontSize = 18.sp, fontWeight = FontWeight.SemiBold),
    titleLarge    = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.Medium),
    titleMedium   = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Medium),
    bodyLarge     = TextStyle(fontSize = 16.sp, fontWeight = FontWeight.Normal, lineHeight = 24.sp),
    bodyMedium    = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Normal, lineHeight = 20.sp),
    bodySmall     = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Normal, color = Color(0xFF7070A0)),
    labelLarge    = TextStyle(fontSize = 14.sp, fontWeight = FontWeight.Medium, letterSpacing = 0.1.sp),
    labelMedium   = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.Medium, letterSpacing = 0.5.sp),
    labelSmall    = TextStyle(fontSize = 10.sp, fontWeight = FontWeight.Medium, letterSpacing = 0.5.sp)
)
```

---

## Spacing & Layout

| Token | Value | Usage |
|---|---|---|
| `spacing_xs` | `4.dp` | Icon padding, tight chips |
| `spacing_sm` | `8.dp` | Between card label and icon |
| `spacing_md` | `16.dp` | Screen horizontal padding (standard) |
| `spacing_lg` | `24.dp` | Section headers, between rows |
| `spacing_xl` | `32.dp` | Hero section top padding |
| `spacing_xxl` | `48.dp` | Onboarding screen padding |
| `card_radius` | `12.dp` | All poster/content cards |
| `button_radius` | `8.dp` | Action buttons |
| `chip_radius` | `20.dp` | Fully rounded filter chips |

---

## Component Specs

### Poster Card
```
Width:  120.dp (portrait grid), 160.dp (featured row)
Height: 180.dp (portrait 2:3 ratio), 240.dp (featured)
Corner radius: 12.dp
Shadow: elevation 4.dp with 20% black overlay
Overlay gradient: bottom 40% fades to black
Title: bodySmall, bottom-left, max 2 lines
Type badge: labelSmall, top-right, colored pill
```

### Play Button (Detail Screen)
```
Width: fill (minus 32dp horizontal padding)
Height: 52.dp
Corner radius: 8.dp
Background: accent_primary gradient
Icon: ▶ 20.sp, white
Text: "PLAY" labelLarge, white, bold
Elevation: 8.dp with purple glow shadow
```

### Bottom Navigation Bar
```
Height: 64.dp + system nav bar insets
Background: surface (#141420) with top border 1.dp (#1E1E2E)
Items: 4 (Home, Search, My List, Settings)
Active: accent_primary icon + label
Inactive: on_surface_muted icon, no label
```

### Filter Chips
```
Height: 32.dp
Corner: chip_radius (20.dp, fully rounded)
Active: accent_primary background, white text
Inactive: surface_variant background, on_surface text
Border: none (active), 1.dp #2E2E4E (inactive)
Horizontal padding: 16.dp
```

### Hero Banner Carousel
```
Height: 260.dp
Auto-scroll: every 5 seconds (pauses on user interaction)
Dot indicators: 6.dp circles, active white, inactive surface_variant
Transition: cross-fade 400ms
Content: full-width poster/backdrop, gradient overlay, title + type badge
```

---

## Motion & Animation

| Element | Animation | Duration |
|---|---|---|
| Screen transitions | Shared element + slide | 350ms |
| Card tap feedback | Scale to 0.96 on press | 100ms |
| Hero auto-scroll | CrossFade | 400ms |
| Shimmer loading | Horizontal sweep loop | 1200ms |
| Bottom sheet open | Slide up + fade | 300ms |
| Player controls hide | Fade out | 500ms |
| Toast messages | Slide up from bottom | 250ms |

---

## Icons

**Library**: Material Symbols (Rounded variant)  
All icons from `androidx.compose.material:material-icons-extended`

| Screen | Key Icons |
|---|---|
| Bottom nav | `Home`, `Search`, `FavoriteBorder` / `Favorite`, `Settings` |
| Player | `PlayArrow`, `Pause`, `Replay10`, `Forward10`, `Fullscreen`, `PictureInPictureAlt`, `Lock`, `Speed`, `Subtitles` |
| Detail | `PlayArrow`, `FavoriteBorder`, `Download`, `Share`, `OpenInNew` |
| Search | `Search`, `Clear`, `History` |
| Settings | `Wifi`, `VideoSettings`, `DeleteOutline`, `Info`, `ChevronRight` |

---

## Screen Dimensions & Safe Areas

- Handle notch / dynamic island: use `WindowInsets.systemBars`
- Player is always **edge-to-edge** (content behind status + nav bars)
- Home/Search/Detail: respect `WindowInsets.statusBars` at top
- Bottom nav: respect `WindowInsets.navigationBars` at bottom
- Minimum touch target: **48.dp × 48.dp** (Material accessibility spec)
