package com.raddstream.app.ui.components

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.raddstream.app.images.ImageSizingHolder
import com.raddstream.app.images.ImageSizingPolicy
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
 */
@Composable
fun CatalogImage(
    url: String?,
    contentDescription: String?,
    modifier: Modifier = Modifier,
    contentScale: ContentScale = ContentScale.Crop,
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

    AsyncImage(
        model = request,
        contentDescription = contentDescription,
        modifier = modifier,
        contentScale = contentScale,
    )
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
