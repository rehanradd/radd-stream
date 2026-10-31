package com.raddstream.app.data

import android.content.Context
import android.os.Build
import android.provider.Settings
import com.raddstream.app.sync.DeviceTrial

/**
 * The one place this app reads a hardware identifier, and the reason it is a separate file:
 * [DeviceTrial.deviceId] is a pure function of three strings so it can be tested on a JVM, and
 * reaching those three strings needs a `Context`. Keeping the Android half here means the rule
 * file imports no Android and this file contains no rule.
 *
 * WHAT THE ID IS: `SHA-256(namespace | ANDROID_ID | Build.HARDWARE | Build.FINGERPRINT)`, sent to
 * the server as `device_id` to open a free three-day trial. It is not a secret and not a
 * proof of anything:
 *  - `ANDROID_ID` is per user, per app, per signing key on API 26+, and it resets on an OS
 *    upgrade or a different app signature;
 *  - below API 26 it can be null on devices with no SIM, which is why this returns null instead
 *    of substituting something — the app then simply does not start a trial, and everything else
 *    works exactly as it did before this file existed;
 *  - `HARDWARE` and `FINGERPRINT` are identical across every phone of one model, so they add no
 *    entropy; they are included because the owner named them, and a rooted viewer can read and
 *    forge all three anyway (`docs/IDENTITY_AND_TRIAL_ABUSE.md` §3, and the server agrees —
 *    `accounts.py:240` calls the id "client-reported … spoofable on a rooted phone").
 *
 * So no copy in this app may call this a locked device, a verified device, or an identity, and
 * nothing here may log the value. It is a row key on a trial ledger, and it is derived from a
 * stable identifier that Android's own privacy guidance says is not for advertising.
 */
object DeviceIdentity {

    /**
     * The id to send, or null when this device cannot name itself honestly. Never cached: it is
     * three property reads and one hash, and a value that outlives the process is a value that can
     * outlive the account it was minted for.
     */
    fun trialDeviceId(context: Context): String? {
        val androidId = runCatching {
            Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID)
        }.getOrNull()
        return DeviceTrial.deviceId(
            androidId = androidId,
            hardware = Build.HARDWARE,
            fingerprint = Build.FINGERPRINT,
        )?.takeIf { DeviceTrial.isStorableDeviceId(it) }
    }
}
