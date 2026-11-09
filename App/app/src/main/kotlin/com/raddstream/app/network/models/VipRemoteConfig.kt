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
    /**
     * True when the server could not read its own settings row and answered
     * with shipped defaults instead: the shape is guaranteed, the values are
     * not the operator's decision. The app must keep its last cached config
     * and act on nothing in this body — treating unknown as `false` is how a
     * remote control fails open (see `admin_panel.remote_config`).
     */
    @SerializedName("settings_unavailable")
    val settingsUnavailable: Boolean = false,
    /**
     * The best picture a free viewer may play, as the operator set it in the
     * panel ("480p" or "720p"; "720p" when unset). The quality gate reads it;
     * any other value decodes but is treated as "720p" by the gate.
     */
    @SerializedName("free_quality_cap")
    val freeQualityCap: String = "720p",
    /**
     * The version code of the APK the operator published, or 0 when they
     * published no code. The update notice compares it against this build;
     * a body with no code falls back to "a link means an update".
     */
    @SerializedName("apk_update_version_code")
    val apkUpdateVersionCode: Int = 0,
    /**
     * The published APK's size in bytes, or 0 when the operator published
     * none. The update dialog shows it ("Download size: 24 MB") so a viewer
     * on mobile data knows what the tap costs; a truncated fetch is not the
     * app's to detect, because the browser downloads the file, not this app.
     *
     * The server also publishes `apk_update_sha256`, which this model
     * deliberately does NOT decode: the app never holds the APK bytes, so a
     * digest it cannot check is a promise it cannot keep, and displaying a
     * hash the viewer cannot use would be machine code on screen. The
     * backend's UPD-1b rule ("no digest, no banner") is therefore NOT
     * enforced here — enforcing it would silently kill the force-update
     * card the owner ordered whenever the operator has not set a digest.
     * If the app ever downloads the APK itself, decode the digest then and
     * verify the bytes before offering the install.
     */
    @SerializedName("apk_update_size_bytes")
    val apkUpdateSizeBytes: Long = 0,
    /**
     * The lowest app version code the operator still supports, or 0 for "no
     * minimum". A build below it is told the update is required, not optional.
     */
    @SerializedName("min_version_code")
    val minVersionCode: Int = 0,
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
    /**
     * The operator's home feed, published by the admin panel and served on this
     * same body so no second call is needed: the sections the panel built, the
     * broadcasts it published, and the works it hid. All three default to empty,
     * which is the honest answer from a deployment with no panel wired — the app
     * then keeps its own rails, shows no banner, and hides nothing. A section
     * item is a full [Post], projected by the server exactly like a posts row,
     * so the rail needs no second fetch to render.
     */
    val sections: List<PanelSection> = emptyList(),
    val broadcasts: List<PanelBroadcast> = emptyList(),
    @SerializedName("hidden_work_ids")
    val hiddenWorkIds: List<Int> = emptyList(),
    /**
     * The operator's theme knobs, published by the admin panel and served on
     * this same body: dark/light/system, an accent colour, dynamic colour,
     * and the hero's autoplay behaviour. Absent from an older deployment, it
     * decodes to [PanelTheme]'s defaults — dark, brand accent, hero on —
     * which is the app this build has always shipped.
     */
    val theme: PanelTheme = PanelTheme(),
    /**
     * The operator's bottom-bar tabs, in order, as set in the panel's `tabs`
     * tuning key. Empty from an older deployment — the app then keeps its own
     * four, exactly like the sections above. The list is authoritative when
     * present (a tab the operator did not list does not show), except Home,
     * which [com.raddstream.app.ui.navigation.PanelTabs.resolve] pins first:
     * the app cannot function without a way back to it.
     */
    val tabs: List<String> = emptyList(),
    /**
     * The operator's disclaimer, published by the admin panel and served on
     * this same body. Empty text from an older deployment — or from a panel
     * where the operator has written nothing yet — no longer means "no
     * disclaimer published": [PanelDisclaimer.effective] falls back to the
     * shipped default text, so the app always has one to show. `version` is
     * what the app remembers having shown, so a new version is shown once more.
     */
    val disclaimer: PanelDisclaimer = PanelDisclaimer(),
)

