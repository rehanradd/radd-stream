package com.raddstream.app.update

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.IntentSenderRequest
import com.google.android.play.core.appupdate.AppUpdateManager
import com.google.android.play.core.appupdate.AppUpdateManagerFactory
import com.google.android.play.core.appupdate.AppUpdateOptions
import com.google.android.play.core.install.InstallStateUpdatedListener
import com.google.android.play.core.install.model.AppUpdateType
import com.google.android.play.core.install.model.InstallStatus
import com.google.android.play.core.install.model.UpdateAvailability

/**
 * Play Core in-app updates, with the download page as the live fallback.
 *
 * The force-update card tries Play first — flexible for a soft update,
 * immediate for a forced one — and opens the operator's download page
 * whenever Play cannot do it: no Play on the device, a sideloaded build
 * Play knows nothing about, an update Play says is not available, or any
 * failure along the way. Every failure lands on the same fallback, so the
 * viewer always has a way forward and the dialog never dead-ends.
 *
 * That fallback is the live path today, not a theoretical one: this app is
 * sideloaded from the download page, and Play Core only knows builds
 * installed from Play — so on every current install Play answers "no
 * update available" and the card opens the download page, exactly as it
 * did before this helper existed. The Play attempt becomes real the day
 * there is a Play listing, with no further code change.
 *
 * Installing stays the platform's job throughout: this app never asks for
 * REQUEST_INSTALL_PACKAGES and never starts an install itself.
 */
object InAppUpdate {

    /**
     * The one path to a new build.
     *
     * @param onPlayFlowStarted called when Play took the update over. The
     * caller dismisses the dialog only for a flexible update: an immediate
     * flow owns the screen, and if the viewer cancels it the dialog must
     * still be there, because a required update has no "Later".
     * @param onDownloadOpened called when the download page opened, so the
     * caller can dismiss the dialog — the one-tap path did its job.
     */
    fun startUpdate(
        context: Context,
        launcher: ActivityResultLauncher<IntentSenderRequest>,
        required: Boolean,
        downloadUrl: String,
        onPlayFlowStarted: () -> Unit,
        onDownloadOpened: () -> Unit,
    ) {
        val updateType = if (required) AppUpdateType.IMMEDIATE else AppUpdateType.FLEXIBLE
        val manager = try {
            AppUpdateManagerFactory.create(context)
        } catch (_: Exception) {
            openDownload(context, downloadUrl, onDownloadOpened)
            return
        }
        manager.appUpdateInfo
            .addOnSuccessListener { info ->
                // An immediate update the viewer walked away from mid-flow
                // reports as in progress; restarting it is the same call
                // as starting it, so it is accepted here too.
                val available = info.updateAvailability() == UpdateAvailability.UPDATE_AVAILABLE ||
                    info.updateAvailability() == UpdateAvailability.DEVELOPER_TRIGGERED_UPDATE_IN_PROGRESS
                if (!available || !info.isUpdateTypeAllowed(updateType)) {
                    openDownload(context, downloadUrl, onDownloadOpened)
                    return@addOnSuccessListener
                }
                try {
                    if (!required) registerFlexibleListener(manager)
                    manager.startUpdateFlowForResult(
                        info,
                        launcher,
                        AppUpdateOptions.newBuilder(updateType).build(),
                    )
                    onPlayFlowStarted()
                } catch (_: Exception) {
                    openDownload(context, downloadUrl, onDownloadOpened)
                }
            }
            .addOnFailureListener {
                openDownload(context, downloadUrl, onDownloadOpened)
            }
    }

    /**
     * An immediate update the viewer walked away from mid-flow: Play
     * reports it as in progress, and the docs say to restart the flow when
     * the app comes back. Called when a required update notice appears, so
     * a viewer who backgrounded the update is not asked to tap again. The
     * dialog stays up either way — if Play cannot restart it, the viewer
     * can tap "Update now" again.
     */
    fun resumeImmediateUpdateIfNeeded(
        context: Context,
        launcher: ActivityResultLauncher<IntentSenderRequest>,
        onPlayFlowStarted: () -> Unit,
    ) {
        val manager = try {
            AppUpdateManagerFactory.create(context)
        } catch (_: Exception) {
            return
        }
        manager.appUpdateInfo.addOnSuccessListener { info ->
            if (info.updateAvailability() != UpdateAvailability.DEVELOPER_TRIGGERED_UPDATE_IN_PROGRESS) {
                return@addOnSuccessListener
            }
            if (!info.isUpdateTypeAllowed(AppUpdateType.IMMEDIATE)) return@addOnSuccessListener
            try {
                manager.startUpdateFlowForResult(
                    info,
                    launcher,
                    AppUpdateOptions.newBuilder(AppUpdateType.IMMEDIATE).build(),
                )
                onPlayFlowStarted()
            } catch (_: Exception) {
                // The dialog stays up: the viewer can tap "Update now" again.
            }
        }
    }

    /**
     * A flexible update downloads in the background while the viewer keeps
     * watching; Play will not install it until the app says so. The listener
     * is the "so": the moment the download lands, the install completes and
     * the app restarts into the new build. Unregistered in [onDestroy].
     */
    private var flexibleManager: AppUpdateManager? = null
    private var flexibleListener: InstallStateUpdatedListener? = null

    private fun registerFlexibleListener(manager: AppUpdateManager) {
        unregisterFlexibleListener()
        val listener = InstallStateUpdatedListener { state ->
            if (state.installStatus() == InstallStatus.DOWNLOADED) {
                try {
                    manager.completeUpdate()
                } catch (_: Exception) {
                    // The download is on the device; Play surfaces the
                    // install on its own next launch. Nothing to do here.
                }
            }
        }
        flexibleManager = manager
        flexibleListener = listener
        manager.registerListener(listener)
    }

    /** Call from the host activity's onDestroy: a leaked Play listener survives the activity. */
    fun onDestroy() {
        unregisterFlexibleListener()
    }

    private fun unregisterFlexibleListener() {
        val manager = flexibleManager
        val listener = flexibleListener
        flexibleManager = null
        flexibleListener = null
        if (manager != null && listener != null) {
            try {
                manager.unregisterListener(listener)
            } catch (_: Exception) {
                // Already gone; nothing to unregister.
            }
        }
    }

    /**
     * The fallback every Play failure lands on: the operator's download page
     * in the system browser. A malformed URL is the operator's to fix; the
     * dialog stays up so the viewer still sees that an update exists.
     */
    private fun openDownload(context: Context, url: String, onDownloadOpened: () -> Unit) {
        try {
            context.startActivity(
                Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            onDownloadOpened()
        } catch (_: ActivityNotFoundException) {
            Toast.makeText(context, "No browser is available to open this download.", Toast.LENGTH_LONG).show()
        } catch (_: Exception) {
            // Malformed URL: leave the dialog up.
        }
    }
}
