package com.raddstream.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.raddstream.app.network.models.Post
import com.raddstream.app.ui.theme.RaddArtScrim

/**
 * The canonical catalog tile. Used by Home rails, the search grid, My List and
 * Downloads. Kept intentionally light (one [CatalogImage] + a couple of Texts) and
 * always rendered inside a keyed lazy container so Compose can recycle slots cheaply
 * on low-RAM phones (Compose performance guidance).
 *
 * Accessibility: the tile leads with one merged sentence — title, year and type, the rating out
 * of ten, and the progress line when the app has one — so the facts arrive in an order that
 * reads, instead of as bare labels off the artwork. The painted star is decorative to a screen
 * reader for exactly that reason: the sentence already says it. Every tap target fills the tile
 * width, and the image is 0.68 of it, so it clears 48dp on any phone.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun PosterCard(
    post: Post,
    modifier: Modifier = Modifier,
    onClick: (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
    /**
     * How far a title the viewer already started has run, 0f..1f, or null when the app never
     * learned a duration. Only the Continue watching rail has an honest answer for this: a bar
     * on any other tile would claim a position the viewer has no row for. It is drawn as a
     * width, not only as a colour, so it survives a colour-blind viewer and a screen reader.
     */
    progressFraction: Float? = null,
    /** The same fact in words — "S2:E5 · 23 min left". */
    progressLabel: String? = null,
    /**
     * One-tap remove, shown as a small × on the poster's corner. Only My List
     * and Continue Watching pass it: everywhere else the tile is a doorway,
     * not a list to edit, and a remove badge there would be a trap for a
     * slipping thumb.
     */
    onRemove: (() -> Unit)? = null,
) {
    val title = post.cleanTitle?.takeIf { it.isNotBlank() } ?: post.title
    val typeLabel = post.typeLabel
    val details = listOfNotNull(
        post.year?.takeIf { it > 0 }?.toString(),
        typeLabel,
    ).joinToString(" · ")
    // Robo run 2: the badge pills announced their a11y labels as separate
    // nodes, so every tile with the same badge repeated the same words ("Hindi
    // dub of a work originally in another language" on dozens of tiles). The
    // tile speaks one sentence — badges included — and the painted row below
    // is paint-only, so a screen reader hears each tile once.
    val tileBadges = TileAudioBadges.forPost(post)
    val a11y = buildString {
        append(title)
        if (details.isNotBlank()) append(", ").append(details)
        post.imdbRating?.takeIf { it.isNotBlank() }?.let { append(", rating ").append(it).append(" out of 10") }
        if (tileBadges.isNotEmpty()) append(", ").append(tileBadges.joinToString(", ") { it.a11y })
        if (progressLabel != null) append(", ").append(progressLabel)
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

                // One tap, not a held tile and not a confirm: the × removes
                // the row at once, and the screen offers Undo in the snackbar.
                // The button eats its own tap, so it never also opens the title.
                if (onRemove != null) {
                    IconButton(
                        onClick = onRemove,
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .padding(6.dp)
                            .size(48.dp)
                            .background(
                                MaterialTheme.colorScheme.surface.copy(alpha = 0.85f),
                                CircleShape,
                            ),
                    ) {
                        Icon(
                            Icons.Default.Close,
                            contentDescription = "Remove $title from My List",
                            tint = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier.size(16.dp),
                        )
                    }
                }

                // Bottom scrim: a poster's lower edge is whatever the artwork happens to be, and
                // the progress bar below has to stay visible against it.
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

                progressFraction?.let { fraction ->
                    Box(
                        Modifier
                            .align(Alignment.BottomCenter)
                            .fillMaxWidth()
                            .height(3.dp)
                            .background(MaterialTheme.colorScheme.scrim.copy(alpha = 0.55f)),
                    ) {
                        Box(
                            Modifier
                                .fillMaxWidth(fraction.coerceIn(0f, 1f))
                                .fillMaxHeight()
                                .background(MaterialTheme.colorScheme.primary),
                        )
                    }
                }

                post.imdbRating?.takeIf { it.isNotBlank() }?.let { rating ->
                    // E-C1: the rating sat in tertiary directly on the artwork —
                    // 2.28:1 on white art, 1.73:1 on mid-grey. It now sits on a
                    // RaddArtScrim plate, like every other badge over artwork.
                    Box(
                        modifier = Modifier
                            .align(Alignment.TopEnd)
                            .padding(6.dp)
                            .background(RaddArtScrim, RoundedCornerShape(4.dp))
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                    ) {
                        Text(
                            text = "★ $rating",
                            color = MaterialTheme.colorScheme.tertiary,
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.Bold,
                            // Decorative: the merged tile description already says
                            // "rating 8.1 out of 10", and a node that clears its own semantics is
                            // how a Compose text stops being read a second time.
                            modifier = Modifier.clearAndSetSemantics { },
                        )
                    }
                }
            }

            Column(
                // One spoken sentence per tile (see the a11y string above):
                // the title, details, badges and progress are paint here, not
                // four more nodes saying the same words the tile already said.
                modifier = Modifier.padding(start = 8.dp, end = 8.dp, bottom = 10.dp).clearAndSetSemantics { },
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
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                // Session 121 (P-28): the badge row only exists when a title has
                // badges, so cards in one rail had different heights and a badge
                // could straddle the rail's clip edge ("Dual Audio" cut mid-glyph).
                // The slot is always 24 dp — the pill's own height — so card height
                // is invariant to badge presence and rails stay uniform.
                Box(Modifier.fillMaxWidth().height(24.dp), contentAlignment = Alignment.CenterStart) {
                    // Dub status decides whether this title is watchable at all for a
                    // Hindi/Urdu-first viewer, so it is said on the tile, not after a tap.
                    AudioBadgeChipRow(badges = tileBadges)
                }

                progressLabel?.let { label ->
                    Text(
                        text = label,
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.labelSmall,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}
