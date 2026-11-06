package com.raddstream.app.player

/**
 * The first-run gesture coach (plan §5 step 7, research rule P37): gestures are muscle
 * memory once learned and invisible until then, so the player teaches them once — on
 * first open, and once again after a major version change — and never again.
 *
 * Pure policy, no clock, no DataStore, no player: the ViewModel feeds it the major
 * version the coach was last shown for (from `ServerSettingsRepository.coachSeenVersion`)
 * and the app's current version name, and the screen reads the answer. The stored value
 * is a major version ("1"), never the full version name, so a minor update (1.0.4 →
 * 1.1.0) does not re-teach gestures the viewer already knows.
 */
fun majorVersionOf(versionName: String): String =
    versionName.substringBefore('.').trim()

/**
 * True when the coach is owed: never shown ([seenVersion] is null), or last shown for
 * a different major version than the one running now. Same major → already taught.
 */
fun shouldShowCoach(seenVersion: String?, currentVersionName: String): Boolean =
    majorVersionOf(seenVersion ?: "") != majorVersionOf(currentVersionName)
