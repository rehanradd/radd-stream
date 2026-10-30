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
    /** Coin-wallet payout rules. Parsed, not displayed: no screen shows a balance yet. */
    val wallet: VipRemoteWallet = VipRemoteWallet(),
    /** The login-streak length and reward. Parsed, not displayed: no screen shows a streak yet. */
    val streak: VipRemoteStreak = VipRemoteStreak(),
    /**
     * The server's own ad cadence, which outranks [ads] for the three caps because it is the
     * number the enforcement side reads. Absent from every deployment today, and an absent block
     * changes nothing: see [VipRemoteAdCadence].
     */
    val engagement: VipRemoteEngagement = VipRemoteEngagement(),
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

/**
 * Ad-network ids and the owner's three cadence caps.
 *
 * **The cadence numbers are the whole product decision, so their absence is load-bearing.** A
 * body that carries none of them must not read as "ads with no limits": `enabled` defaults FALSE,
 * and every interval defaults to zero, which [com.raddstream.app.player.AdCadenceLimits] answers
 * with the shipped cap rather than with unlimited. An older deployment therefore gets no ads at
 * all, and a deployment that switches ads on without ever publishing a cadence gets exactly
 * 1-per-25-minutes, 1-per-12-posters and 1-per-4-hours. This file deliberately holds no cap of
 * its own: the numbers have one owner, in the policy that enforces them, so the wire and the
 * enforcement cannot drift apart.
 *
 * The alternate spellings exist because the server fields are still landing on another lane's
 * branch (`q5-monet-fields-20261029`); accepting more than one spelling per key is how this body
 * has always absorbed a renamed server field, and an unknown key costs nothing — Gson skips it and
 * the default stands.
 */
data class VipRemoteAds(
    @SerializedName("monetag_rewarded_zone_id")
    val monetagRewardedZoneId: String = "",
    @SerializedName("adsterra_native_banner_id")
    val adsterraNativeBannerId: String = "",
    /**
     * The operator's switch for the three capped surfaces. FALSE when absent, like
     * `quality_gate` above and for the same reason: an ad is not a feature the viewer already
     * had, so a deployment that never set it must keep showing them nothing.
     */
    @SerializedName(value = "ads_enabled", alternate = ["feature_ads", "enable_ads"])
    val enabled: Boolean = false,
    @SerializedName(value = "preroll_interval_minutes", alternate = ["pre_roll_interval_minutes", "preroll_minutes"])
    val prerollIntervalMinutes: Int = 0,
    @SerializedName(value = "feed_card_posters", alternate = ["native_card_every_posters", "feed_interval_posters"])
    val feedCardEveryPosters: Int = 0,
    @SerializedName(value = "app_open_interval_hours", alternate = ["app_open_hours", "open_interval_hours"])
    val appOpenIntervalHours: Int = 0,
    /**
     * How long a creative must watch for before it answers to a skip control. The policy caps the
     * answer at 5 s whatever the server says, so a misconfigured deployment cannot buy a
     * non-skippable ad with a body edit; a non-positive value falls back to the shipped cap.
     */
    @SerializedName(value = "ad_skip_after_seconds", alternate = ["skippable_after_seconds", "ads_skip_seconds"])
    val skippableAfterSeconds: Int = 0,
) {
    /** True when the rewarded slot has a zone to request; an empty id means "no inventory". */
    val hasRewardedInventory: Boolean
        get() = monetagRewardedZoneId.isNotBlank()

    /**
     * The ids a native surface would need before it could fill anything. Two blank ids mean the
     * operator turned the switch on without configuring a network, and the rule for an ad that
     * cannot be filled is that nothing is shown.
     */
    val hasNativeInventory: Boolean
        get() = adsterraNativeBannerId.isNotBlank()
}

/**
 * The coin wallet the owner's plan pays rewarded views and a kept streak into. Parsed here and
 * displayed nowhere yet: no screen in this build renders a balance, and a number the app cannot
 * explain is a number it must not invent. Every default is the inert one — zero coins, switch off
 * — so an absent `wallet` object cannot make this client promise a payout.
 */
