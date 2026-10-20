# ProGuard rules for RADD Stream

# Keep Retrofit service interfaces
-keep interface com.raddstream.app.network.** { *; }

# Keep data models (Gson serialization)
-keep class com.raddstream.app.network.models.** { *; }

# Hilt
-keep class * extends dagger.hilt.android.internal.managers.ApplicationComponentManager { *; }

# ExoPlayer / Media3
-keep class androidx.media3.** { *; }
-dontwarn androidx.media3.**

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**

# Retrofit
-keepattributes Signature
-keepattributes Exceptions
-keep class retrofit2.** { *; }
