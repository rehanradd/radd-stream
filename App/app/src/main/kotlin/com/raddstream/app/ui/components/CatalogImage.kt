package com.raddstream.app.ui.components

import android.content.Context
import android.graphics.Bitmap
import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.graphics.drawable.toBitmap
import coil.compose.SubcomposeAsyncImage
import coil.request.ImageRequest
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.images.ArtUrlPolicy
import com.raddstream.app.images.ImageSizingHolder
import com.raddstream.app.images.ImageSizingPolicy
import com.raddstream.app.ui.theme.RaddStreamMark
import dagger.hilt.EntryPoint
import dagger.hilt.InstallIn
import dagger.hilt.android.EntryPointAccessors
import dagger.hilt.components.SingletonComponent

/**
 * The ONE place a catalog image turns a stored preference into a Coil request. Home, Browse, Search,
 * My List (all via [PosterCard]) and the detail header render posters through here, so the Settings
 * "Image quality" row and the mobile-data switch cannot be honoured on one screen and quietly ignored
 * on another — the drift this whole file exists to prevent.
 *
 * [onBitmap] is the artwork-accent hook: a caller that wants the poster's own colour (the detail
 * header's border) gets the decoded bitmap on success, and nothing when the load is gated or fails.
 * It is optional and defaults to off, so the grid cells that never need a bitmap pay nothing.
 *
 * It reads [ImageSizingHolder], an Application-owned singleton, through a Hilt [EntryPoint] off the
 * ambient [LocalContext], because a poster lives deep inside a recycled grid cell where no screen
 * composes a ViewModel. Handing Coil an explicit [ImageRequest] size is the whole point: left to
 * itself Coil decodes to the view box, so "Battery saver" would still pull a full poster and the
 * setting would be a decoration. Passing the request as `model` (not a bare URL) is how the width
 * actually reaches the decoder in Coil 2.x.
 *
 * When the load is gated off — metered connection and no mobile-data permission — `model` is null, so
 * Coil makes no request at all and whatever the surrounding card already paints behind the image (the
 * surfaceVariant placeholder, or the initials tile when there is no URL) is exactly what the viewer
 * sees. What is NOT protected: metered-ness is sampled once per composition, so an image already on
 * screen stays up if the network flips to metered while you scroll; only the next request obeys it.
 * That is the deliberate cost of not parking a live ConnectivityListener on every list.
 *
 * Phase 7 (M4): the URL itself is gated too, by [ArtUrlPolicy]. The server already
 * vets catalog art through `/api/v1/art`, and this is the client-side second lock:
 * a URL that is not our server, a public image CDN, or a neutral upload host never
 * reaches Coil — the fallback card paints instead, so no upstream domain ever
 * learns a viewer opened a title. [allowAnyHost] is the one documented exception:
 * live-TV channel logos come from the operator-curated channel registry, not the
 * catalog, and their hosts are the registry's own — the caller opts out by name.
 *
 * A *failed* load is different from a *gated* one and gets its own art. Nothing about a
 * dead poster URL is the caller's fault — the server sent a link, the CDN did not answer —
 * so instead of leaving a bare surfaceVariant rectangle (which reads as "this title has no
 * artwork", a claim about the content rather than about the network) the tile paints
 * [ImageFallbackCard]: a dark branded panel carrying the source-ripple mark and, when the
 * caller supplied one, the title's initials. [fallbackLabel] is optional precisely because
 * not every call site has a title to hand; the mark alone is a complete answer.
 *
 * A failed load is retried, not filed away. Samsung RTL (v1.1.2, Issue 5):
 * Salaar's poster URL is alive (HEAD 200 from the Oracle VM, 0.19 s) yet the
 * phone showed the dark "SA" fallback — one transient fetch failure, and
 * Coil's single attempt left the tile failed for the whole visit, with no
 * way back. A failure now re-requests at once, up to [MAX_IMAGE_AUTO_RETRIES]
 * times ([shouldAutoRetryImage] is the bound), and once those are spent the
 * fallback itself is tappable to try again — a tap is a deliberate retry, so
 * it is never bounded. The retries are immediate on purpose: a delayed retry
 * would park a coroutine on the composition clock, which the frozen-clock
 * Robolectric tests cannot advance past; a bounded immediate re-request
 * settles the same way a single attempt does.
 */