/**
 * The default disclaimer text, written under the owner's order (Session 122).
 * Verbatim — do not rewrite or shorten it. The admin panel's text overrides
 * it when set; when the panel field is empty, the app shows this. It is the
 * legal shield in plain words: the app owns, hosts, uploads and stores
 * nothing, only opens links that are already public, and names the takedown
 * address and the 48-hour hide-while-checking promise.
 */
val DEFAULT_DISCLAIMER_TEXT = """
    Radd Stream is a media browser and video player. It does not own, host, upload, or store any movie, show, video, or song.

    The app only finds and opens links that are already public on the internet, the same way a web browser opens a web page. All titles, posters, and videos belong to their owners and the sites that publish them.

    If you own content that appears here and want it removed, email radddao1@gmail.com. We will hide it within 48 hours while we check your claim, and remove it permanently if the claim is right. False claims will be refused and the content restored.

    Some content is made for adults only. It is kept behind an adult lock and is never shown on public lists.

    Links on the internet can change or stop working at any time. We do not promise that any link will play, and we are not responsible for what other websites show.

    By using Radd Stream you agree to this. If you do not agree, please do not use the app.
""".trimIndent()

/** The version the default disclaimer counts as: accepting it records this. */
const val DEFAULT_DISCLAIMER_VERSION = 1

/** The takedown contact shown with the default disclaimer. */
const val DEFAULT_DISCLAIMER_EMAIL = "radddao1@gmail.com"

/**
 * The operator's disclaimer: the text, the version the app compares
 * against what it has already shown, and the takedown contact email the
 * panel publishes under the text. An empty email means "no contact
 * published" — the dialog shows no contact line at all, never an
 * invented address.
 */
data class PanelDisclaimer(
    val text: String = "",
    val version: Int = 0,
    val email: String = "",
) {
    /**
     * The disclaimer the viewer actually sees: the panel's own text when
     * the operator wrote one, else the shipped default. The stored value
     * stays the panel value; this resolves at read time, so a panel edit
     * takes effect without a re-install and a cleared panel field falls
     * back to the default instead of leaving the app with no disclaimer
     * at all. The text is therefore never blank: a caller that checks
     * `text.isBlank()` to decide whether to show anything is checking a
     * condition that can no longer happen.
     */
    fun effective(): PanelDisclaimer =
        if (text.isNotBlank()) {
            this
        } else {
            PanelDisclaimer(
                text = DEFAULT_DISCLAIMER_TEXT,
                version = DEFAULT_DISCLAIMER_VERSION,
                email = email.ifBlank { DEFAULT_DISCLAIMER_EMAIL },
            )
        }
}

/**
 * The operator's theme, as the panel stores it in `tuning_settings`.
 * `mode` is "dark", "light" or "system" (anything else decodes but is
 * treated as dark by the resolver); `accent` is "" (brand default) or a
 * #RRGGBB hex; `heroMax` is how many slides the hero shows, 0 hides it.
 */
data class PanelTheme(
    val mode: String = "dark",
    val accent: String = "",
    @SerializedName("dynamic_color")
    val dynamicColor: Boolean = false,
    @SerializedName("hero_autoplay")
    val heroAutoplay: Boolean = true,
    @SerializedName("hero_interval_s")
    val heroIntervalS: Int = 5,
    @SerializedName("hero_max")
    val heroMax: Int = 6,
)

/**
 * One home rail the admin panel built. `key` is the operator's slug (the panel's
 * `home_sections.key`); the app prefixes it when it merges, so a panel rail can
 * never collide with a built-in one by accident. Items arrive resolved — the
 * server already applied the adult rule and the hide list before projecting.
 */
data class PanelSection(
    val key: String = "",
    val title: String = "",
    val items: List<Post> = emptyList(),
)

/**
 * One announcement the admin panel published. The server sends live,
 * published broadcasts of every target, so the app filters by its own
 * region, tier and version ([broadcastVisible]): `target` is one of
 * "all", "free", "vip", "region" or "version", and `targetDetail` names
 * which one — a panel region for "region", an exact version name for
 * "version", empty otherwise. An empty title means "nothing to say" and
 * the banner is skipped.
 */
data class PanelBroadcast(
    val id: Int = 0,
    val title: String = "",
    val body: String = "",
    val severity: String = "info",
    val target: String = "all",
    @SerializedName("target_detail")
    val targetDetail: String = "",
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