data class VipRemoteWallet(
    @SerializedName(value = "wallet_enabled", alternate = ["feature_wallet", "coins_enabled"])
    val enabled: Boolean = false,
    @SerializedName(value = "coin_reward_preroll", alternate = ["coins_per_preroll", "reward_preroll_coins"])
    val coinsPerPreRoll: Int = 0,
    @SerializedName(value = "coin_reward_streak", alternate = ["coins_per_streak", "reward_streak_coins"])
    val coinsPerStreak: Int = 0,
    /** What one device may earn in a day. Zero means the operator set no ceiling, not no wallet. */
    @SerializedName(value = "coin_daily_cap", alternate = ["coins_daily_limit", "daily_coin_cap"])
    val dailyCoinCap: Int = 0,
) {
    /** True when there is at least one way to earn, so a balance screen has something to show. */
    val hasAnyEarningRule: Boolean
        get() = enabled && (coinsPerPreRoll > 0 || coinsPerStreak > 0)
}

/**
 * The login streak the owner's plan rewards after a week. `days` is the one field whose default is
 * a real number rather than zero, because the pillar itself is "7 consecutive days" and a partial
 * body that omits the length must not silently shorten or lengthen a promise the operator made.
 */
data class VipRemoteStreak(
    @SerializedName(value = "streak_enabled", alternate = ["feature_streak", "login_streak_enabled"])
    val enabled: Boolean = false,
    @SerializedName(value = "streak_days", alternate = ["streak_length_days", "streak_target_days"])
    val days: Int = DEFAULT_DAYS,
    @SerializedName(value = "streak_reward_coins", alternate = ["streak_bonus_coins"])
    val rewardCoins: Int = 0,
) {
    companion object {
        /** The owner's pillar: seven days in a row. */
        const val DEFAULT_DAYS = 7
    }

    /** A length the server never filled in is not a streak; a zero-day "streak" rewards nothing. */
    val isConfigured: Boolean
        get() = enabled && days > 0
}

/**
 * The engagement pillar's read projection — `Fast_Fetch/engagement.py:remote_view()`, published
 * under `/api/v1/app/remote-config` as `engagement`.
 *
 * Only `cadence` is decoded, and only because it is the one part of that body that changes what a
 * viewer sees: the caps on how often an ad may fire. The `wallet`, `streak` and `passes` shapes in
 * the same server object are not decoded *here* — this file's [wallet] and [streak] are the older
 * top-level keys, and a field decoded and then dropped is exactly the `maintenanceMode` mistake
 * this file's own watcher log records. When a screen draws a balance or a streak, it decodes what
 * it draws, from the body it is actually pointed at.
 */
data class VipRemoteEngagement(
    val cadence: VipRemoteAdCadence = VipRemoteAdCadence(),
)

/**
 * The server's own ad caps, in the server's own units.
 *
 * [appOpenGapMinutes] is MINUTES (`240`), while [VipRemoteAds.appOpenIntervalHours] is HOURS (`4`).
 * The two keys are therefore never alternates of each other — accepting `240` where `4` was meant
 * would be a ten-day app-open window bought with a rename — and
 * [com.raddstream.app.player.AdCadenceLimits] converts at one place, in the direction the names state.
 *
 * Every field defaults to zero, which means "this server said nothing" and lands on the shipped
 * cap, the same rule the `ads` block already follows. That makes the block safe to read before it
 * exists: no route serves `engagement` today, and every deployment still gets
 * 1-per-25-minutes, 1-per-12-posters and 1-per-4-hours, because the caps have one owner in the
 * policy and this file holds none of its own.
 */
data class VipRemoteAdCadence(
    @SerializedName(value = "ad_preroll_min_gap_minutes", alternate = ["preroll_min_gap_minutes"])
    val prerollGapMinutes: Int = 0,
    @SerializedName(value = "ad_native_card_every_posters", alternate = ["native_card_every_posters"])
    val feedCardEveryPosters: Int = 0,
    @SerializedName(value = "ad_app_open_min_gap_minutes", alternate = ["app_open_min_gap_minutes"])
    val appOpenGapMinutes: Int = 0,
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
