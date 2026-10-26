package com.raddstream.app.data.cache

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Maps the device's live connectivity onto the one coarse signal the scheduler cares about —
 * [NetworkClass] — and nothing else. The cache engine uses this only to decide whether opportunistic
 * auto-preview downloads may run (they never run on metered roaming and are opt-in on mobile);
 * a user-requested keep is driven on any connected network. There is no site, hoster, or address
 * involved: this is purely "can we move bytes, and should we do it unprompted".
 *
 * Every read is guarded: if the platform refuses a query (a locked-down API level, a transient
 * connectivity service failure) we answer [NetworkClass.MOBILE] rather than [NetworkClass.NONE],
 * so a keep still proceeds while opportunistic preview stays conservative.
 */
@Singleton
class ConnectivityProbe @Inject constructor(
    @ApplicationContext private val context: Context,
) {

    fun current(): NetworkClass = runCatching {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return NetworkClass.MOBILE
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val network = cm.activeNetwork ?: return NetworkClass.NONE
            val caps = cm.getNetworkCapabilities(network) ?: return NetworkClass.NONE
            when {
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> NetworkClass.WIFI
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> NetworkClass.WIFI
                caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> NetworkClass.MOBILE
                else -> NetworkClass.MOBILE
            }
        } else {
            @Suppress("DEPRECATION")
            when (val info = cm.activeNetworkInfo) {
                null -> NetworkClass.NONE
                else -> if (info.type == ConnectivityManager.TYPE_WIFI) NetworkClass.WIFI else NetworkClass.MOBILE
            }
        }
    }.getOrDefault(NetworkClass.MOBILE)

    /**
     * Is the active connection METERED — the one signal the poster loader needs before it spends a
     * viewer's mobile data? This is distinct from [current]'s transport class: it reads the OS's own
     * metered verdict, so a phone on a metered Wi-Fi hotspot is caught and a tablet on unlimited fibre
     * is not. It uses the same guarded, permission-free (ACCESS_NETWORK_STATE is already declared) read
     * as [current] and lives here so this stays the app's single owner of connectivity queries.
     *
     * It fails OPEN: if the platform refuses the query we answer `false` (not metered), because for
     * images the safe-on-failure behaviour is to let art load exactly as it does today rather than to
     * blank a grid over a connectivity service we could not reach. What is NOT protected: a network
     * that flips to metered after a poster has already loaded leaves that image on screen — this is a
     * per-request gate, not a live subscription, so only the next request obeys the change.
     */
    fun isMetered(): Boolean = runCatching {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val network = cm.activeNetwork ?: return false
            val caps = cm.getNetworkCapabilities(network) ?: return false
            !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
        } else {
            @Suppress("DEPRECATION")
            when (val info = cm.activeNetworkInfo) {
                null -> false
                else -> info.isRoaming || info.type == ConnectivityManager.TYPE_MOBILE
            }
        }
    }.getOrDefault(false)
}
