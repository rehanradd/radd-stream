# moved verbatim out of `App/AGENTS.md` by the 2026-10-30 documentation diet; text unchanged.

## 9. Phase 0 Implementation Notes (Historical)

Phase 0 created the Gradle project skeleton and the GitHub Actions build. The following steps are retained as historical implementation notes.

### Step-by-step:

**Step 1 — Create `settings.gradle.kts`**
```kotlin
pluginManagement {
    repositories {
        google(); mavenCentral(); gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories { google(); mavenCentral() }
}
rootProject.name = "radd-stream-app"
include(":app")
```

**Step 2 — Create root `build.gradle.kts`**
```kotlin
plugins {
    alias(libs.plugins.android.application) apply false
    alias(libs.plugins.kotlin.android) apply false
    alias(libs.plugins.hilt) apply false
    alias(libs.plugins.kotlin.kapt) apply false
}
```

**Step 3 — Create `gradle/libs.versions.toml`** (version catalog)
Define all library versions in one place — see TECH_STACK.md for the full list.

**Step 4 — Create `app/build.gradle.kts`**
- `applicationId = "com.raddstream.app"`
- `minSdk = 21`, `targetSdk = 35`, `compileSdk = 35`
- Configure signing config from env vars (`KEY_STORE_PASSWORD` etc.)
- Add all dependencies from TECH_STACK.md

**Step 5 — Create `gradle-wrapper.properties`**
```properties
distributionUrl=https\://services.gradle.org/distributions/gradle-8.7-bin.zip
```

**Step 6 — Create `gradlew` + `gradlew.bat`**
Download from any fresh Android project or https://github.com/gradle/gradle-wrapper

**Step 7 — Create `AndroidManifest.xml`**
```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
```

**Step 8 — Create minimal `MainActivity.kt`**
```kotlin
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { RaddStreamApp() }
    }
}
```

**Step 9 — Create `RaddStreamApplication.kt`**
```kotlin
@HiltAndroidApp
class RaddStreamApplication : Application()
```

**Step 10 — Push → watch GitHub Actions → verify green ✓ + APK artifact**

---

