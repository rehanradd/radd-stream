package com.raddstream.app.network.models

import com.google.gson.annotations.SerializedName

/**
 * GET /api/v1/app/remote-config — the one public body that carries the payment handles
 * the operator wants printed beside a Copy button.
 *
 * Everything here is display text, not a credential: the shortener API tokens the same
 * row holds are masked at the edge, so this projection has no richer second version to
 * leak (see `Fast_Fetch/admin_panel.py:remote_config`). A handle the operator has not
 * filled in comes back as an empty string, and the screen says so instead of inventing
 * an account a viewer could pay by mistake.
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
)

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
