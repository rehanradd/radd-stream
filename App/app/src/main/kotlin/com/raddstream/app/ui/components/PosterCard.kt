package com.raddstream.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.Post

/**
 * The canonical catalog tile. Used by Home rails, the search grid, My List and
 * Downloads. Kept intentionally light (one [CatalogImage] + a couple of Texts) and
 * always rendered inside a keyed lazy container so Compose can recycle slots cheaply
 * on low-RAM phones (Compose performance guidance).
 *
 * Accessibility: the whole tile exposes a single merged content description
 * ("title, year, type, rating") so TalkBack announces it as one item rather than
 * three, and every tap target fills the tile width (>=48dp tall image).
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PosterCard(
    post: Post,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
    rank: Int? = null,
) {
    val title = post.cleanTitle?.takeIf { it.isNotBlank() } ?: post.title
    val typeLabel = post.contentType?.takeIf { it.isNotBlank() }?.replaceFirstChar { it.uppercase() }
    val details = listOfNotNull(
        post.year?.takeIf { it > 0 }?.toString(),
        typeLabel,
    ).joinToString(" · ")
    val a11y = buildString {
        append(title)
        if (details.isNotBlank()) append(", ").append(details)
        post.imdbRating?.takeIf { it.isNotBlank() }?.let { append(", rating ").append(it).append(" out of 10") }
    }

    val clickable = Modifier.semantics { contentDescription = a11y }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .then(clickable)
            .clip(RoundedCornerShape(12.dp))
            .then(
                when {
                    onClick != null && onLongClick != null ->
                        Modifier.combinedClickable(onClick = onClick, onLongClick = onLongClick)
                    onClick != null ->
                        Modifier.combinedClickable(onClick = onClick)
                    else -> Modifier
                }
            ),
        shape = RoundedCornerShape(12.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(0.68f)
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.BottomStart,
            ) {
                val posterUrl = post.posterUrl?.takeIf { it.isNotBlank() }
                if (posterUrl == null) {
                    ImageFallbackCard(
                        modifier = Modifier.fillMaxSize(),
                        label = title.take(2).uppercase(),
                    )
                } else {
                    CatalogImage(
                        url = posterUrl,
                        contentDescription = null, // tile-level a11y already announced the title
                        modifier = Modifier.fillMaxSize(),
                        // A dead poster URL must not look like "no artwork exists" — the
                        // branded fallback says what failed, and keeps the title readable.
                        fallbackLabel = title.take(2).uppercase(),
                    )
                }

                // Bottom scrim so overlaid text/rank stays legible over any poster.
                Box(
                    Modifier
                        .fillMaxWidth()
                        .align(Alignment.BottomCenter)
                        .background(
                            Brush.verticalGradient(
                                colors = listOf(
                                    androidx.compose.ui.graphics.Color.Transparent,
                                    MaterialTheme.colorScheme.scrim.copy(alpha = 0.55f),
                                )
                            )
                        )
                        .height(36.dp),
                )

                if (rank != null) {
                    Box(
                        modifier = Modifier
                            .align(Alignment.TopStart)
                            .padding(6.dp)
                            .clip(RoundedCornerShape(6.dp))
                            .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.6f))
                            .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(6.dp))
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                    ) {
                        Text(
                            text = "#$rank",
                            color = MaterialTheme.colorScheme.onBackground,
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                        )
                    }
                }

                post.imdbRating?.takeIf { it.isNotBlank() }?.let { rating ->
                    Text(
                        text = "★ $rating",
                        color = MaterialTheme.colorScheme.tertiary,
                        style = MaterialTheme.typography.labelMedium,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.align(Alignment.TopEnd).padding(6.dp),
                    )
                }
            }

            Column(
                modifier = Modifier.padding(start = 8.dp, end = 8.dp, bottom = 10.dp),
                verticalArrangement = Arrangement.spacedBy(2.dp),
            ) {
                Text(
                    text = title,
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                if (details.isNotBlank()) {
                    Text(
                        text = details,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.labelSmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                // Dub status decides whether this title is watchable at all for a
                // Hindi/Urdu-first viewer, so it is said on the tile, not after a tap.
                AudioBadgeChipRow(badges = TileAudioBadges.forPost(post))
            }
        }
    }
}
