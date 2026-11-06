package com.raddstream.app.ui.navigation

import com.raddstream.app.data.UserRegion
import com.raddstream.app.network.models.PanelBroadcast

/**
 * Whether one broadcast is for this phone.
 *
 * The server sends every live, published broadcast and this is where the
 * audience is decided, because only the phone knows its own region, tier
 * and version. The rules are fail-closed throughout: an unknown target, a
 * region or version with no detail, and a tier the phone has not loaded
 * yet all hide the broadcast rather than show it to the wrong viewer.
 * A broadcast is decoration, never content — losing one to caution costs
 * a notice, showing one to the wrong audience costs the operator's word.
 *
 * The region map is the honest limit of what the phone knows: it knows
 * which region CARD the viewer picked, not which country they are in.
 * Pakistan and India pick the same Desi card, so a broadcast the operator
 * addressed to "pakistan" reaches Indian Desi viewers too. The panel says
 * so on its form, and this map is where that promise is kept.
 */
object BroadcastTargeting {

    private val REGION_TARGETS = mapOf(
        "pakistan" to UserRegion.DESI_DUBS,
        "india" to UserRegion.DESI_DUBS,
        "asia" to UserRegion.EAST_ASIAN,
        "international" to UserRegion.INTERNATIONAL,
    )

    fun visible(
        broadcast: PanelBroadcast,
        regionId: String,
        isVip: Boolean?,
        appVersion: String,
    ): Boolean {
        return when (broadcast.target.trim().lowercase()) {
            "all" -> true
            // `isVip == false` is not the same as `isVip != true`: a null
            // entitlement (not loaded yet) hides both tiered broadcasts.
            // A viewer whose tier is unknown is shown neither a free
            // offer nor a VIP notice until the app knows which they are.
            "free" -> isVip == false
            "vip" -> isVip == true
            "region" -> REGION_TARGETS[broadcast.targetDetail.trim().lowercase()] ==
                UserRegion.normalize(regionId)
            // Exact match only: the operator writes one version name, and
            // "1.0.4" must never match "1.0.40" or "1.0".
            "version" -> broadcast.targetDetail.trim().isNotEmpty() &&
                broadcast.targetDetail.trim() == appVersion.trim()
            else -> false
        }
    }
}
