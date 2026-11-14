package com.raddstream.app.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
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
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.raddstream.app.network.models.Post
import com.raddstream.app.ui.layout.CardGeometry
import com.raddstream.app.ui.theme.PressHaptics
import com.raddstream.app.ui.theme.RaddStreamTheme
import com.raddstream.app.ui.theme.pressScale

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
 * width, and the image is one [CardGeometry.POSTER_ASPECT] box tall, so it clears 48dp on any
 * phone.
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
        post.imdbRating?.let { UserWords.displayRating(it) }?.let { rating ->
            append(", rating ").append(rating).append(" out of 10")
        }
        if (tileBadges.isNotEmpty()) append(", ").append(tileBadges.joinToString(", ") { it.a11y })
        if (progressLabel != null) append(", ").append(progressLabel)
    }

    // F7 (Batch B): the title slot is exactly two lines tall, taken from the
    // style's own line height, so a one-line title leaves the same card height
    // as a two-line one — the round-2 "inconsistent card heights" complaint.
    // The height is density-scaled, so a 200% font scale grows the slot
    // instead of clipping the second line.
    val titleLineHeight = MaterialTheme.typography.titleSmall.lineHeight
    val titleSlotHeight = with(LocalDensity.current) {
        // TextUnit has no isSpecified in this Compose version — Unspecified
        // is the sentinel to compare against.
        if (titleLineHeight != TextUnit.Unspecified) (titleLineHeight.value * 2).sp.toDp() else 40.dp
    }

    val clickable = Modifier.semantics { contentDescription = a11y }

    // UI-fix P1-X1: the tile's own press source — the scale + haptic track
    // the same presses the tile's combinedClickable already owns.
    val pressSource = remember { MutableInteractionSource() }
    PressHaptics(pressSource)

    Card(
        modifier = modifier
            .fillMaxWidth()
            .then(clickable)
            .clip(RoundedCornerShape(12.dp))
            .pressScale(pressSource)
            .then(
                when {
                    onClick != null && onLongClick != null ->
                        Modifier.combinedClickable(
                            interactionSource = pressSource,
                            // 1.7.0 has no interactionSource-only overload:
                            // the indication is required, and null is right
                            // here — pressScale is the tile's feedback now,
                            // not the Material ripple.
                            indication = null,
                            onClick = onClick,
                            onLongClick = onLongClick,
                        )
                    onClick != null ->
                        Modifier.combinedClickable(
                            interactionSource = pressSource,
                            indication = null,
                            onClick = onClick,
                        )
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
                    .aspectRatio(CardGeometry.POSTER_ASPECT)
                    .background(MaterialTheme.colorScheme.surfaceVariant),
                contentAlignment = Alignment.BottomStart,
            ) {
                val posterUrl = post.posterUrl?.takeIf { it.isNotBlank() }
                if (posterUrl == null) {
                    ImageFallbackCard(
                        modifier = Modifier.fillMaxSize(),
                        // F6 (Batch A): the full title, not initials — the tile
                        // must say which title has no poster.
                        label = title,
                    )
                } else {
                    CatalogImage(
                        url = posterUrl,
                        contentDescription = null, // tile-level a11y already announced the title
                        modifier = Modifier.fillMaxSize(),
                        // A dead poster URL must not look like "no artwork exists" — the
                        // branded fallback says what failed, and keeps the title readable.
                        fallbackLabel = title,
                    )
                }

                // F12 (Batch B): the remove × no longer sits on the poster
                // art — it rode the image corner and covered the artwork on
                // every saved tile. It lives in the text row now, beside the
                // title, on the card surface; the image corner is art-only.
                // (The rating badge keeps BottomStart on the scrim — P0-1.)

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

                UserWords.displayRating(post.imdbRating)?.let { rating ->
                    // UI-fix P0-1: the badge used to sit TopEnd, painted OVER
                    // the remove × (same corner, declared later, so it won
                    // the tap) — rated titles in My List / Continue Watching
                    // could not be removed. It now rides BottomStart, above
                    // the 3dp progress bar, on the same scrim plate.
                    RatingBadge(
                        rating = rating,
                        modifier = Modifier
                            .align(Alignment.BottomStart)
                            .padding(start = 6.dp, bottom = 8.dp),
                    )
                }
            }

            // The text row: the title, details, badges and progress are paint
            // here, not four more nodes saying the same words the tile already
            // said — the column below is cleared for exactly that reason, so
            // the remove button sits BESIDE it in this row, not inside it:
            // a cleared subtree would swallow the button's own description
            // and tap. One spoken sentence per tile (see the a11y string
            // above).
            Row(
                modifier = Modifier.fillMaxWidth().padding(start = 8.dp, end = 8.dp, bottom = 10.dp),
                verticalAlignment = Alignment.Top,
            ) {
                Column(
                    modifier = Modifier.weight(1f).clearAndSetSemantics { },
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Text(
                        text = UserWords.breakableTitle(title),
                        color = MaterialTheme.colorScheme.onSurface,
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.height(titleSlotHeight),
                    )
                    if (details.isNotBlank()) {
                        Text(
                            text = details,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            style = MaterialTheme.typography.labelSmall,
                            // F7 (Batch B): one line, not two — year + type
                            // never needs a second line, and the second line
                            // was the other half of the uneven card heights.
                            maxLines = 1,
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

                // F12 (Batch B): one tap, not a held tile and not a confirm —
                // the × removes the row at once, and the screen offers Undo in
                // the snackbar. The button eats its own tap, so it never also
                // opens the title. It sits on the card surface beside the
                // title now, never on the poster art above.
                if (onRemove != null) {
                    IconButton(
                        onClick = onRemove,
                        modifier = Modifier
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
            }
        }
    }
}

/**
 * F25 (Batch B): the placeholder tile as Android Studio sees it — a title
 * with no poster art, so the F6 gradient + title treatment is visible
 * without running the app. The screenshot test in ScreenSnapshotTest pins
 * the same tile in CI.
 */
@Preview(name = "Poster card placeholder", showBackground = true)
@Composable
private fun PosterCardPlaceholderPreview() {
    RaddStreamTheme {
        PosterCard(
            post = Post(
                id = 1,
                title = "Jawan",
                cleanTitle = "Jawan",
                year = 2023,
                contentType = "movie",
                posterUrl = null,
            ),
            modifier = Modifier.width(180.dp),
        )
    }
}
