# 🛠️ Tech Stack Decision

## Language: **Kotlin**

| Factor | Why Kotlin wins |
|---|---|
| **Performance** | Compiles to JVM bytecode + Kotlin/Native options; near-C++ speed for UI |
| **Modern Android APIs** | First-class support for Jetpack, Coroutines, Flow, Compose |
| **Coroutines** | Lightweight async / concurrency — perfect for streaming API calls |
| **Type safety** | Null-safety built into the type system — fewer crashes |
| **Interop** | 100% Java interop — use any Android library ever written |
| **Google support** | Google's official Android language since 2019 |
| **Community** | Largest Android community, most Stack Overflow answers |

> ❌ **Rejected: Flutter** — Dart runtime overhead, less access to Android-native media APIs  
> ❌ **Rejected: React Native** — JS bridge bottleneck, poor ExoPlayer integration  
> ❌ **Rejected: Java** — Verbose, no coroutines, being phased out for Android  

---

## UI Framework: **Jetpack Compose**

- Declarative UI (like SwiftUI / React) — build screens as functions, not XML
- Native Material 3 components
- Built-in animation APIs
- Hot-reload in Android Studio
- Used by Google, Netflix, Twitter, Airbnb on Android

---

## Media Playback: **ExoPlayer / Media3**

- Google's official media player library for Android
- Supports HLS (`.m3u8`), DASH, MP4, MKV, and direct HTTP streams
- Hardware-accelerated decoding
- Background playback (foreground Service + MediaSession)
- Picture-in-Picture (PiP) mode
- Subtitle / CC track support
- Playback speed control (0.5×–2×)

---

## Networking: **Retrofit 2 + OkHttp 3**

- Type-safe HTTP client for the `radd-stream` REST API
- Gson / Moshi for JSON deserialization
- OkHttp interceptor for server URL configuration. There is **no auth token
  injection to configure for the catalog routes** — `viewer.py` accepts no API key
  or session on `/api/v1/posts`, and `CORS_ALLOW_ORIGINS` is an **empty** allow-list,
  so responses carry no `Access-Control-Allow-Origin` header at all (the old
  `Access-Control-Allow-Origin: *` note described code that has since been replaced by
  `cors_headers_for()`). The deployed Oracle host is plain HTTP with no TLS, so
  whatever credential does exist — `RADD_ADMIN_TOKEN`, or an account sync key — must
  never be sent over it. ⚠️ Reality (verified against `viewer.py`/`redact.py`
  2026-10-30): add real auth to the backend before writing any token-handling
  interceptor.
- Automatic retry on network errors

---

## Architecture Pattern: **MVVM + Repository + Clean Architecture**

```
UI Layer (Compose Screens)
    ↕ StateFlow / LiveData
ViewModel Layer (business logic, state management)
    ↕ suspend functions
Repository Layer (data source abstraction)
    ↕ Retrofit interfaces
Remote Data Source (radd-stream REST API)
```

---

## Dependency Injection: **Hilt (Dagger)**

- Google's recommended DI for Android
- Automatic ViewModel injection
- Scoped singletons for Retrofit, database, player

---

## Local Storage: **Room Database**

- Local SQLite cache of catalog items (offline browsing)
- Watchlist / Favorites stored locally
- Continue-Watching history (episode + timestamp)

---

## Image Loading: **Coil**

- Kotlin-native image loader (vs Glide/Picasso which are Java)
- Coroutine-aware, Compose-native
- Automatic disk + memory caching for poster images

---

## Navigation: **Jetpack Navigation Component (Compose)**

- Type-safe screen navigation
- Deep-link support (e.g. `radd://stream/12345`)
- Back-stack management

---

## Full Dependency List

```kotlin
// build.gradle.kts (app)

// Jetpack Compose BOM
implementation(platform("androidx.compose:compose-bom:2024.05.00"))
implementation("androidx.compose.ui:ui")
implementation("androidx.compose.material3:material3")
implementation("androidx.compose.ui:ui-tooling-preview")
implementation("androidx.activity:activity-compose:1.9.0")

// Navigation
implementation("androidx.navigation:navigation-compose:2.7.7")

// Media3 / ExoPlayer
implementation("androidx.media3:media3-exoplayer:1.3.1")
implementation("androidx.media3:media3-exoplayer-hls:1.3.1")
implementation("androidx.media3:media3-exoplayer-dash:1.3.1")
implementation("androidx.media3:media3-ui:1.3.1")
implementation("androidx.media3:media3-session:1.3.1")

// Networking
implementation("com.squareup.retrofit2:retrofit:2.11.0")
implementation("com.squareup.retrofit2:converter-gson:2.11.0")
implementation("com.squareup.okhttp3:okhttp:4.12.0")
implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

// DI
implementation("com.google.dagger:hilt-android:2.51.1")
kapt("com.google.dagger:hilt-android-compiler:2.51.1")
implementation("androidx.hilt:hilt-navigation-compose:1.2.0")

// Room
implementation("androidx.room:room-runtime:2.6.1")
implementation("androidx.room:room-ktx:2.6.1")
kapt("androidx.room:room-compiler:2.6.1")

// Image loading
implementation("io.coil-kt:coil-compose:2.6.0")

// ViewModel + Coroutines
implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.0")
implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

// DataStore (settings / server config)
implementation("androidx.datastore:datastore-preferences:1.1.1")
```

---

## Minimum SDK

| Target | Value |
|---|---|
| `minSdk` | **21** (Android 5.0 — covers 99%+ of active Android devices) |
| `targetSdk` | **35** (Android 15) |
| `compileSdk` | **35** |

---

## Build System

- **Gradle** with **Kotlin DSL** (`build.gradle.kts`)
- **Android Studio Ladybug** (2024.2.1) or later
- **JDK 17**
