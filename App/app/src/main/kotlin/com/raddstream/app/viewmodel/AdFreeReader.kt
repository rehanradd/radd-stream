package com.raddstream.app.viewmodel

import com.raddstream.app.data.ServerSettingsRepository
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.flow.first

/**
 * The one-shot answer to "may this viewer be shown an ad at all", for surfaces that are not already
 * collecting entitlement as live UI state.
 *
 * [RewardedVipPass.isAdFree] owns the rule and this only reads the two stored facts into it, so the
 * paid card's sentence and the rewarded card's four hours stay one promise rather than two. The
 * player and the detail page do not use this: they already observe the same facts as flows because
 * their UI has to change while it is open. A feed card and an app-open slot are fire-once asks with
 * no affordance to update, so a read at the moment of the ask is the honest shape — an approval that
 * lands mid-scroll takes effect on the next ask rather than being promised a recomposition it will
 * never receive.
 *
 * Both reads fail closed. A store that cannot answer is not permission to show a sponsor to a
 * viewer who may have paid.
 */
@Singleton
class AdFreeReader @Inject constructor(
    private val settings: ServerSettingsRepository,
) {

    suspend fun isAdFree(nowMs: Long = System.currentTimeMillis()): Boolean {
        val rewardedExpiresAt = try {
            settings.rewardedVipExpiresAt.first()
        } catch (_: Exception) {
            0L
        }
        val serverVip = try {
            settings.storedEntitlement.first()?.vip == true
        } catch (_: Exception) {
            false
        }
        return RewardedVipPass.isAdFree(serverVip, rewardedExpiresAt, nowMs)
    }
}