@Composable
fun CatalogImage(
    url: String?,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Crop,
    fallbackLabel: String? = null,
    onBitmap: ((Bitmap?) -> Unit)? = null,
    /**
     * Phase 7 (M4): true only for operator-curated art whose hosts are the
     * registry's own (live-TV channel logos). Catalog art never passes this.
     */
    allowAnyHost: Boolean = false,
) {
    val context = LocalContext.current
    val holder = remember(context) { imageSizingHolder(context) }
    val sizing by holder.sizing.collectAsState()
    val metered = holder.isMetered()
    val settingsRepository = remember(context) { serverSettingsRepository(context) }
    val serverUrl by settingsRepository.serverUrl.collectAsState(initial = null)
    val serverHost = remember(serverUrl) { ArtUrlPolicy.hostOf(serverUrl) }

    // The load attempt this URL is on: 0 is the first request, and each
    // failure below bumps it (bounded) while a tap on the failed tile bumps
    // it without a bound. It is part of the request's key, so a bump
    // re-issues the fetch instead of re-showing the same failure.
    var attempt by remember(url) { mutableIntStateOf(0) }

    val request = remember(url, sizing, metered, serverHost, allowAnyHost, attempt) {
        val decision = ImageSizingPolicy.decide(
            widthPx = sizing.posterMaxWidthPx,
            imagesAllowedOnMobileData = sizing.imagesAllowedOnMobileData,
            metered = metered,
        )
        val clean = url?.takeIf { it.isNotBlank() }
        val allowed = allowAnyHost || ArtUrlPolicy.isAllowed(clean, serverHost)
        // DIAGNOSTIC ONLY (poster-diag build, 2026-11-13): one line per load decision —
        // this remember block re-runs only when a decision input changes, so a scrolling
        // list does not spam logcat. It answers the three questions the BrowserStack
        // poster experiment left open: did a URL arrive at all (kind/host), did the
        // metered gate block it (metered + mobileDataAllowed -> shouldLoad), and did
        // the allowlist block it (allowed) — before Coil is even involved. The full
        // URL is deliberately NOT logged: an art handle carries a signed token.
        // Filter: tag:PosterDiag, look for DECISION.
        Log.d(
            "PosterDiag",
            "DECISION kind=${posterUrlKind(clean)} host=${ArtUrlPolicy.hostOf(clean)} " +
                "metered=$metered mobileDataAllowed=${sizing.imagesAllowedOnMobileData} " +
                "shouldLoad=${decision.shouldLoad} allowed=$allowed " +
                "outcome=${if (clean != null && decision.shouldLoad && allowed) "REQUEST" else "NO_REQUEST"}",
        )
        if (clean != null && decision.shouldLoad && allowed) {
            ImageRequest.Builder(context)
                .data(clean)
                .size(decision.widthPx, decision.widthPx)
                .build()
        } else {
            null
        }
    }

    // A request that was never made — no URL, a gated load (metered
    // connection with no mobile-data permission), or a disallowed host —
    // must not shimmer forever: the shimmer is a loading state, and nothing
    // is loading. The branded fallback says "no artwork" honestly, with the
    // mark and the initials to look at. Robo run 6: a gated Detail poster
    // showed as a flat dark surfaceVariant rectangle (image contrast 1.33)
    // because the null model left the box blank behind the shimmer.
    if (request == null) {
        ImageFallbackCard(
            label = fallbackLabel,
            modifier = modifier,
        )
        return
    }

    // Robo run 8: until this request has produced a bitmap, the box holds the
    // loading shimmer, not an image — a flat dark rectangle the checker scores
    // as a picture (McLintock! detail poster, 1.63:1 — the sampled colours are
    // the poster's own surfaceVariant box and outlineVariant frame, no artwork
    // at all). The image node stays out of the accessibility tree until there
    // is an image to describe (the run-7 ShimmerBox pattern); on success it
    // appears with its content description, and on error the fallback card
    // speaks instead. Keyed on the request, so a new URL starts hidden again.
    var loaded by remember(request) { mutableStateOf(false) }

    SubcomposeAsyncImage(
        model = request,
        contentDescription = contentDescription,
        modifier = modifier.then(if (loaded) Modifier else Modifier.clearAndSetSemantics { }),
        contentScale = contentScale,
        // A real request in flight gets the moving shimmer; a gated or blank URL never
        // reaches this slot, so the surface behind the card stays the truth in that case.
        loading = { ShimmerBox(Modifier.fillMaxSize()) },
        // A failed load shows the branded fallback — and the fallback is
        // tappable to try again, because a tile that failed once must not
        // stay failed for the whole visit when the URL itself is alive.
        error = {
            Box(
                Modifier
                    .fillMaxSize()
                    .clickable(onClickLabel = "Retry loading image") { attempt++ },
            ) {
                ImageFallbackCard(label = fallbackLabel, modifier = Modifier.fillMaxSize())
            }
        },
        // The artwork-accent hook: only a caller that passed onBitmap pays the
        // decode-to-bitmap, and only on a real success — a gated or failed load
        // reports nothing, so the caller keeps its fallback colour.
        onSuccess = { state ->
            loaded = true
            onBitmap?.invoke(state.result.drawable.toBitmap())
        },
        // A transient failure re-requests at once, bounded by
        // [shouldAutoRetryImage]: one failed fetch must not leave a live
        // poster as a dark initials tile for the whole visit. Once the
        // bound is spent the error slot above is the way back — a tap
        // re-issues the fetch without a bound, because a tap is deliberate.
        onError = {
            if (shouldAutoRetryImage(attempt)) attempt++ else loaded = false
        },
    )
}

