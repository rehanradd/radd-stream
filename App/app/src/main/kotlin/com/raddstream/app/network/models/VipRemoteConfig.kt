package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/**
 * GET /api/v1/app/remote-config — the one public body that carries the payment handles
 * the operator wants printed beside a Copy button.
 *
 * Everything here is display text, not a credential: the one row the admin panel publishes
 * has its secrets masked at the edge, so this projection has no richer second version to
 * leak (see `Fast_Fetch/admin_panel.py:remote_config`). A handle the operator has not
 * filled in comes back as an empty string, and the screen says so instead of inventing
 * an account a viewer could pay by mistake.
 *
 * **Link shorteners are retired — this app does not model them.** The client used to decode a
 * `link_shorteners` array off this body and asked nothing of it, and the owner has since
 * retired shortening from the project outright, so every byte path here is direct
 * (`ApiProvider.streamRedirectUrl` → `/api/v1/stream?id=<handle>`). A deployment whose remote
 * config still carries `link_shorteners` is not an error and needs no client code: Gson
 * ignores the key, and `VipRemoteConfigTest` pins that the rest of the body still decodes.
 */
data class VipRemoteConfig(
    val success: Boolean = false,
    val currency: String = "PKR",
    @SerializedName("updated_at")
    val updatedAt: Long = 0L,
    /** Operator switch: the phone shows a maintenance notice instead of the catalog. */
    @SerializedName("maintenance_mode")
    val maintenanceMode: Boolean = false,
    /**
     * The build the operator currently publishes, or "" when they have not published one.
     * The body carries no version code, so a non-empty URL *is* the update signal; the
     * screen still validates it as http(s) before offering the button.
     */
    @SerializedName("apk_update_url")
    val apkUpdateUrl: String = "",
    val vip: VipRemotePricing = VipRemotePricing(),
    val payments: VipRemotePayments = VipRemotePayments(),
    /** Operator switches for whole surfaces; every one defaults ON when the body omits it. */
    @SerializedName("feature_flags")
    val featureFlags: VipRemoteFeatureFlags = VipRemoteFeatureFlags(),
    /** Ad-network ids, displayed nowhere: they only decide whether a slot has real inventory. */
    val ads: VipRemoteAds = VipRemoteAds(),
)

/**
 * The real server keys are `downloads`, `pure_cinema` and `chromecast`
 * (`Fast_Fetch/admin_panel.py:remote_config`). The brief's `*_enabled` spelling is accepted as
 * an alternate so a future/renamed body still decodes instead of silently turning a switch off.
 *
 * Every flag defaults to `true`: the server ships them enabled, and a partial body must not
 * remove a surface the app has always had. Only an explicit `false` turns anything off.
 */
data class VipRemoteFeatureFlags(
    @SerializedName(value = "downloads", alternate = ["downloads_enabled"])
    val downloads: Boolean = true,
    @SerializedName("pure_cinema")
    val pureCinema: Boolean = true,
    @SerializedName("chromecast")
    val chromecast: Boolean = true,
    @SerializedName(value = "sharing", alternate = ["sharing_enabled"])
    val sharing: Boolean = true,
    @SerializedName(value = "search", alternate = ["search_enabled"])
    val search: Boolean = true,
    /**
     * The operator's choice to charge VIP for the top rungs. Defaults FALSE, the opposite of
     * the four flags above, because this one is not a feature the viewer already had: on, it
     * hides 1080p and 4K from everyone the ledger has not confirmed. A deployment that never
     * sets it must stay fully watchable, so an absent key means "do not restrict".
     */
    @SerializedName(value = "quality_gate", alternate = ["quality_gating_enabled"])
    val qualityGate: Boolean = false,
)

data class VipRemoteAds(
    @SerializedName("monetag_rewarded_zone_id")
    val monetagRewardedZoneId: String = "",
    @SerializedName("adsterra_native_banner_id")
    val adsterraNativeBannerId: String = "",
) {
    /** True when the rewarded slot has a zone to request; an empty id means "no inventory". */
    val hasRewardedInventory: Boolean
        get() = monetagRewardedZoneId.isNotBlank()
}

data class VipRemotePricing(
    @SerializedName("monthly_pkr")
    val monthlyPkr: Int = 0,
    @SerializedName("yearly_pkr")
    val yearlyPkr: Int = 0,
)

data class VipRemotePayments(
    val jazzcash: VipRemoteJazzCash = VipRemoteJazzCash(),
    val easypaisa: VipRemoteEasyPaisa = VipRemoteEasyPaisa(),
    val raast: VipRemoteRaast = VipRemoteRaast(),
) {
    /** True when at least one destination exists, so a submission has something to point at. */
    val hasAnyHandle: Boolean
        get() = jazzcash.tillId.isNotBlank() || jazzcash.mobileAccount.isNotBlank() ||
            easypaisa.mobileNumber.isNotBlank() || raast.instantId.isNotBlank()
}

data class VipRemoteJazzCash(
    @SerializedName("till_id")
    val tillId: String = "",
    @SerializedName("mobile_account")
    val mobileAccount: String = "",
)

data class VipRemoteEasyPaisa(
    @SerializedName("mobile_number")
    val mobileNumber: String = "",
)

data class VipRemoteRaast(
    @SerializedName("instant_id")
    val instantId: String = "",
)
