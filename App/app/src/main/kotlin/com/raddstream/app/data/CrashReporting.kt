package com.raddstream.app.data

import android.content.Context
import com.google.firebase.FirebaseApp
import com.google.firebase.crashlytics.FirebaseCrashlytics

/**
 * Firebase Crashlytics, installed exactly once at launch.
 *
 * Why this is a separate object and not inline in
 * [com.raddstream.app.RaddStreamApplication.onCreate]: the ordering against
 * [Telemetry.installCrashHandler] is the whole point, and it needs to be
 * readable in one place.
 *
 * Ordering — Crashlytics FIRST, Telemetry second:
 * - `FirebaseApp` auto-initialises from `google-services.json` through
 *   `FirebaseInitProvider` before `Application.onCreate` (the manifest's
 *   `androidx.startup` removal does not touch it — that provider is a
 *   ContentProvider, not an App Startup initializer). Calling
 *   `FirebaseCrashlytics.getInstance()` here forces Crashlytics to install
 *   its uncaught-exception handler immediately, instead of on first use.
 * - [Telemetry.installCrashHandler] then captures Crashlytics' handler as
 *   its `previous` and chains to it, so a crash is counted in the local
 *   aggregates AND reported to Crashlytics: Telemetry records the counter,
 *   then delegates to Crashlytics, which records the report and kills the
 *   process. Neither handler is lost, and the existing telemetry behaviour
 *   (synchronous counter commit, then the previous handler) is unchanged.
 * - Both handlers chain to their predecessor, so even if a future SDK
 *   version installs Crashlytics' handler lazily, the chain still holds —
 *   the order here is the deliberate one, not the only working one.
 *
 * Failure is never fatal: Crashlytics is observability, not a launch
 * dependency. If Firebase cannot initialise (no config, no network at
 * first run, a broken install), the app still starts and Telemetry's
 * handler still installs — a crash is then counted locally and reported
 * nowhere, instead of the app dying at launch with no report at all.
 * `runCatching` is the whole guard; nothing here throws.
 */
object CrashReporting {

    /**
     * Install Crashlytics' crash handler. Safe to call twice: Firebase
     * initialisation is a no-op when an app already exists, and
     * `getInstance()` returns the same instance.
     */
    fun install(context: Context) {
        runCatching {
            if (FirebaseApp.getApps(context).isEmpty()) {
                FirebaseApp.initializeApp(context)
            }
            // Force instantiation now: this is what installs Crashlytics'
            // uncaught-exception handler before Telemetry wraps it.
            FirebaseCrashlytics.getInstance()
        }
    }
}
