package com.raddstream.app.ui.components

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import coil.compose.SubcomposeAsyncImage
import coil.request.ImageRequest
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
 * A *failed* load is different from a *gated* one and gets its own art. Nothing about a
 * dead poster URL is the caller's fault — the server sent a link, the CDN did not answer —
 * so instead of leaving a bare surfaceVariant rectangle (which reads as "this title has no
 * artwork", a claim about the content rather than about the network) the tile paints
 * [ImageFallbackCard]: a dark branded panel carrying the source-ripple mark and, when the
 * caller supplied one, the title's initials. [fallbackLabel] is optional precisely because
 * not every call site has a title to hand; the mark alone is a complete answer.
 */
@Composable
fun CatalogImage(
    url: String?,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Crop,
    fallbackLabel: String? = null,
) {
    val context = LocalContext.current
    val holder = remember(context) { imageSizingHolder(context) }
    val sizing by holder.sizing.collectAsState()
    val metered = holder.isMetered()

    val request = remember(url, sizing, metered) {
        val decision = ImageSizingPolicy.decide(
            widthPx = sizing.posterMaxWidthPx,
            imagesAllowedOnMobileData = sizing.imagesAllowedOnMobileData,
            metered = metered,
        )
        val clean = url?.takeIf { it.isNotBlank() }
        if (clean != null && decision.shouldLoad) {
            ImageRequest.Builder(context)
                .data(clean)
                .size(decision.widthPx, decision.widthPx)
                .build()
        } else {
            null
        }
    }

    SubcomposeAsyncImage(
        model = request,
        contentDescription = contentDescription,
        modifier = modifier,
        contentScale = contentScale,
        // A real request in flight gets the moving shimmer; a gated or blank URL never
        // reaches this slot, so the surface behind the card stays the truth in that case.
        loading = { ShimmerBox(Modifier.fillMaxSize()) },
        error = { ImageFallbackCard(label = fallbackLabel) },
    )
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
            if (!label.isNullOrBlank()) {
                Text(
                    text = label,
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

@EntryPoint
@InstallIn(SingletonComponent::class)
interface ImageSizingEntryPoint {
    fun imageSizingHolder(): ImageSizingHolder
}