/**
 * Auto-retries for a failed catalog image: the first load plus
 * [MAX_IMAGE_AUTO_RETRIES] immediate re-requests, then the error slot's
 * tap-to-retry is the only way back. The bound is what keeps a permanently
 * dead URL from re-requesting forever; the tap is unbounded because a tap
 * is a deliberate retry. Pure so the bound is testable without Coil.
 */
internal const val MAX_IMAGE_AUTO_RETRIES = 2

internal fun shouldAutoRetryImage(attempt: Int, maxAutoRetries: Int = MAX_IMAGE_AUTO_RETRIES): Boolean =
    attempt < maxAutoRetries

/**
 * DIAGNOSTIC ONLY (poster-diag build, 2026-11-13): classifies a poster URL for the DECISION
 * log line — "art" is a server `/api/v1/art` handle, "direct" is a CDN/upload-host URL the
 * server passed through untouched, "none" is a missing/blank URL. Pure so it stays testable
 * without a device.
 */
internal fun posterUrlKind(url: String?): String = when {
    url.isNullOrBlank() -> "none"
    "/api/v1/art" in url -> "art"
    else -> "direct"
}

/**
 * The dark placeholder every failed catalog image falls back to. Colours come only from
 * the theme, never a literal, so a re-brand from `brand.properties` restyles this with the
 * rest of the app.
 */
@Composable
fun ImageFallbackCard(
    modifier: Modifier = Modifier,
    label: String? = null,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    listOf(
                        MaterialTheme.colorScheme.surfaceVariant,
                        MaterialTheme.colorScheme.surface,
                        MaterialTheme.colorScheme.background,
                    )
                )
            ),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            modifier = Modifier.padding(8.dp),
        ) {
            RaddStreamMark(
                diameter = 30.dp,
                color = MaterialTheme.colorScheme.primary.copy(alpha = 0.55f),
            )
            // Session 121 (P-15): the label is title initials ("AL"), never punctuation.
            // A label with no letter or digit in it — a "?" from a mistyped title, or
            // a stray symbol — renders as the mark alone instead of a stray glyph.
            val safeLabel = label?.takeIf { it.any { ch -> ch.isLetterOrDigit() } }
            if (!safeLabel.isNullOrBlank()) {
                Text(
                    text = safeLabel,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.titleSmall,
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                    modifier = Modifier.padding(top = 6.dp),
                )
            }
        }
    }
}

/** Reaches the Application-owned sizing singleton from any composable — the [com.raddstream.app.brand.Brand]
 *  "read it anywhere" convenience, but for a DI object that must observe DataStore rather than BuildConfig. */
private fun imageSizingHolder(context: Context): ImageSizingHolder =
    EntryPointAccessors.fromApplication(
        context.applicationContext,
        ImageSizingEntryPoint::class.java,
    ).imageSizingHolder()

/** Phase 7 (M4): the server settings, read the same way — the art policy needs the configured host. */
private fun serverSettingsRepository(context: Context): ServerSettingsRepository =
    EntryPointAccessors.fromApplication(
        context.applicationContext,
        ImageSizingEntryPoint::class.java,
    ).serverSettingsRepository()

@EntryPoint
@InstallIn(SingletonComponent::class)
interface ImageSizingEntryPoint {
    fun imageSizingHolder(): ImageSizingHolder
    fun serverSettingsRepository(): ServerSettingsRepository
}
