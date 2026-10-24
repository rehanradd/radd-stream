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
}
