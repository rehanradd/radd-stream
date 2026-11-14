package com.raddstream.app.ui.components

import android.os.SystemClock
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.snap
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Favorite
import androidx.compose.material.icons.filled.FavoriteBorder
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.raddstream.app.brand.Brand
import com.raddstream.app.network.models.Post
import com.raddstream.app.network.models.WireText
import com.raddstream.app.ui.theme.PressHaptics
import com.raddstream.app.ui.theme.RaddEmphasized
import com.raddstream.app.ui.theme.RaddMotion
import com.raddstream.app.ui.theme.RaddStreamMark
import com.raddstream.app.ui.theme.RaddTokens
import com.raddstream.app.ui.theme.pressScale
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * The banner rail on Home: [heroHeight] tall, a rounded card floating on a soft
 * ambient glow, one work at a time, advancing on its own.
 *
 * Layout of one slide, back to front:
 *  - the ambient glow ([HeroAmbientGlow]): two low-alpha radial blooms tinted from the
 *    theme, drifting to a new hue as the active page changes — light spilling into the
 *    inset around the card, which is what gives the banner depth instead of a pasted-on
 *    rectangle;
 *  - the widest artwork the row carries, cropped to fill;
 *  - a vertical scrim that goes from clear at the top to the page background at the
 *    bottom, so the title and buttons stay readable over any poster;
 *  - the title, a year badge and up to [MAX_LANGUAGE_PILLS] language pills;
 *  - page dots, which double as the manual affordance — tapping a dot jumps to that slide.
 *    They sit at the TOP end of the banner, in a contrast pill: bottom-anchored they shared
 *    the buttons' strip, and their 48dp hit boxes (declared after the pager, so on top in
 *    z-order) covered the Watch Now button's centre on a 6-dot hero — a centred tap hit a
 *    dot, which just re-selected the slide, so Watch Now looked dead while the banner tap
 *    (above the strip) worked. The top band never meets the button strip; see
 *    [heroIndicatorOverlapsActionRow].
 *  - a prominent Watch Now button, which starts the title (the slide's own tap target
 *    only opens the details — the button is the part that says "play"); beside it, a
 *    My List toggle, so saving a title does not need a trip to its details page;
 *
 * WHAT THE HERO PAINTS (App/AGENTS.md §5): `GET /api/v1/posts` projects a
 * `backdrop_urls` column alongside `poster_url` (`Fast_Fetch/viewer.py` `_art_pair()`),
 * and that is the wide TMDB artwork this banner is built for — so the default image is the
 * first backdrop, and the poster is only the fallback for a row that has no backdrop, or a
 * server whose list projection predates the column. The hero never invents a URL from
 * `tmdb_id`: a TMDB image path is not derivable from the id, and guessing one would be a
 * 404 on every tile. [backdropFor] is the seam if that policy ever changes.
 *
 * Auto-advance is motion, so it respects the same system switch as the skeletons
 * ([rememberReduceMotion]): with animations off the banner still paginates by hand, it just
 * never moves on its own, and the glow cuts instead of cross-fading. A drag also gets the
 * pager back immediately — the loop waits for `isScrollInProgress` to clear before it takes
 * the page away again. The same guard covers a finger already down on Watch Now: an
 * advance that STARTS mid-press slides the button out from under it, and the tap
 * detector cancels a press whose target moved away — so the loop skips its tick while
 * the button reports pressed (`watchNowPressed`) instead of stealing the tap.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun HeroCarousel(
    posts: List<Post>,
    onPostClick: (Post) -> Unit,
    modifier: Modifier = Modifier,
    backdropFor: (Post) -> String? = { it.heroArtUrl },
    /** The operator's theme: false pauses the auto-advance, the interval is in ms. */
    autoplay: Boolean = true,
    intervalMs: Long = AUTO_ADVANCE_MS,
    /** Session 121 (P-26): Watch Now starts the title instead of only opening it. */
    onWatchNow: (Post) -> Unit = onPostClick,
    isFavorite: (Post) -> Boolean = { false },
    onToggleFavorite: (Post) -> Unit = {},
) {
    if (posts.isEmpty()) return
    val reduceMotion = rememberReduceMotion()
    val pagerState = rememberPagerState(pageCount = { posts.size })
    val scrollScope = rememberCoroutineScope()
    // True while a finger is down on the visible slide's Watch Now button, reported
    // up by HeroSlide. The advance loop reads it per tick (it is deliberately NOT
    // a LaunchedEffect key: restarting the effect would cancel an in-flight
    // animateScrollToPage and strand the pager between pages).
    var watchNowPressed by remember { mutableStateOf(false) }
    // Samsung RTL (v1.1.2, Issue 3): the banner rotated every 5 s and a
    // manual swipe or dot tap did not restart the clock, so the slide a
    // viewer had just chosen could be yanked away a beat later — and
    // Watch Now was a moving target. The advance loop below reads this
    // timestamp per tick: any page change (auto or manual), any drag, and
    // any dot tap restarts the full interval, so a viewer always gets the
    // whole interval on the slide they are looking at.
    var lastChangeMs by remember { mutableLongStateOf(SystemClock.uptimeMillis()) }
    // A drag that snaps back to the same page changes no page, so the
    // page effect below would not see it — the scroll flag is the record
    // that the viewer is handling the banner right now.
    LaunchedEffect(pagerState.isScrollInProgress) {
        if (pagerState.isScrollInProgress) lastChangeMs = SystemClock.uptimeMillis()
    }
    // Self-heal for the press flag: if the pressed slide is ever disposed mid-press
    // (a two-finger drag paging away under the finger), its release callback never
    // fires and the flag would stick true, parking auto-advance forever. A page
    // change means the pressed button is gone, so the flag is stale by definition.
    // A normal press can never trip this — the loop below holds its tick while the
    // flag is true, and a dot tap needs the finger to be on a dot, not the button.
    LaunchedEffect(pagerState.currentPage) {
        watchNowPressed = false
        lastChangeMs = SystemClock.uptimeMillis()
    }

    LaunchedEffect(posts.size, reduceMotion, autoplay, intervalMs) {
        if (!autoplay || posts.size < 2 || reduceMotion) return@LaunchedEffect
        while (true) {
            // Tick, don't sleep the whole interval: a press, a drag, or a
            // manual page change part-way through the wait must hold the
            // advance, and a single long delay could not notice any of them
            // until it had already fired. The tick is the only cost; the
            // decision — and its test — lives in [shouldAdvanceHero].
            delay(HERO_ADVANCE_TICK_MS)
            if (!shouldAdvanceHero(
                    nowMs = SystemClock.uptimeMillis(),
                    lastChangeMs = lastChangeMs,
                    intervalMs = intervalMs,
                    isScrolling = pagerState.isScrollInProgress,
                    watchNowPressed = watchNowPressed,
                )
            ) continue
            lastChangeMs = SystemClock.uptimeMillis()
            pagerState.animateScrollToPage(
                nextHeroPage(pagerState.currentPage, posts.size),
                animationSpec = RaddMotion.defaultSpatial(),
            )
        }
    }

    Box(modifier.fillMaxWidth().height(heroHeight())) {
        HeroAmbientGlow(
            currentPage = pagerState.currentPage,
            modifier = Modifier.fillMaxSize(),
        )

        HorizontalPager(
            state = pagerState,
            // F28 (Batch B): the pager composes only the current page by
            // default, so every auto-advance started a fresh image load and
            // the hero read as empty mid-load (the Batch 0/1 empty-hero
            // shots). One page of lookahead keeps the next slide's art
            // warm, so an advance lands on a painted slide.
            beyondBoundsPageCount = 1,
            modifier = Modifier.fillMaxSize().padding(heroInset),
        ) { page ->
            val post = posts.getOrNull(page) ?: return@HorizontalPager
            HeroSlide(
                post = post,
                backdropUrl = backdropFor(post),
                onClick = { onPostClick(post) },
                onWatchNow = { onWatchNow(post) },
                onWatchNowPressChange = { watchNowPressed = it },
                isFavorite = isFavorite(post),
                onToggleFavorite = { onToggleFavorite(post) },
                modifier = Modifier.clip(RoundedCornerShape(HERO_CORNER)),
            )
        }

        if (posts.size > 1) {
            HeroIndicator(
                count = posts.size,
                current = pagerState.currentPage,
                // Scrolling is a suspending pager call, so the dot's click launches it on the
                // composition's scope instead of pretending the tap can wait for it inline.
                // The tap also restarts the auto-advance clock outright: tapping the
                // current dot changes no page, so the page effect would not see it,
                // and without this the slide just chosen could still be yanked away
                // a beat later (Samsung RTL v1.1.2, Issue 3).
                onSelect = { index ->
                    lastChangeMs = SystemClock.uptimeMillis()
                    scrollScope.launch {
                        pagerState.animateScrollToPage(index, animationSpec = RaddMotion.defaultSpatial())
                    }
                },
                // Top end, NOT the bottom strip: the dots' 48dp hit boxes used to sit
                // in the buttons' band (bottom 20dp), declared after the pager so on
                // top in z-order, and on a 6-dot hero they covered the Watch Now
                // button's centre — a centred tap hit a dot, not the button. Up here
                // no dot can cover any control; the pill keeps them readable over
                // bright artwork, where the top scrim is clear.
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(top = HERO_INDICATOR_TOP_DP.dp, end = 16.dp),
            )
        }
    }
}

/**
 * The banner's own placeholder while the first rail is still in flight. It keeps the real
 * hero's footprint ([heroHeight]) so the page does not jump when artwork lands, and a few
 * shimmering bars stand in for the title, badges and Watch Now button.
 *
 * Samsung RTL (v1.1.2, Issue 3): the first load read as a blank grey box for ~10 s.
 * The skeleton was already here — but its shimmer band (0.16f) is near-invisible
 * over the surfaceVariant base, so on a phone it read as flat grey, not as
 * loading. The band runs stronger here ([HERO_SKELETON_SHIMMER_ALPHA]) and the
 * brand mark sits in the middle, so the wait reads as "featured titles are
 * loading" instead of an empty slot. The mark is decorative canvas, like the
 * fallback card's, and stays out of the accessibility tree with the bars.
 */
@Composable
fun HeroSkeleton(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxWidth().height(heroHeight())) {
        Box(Modifier.fillMaxSize().padding(heroInset).clip(RoundedCornerShape(HERO_CORNER))) {
            ShimmerBox(Modifier.fillMaxSize(), highlightAlpha = HERO_SKELETON_SHIMMER_ALPHA)
            RaddStreamMark(
                diameter = 56.dp,
                color = MaterialTheme.colorScheme.primary.copy(alpha = 0.55f),
                modifier = Modifier.align(Alignment.Center),
            )
            Column(
                modifier = Modifier
                    .align(Alignment.BottomStart)
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp)
                    .padding(bottom = 20.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                ShimmerBox(
                    Modifier.fillMaxWidth(0.55f).height(36.dp),
                    shape = RoundedCornerShape(8.dp),
                )
                ShimmerBox(
                    Modifier.width(120.dp).height(16.dp),
                    shape = RoundedCornerShape(8.dp),
                )
                ShimmerBox(
                    Modifier.width(150.dp).height(HERO_BUTTON_HEIGHT_DP.dp),
                    shape = RoundedCornerShape(28.dp),
                )
            }
        }
    }
}

/**
 * Two soft radial blooms behind the banner, tinted from the theme's accent trio and
 * cross-fading to the next hue as the pager moves. The card is inset by [heroInset], so
 * this light spills out around it — depth without a single extra image.
 */
@Composable
private fun HeroAmbientGlow(currentPage: Int, modifier: Modifier = Modifier) {
    val scheme = MaterialTheme.colorScheme
    val accents = remember(scheme.primary, scheme.secondary, scheme.tertiary) {
        listOf(scheme.primary, scheme.secondary, scheme.tertiary)
    }
    val reduceMotion = rememberReduceMotion()
    val fade = if (reduceMotion) snap<Color>() else RaddMotion.slowEffects()
    val leading by animateColorAsState(accents[currentPage % accents.size], fade, label = "heroGlowLeading")
    val trailing by animateColorAsState(accents[(currentPage + 1) % accents.size], fade, label = "heroGlowTrailing")

    Box(
        modifier.drawBehind {
            drawRect(
                Brush.radialGradient(
                    colors = listOf(leading.copy(alpha = 0.34f), leading.copy(alpha = 0f)),
                    center = Offset(size.width * 0.30f, size.height * 0.20f),
                    radius = size.maxDimension * 0.72f,
                ),
            )
            drawRect(
                Brush.radialGradient(
                    colors = listOf(trailing.copy(alpha = 0.24f), trailing.copy(alpha = 0f)),
                    center = Offset(size.width * 0.84f, size.height * 0.66f),
                    radius = size.maxDimension * 0.58f,
                ),
            )
        },
    )
}

@Composable
private fun HeroSlide(
    post: Post,
    backdropUrl: String?,
    onClick: () -> Unit,
    onWatchNow: () -> Unit = onClick,
    /** Reports the Watch Now button's press state up, so the auto-advance loop can
     *  hold its tick while a finger is down on it instead of sliding the button
     *  away mid-tap. Default no-op: the slide is still fully usable without it. */
    onWatchNowPressChange: (Boolean) -> Unit = {},
    isFavorite: Boolean = false,
    onToggleFavorite: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    val title = post.displayTitle
    val languages = remember(post.language) { heroLanguagePills(post.language) }
    // The slide merges its children, so TalkBack reads this line and then the Watch Now button
    // inside it. Saying "watch now" here as well would announce the same action twice.
    val a11y = buildString {
        append(title)
        post.yearLabel?.let { append(", ").append(it) }
        if (languages.isNotEmpty()) append(", languages ").append(languages.joinToString())
    }

    Box(
        modifier = modifier
            .fillMaxSize()
            .semantics { contentDescription = a11y }
            .clickable(onClick = onClick),
    ) {
        // 1 — artwork, or the branded fallback card when there is nothing to paint.
        // F6 (Batch A): the blank-backdrop branch used to paint a labelless card —
        // a bare gradient with no title at all. It now names the title, like the
        // failed-load fallback below it.
        if (backdropUrl.isNullOrBlank()) {
            ImageFallbackCard(label = title)
        } else {
            CatalogImage(
                url = backdropUrl,
                contentDescription = null, // the merged description above already tells it
                modifier = Modifier.fillMaxSize(),
                contentScale = ContentScale.Crop,
                fallbackLabel = title,
            )
        }

        // 2 — vertical scrim: clear at the crest, page background under the text.
        // Session 121 (P-20): the old scrim stayed near-clear until 45% down, so the
        // hero title collided with the poster's own baked-in title art. The scrim
        // now starts earlier and ends darker, so the words sit on background,
        // not on artwork.
        Box(
            Modifier
                .fillMaxSize()
                .background(
                    Brush.verticalGradient(
                        0f to MaterialTheme.colorScheme.background.copy(alpha = 0f),
                        0.35f to MaterialTheme.colorScheme.background.copy(alpha = 0.25f),
                        0.7f to MaterialTheme.colorScheme.background.copy(alpha = 0.65f),
                        1f to MaterialTheme.colorScheme.background.copy(alpha = 0.95f),
                    )
                ),
        )

        // 3 — the words. With art they sit at the bottom, over the scrim.
        // Without art (F8c, Batch B) the slide is a branded fallback card
        // that already names the title in its centre — repeating the headline
        // at the bottom left an enormous empty area with the buttons sitting
        // very low, reading as a missing background. So the art-less slide
        // centres its badges + buttons instead, and drops the repeated title.
        val hasArt = !backdropUrl.isNullOrBlank()
        Column(
            modifier = Modifier
                .align(if (hasArt) Alignment.BottomStart else Alignment.CenterStart)
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = if (hasArt) HERO_ACTION_BOTTOM_DP.dp else 0.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (hasArt) {
                Text(
                    text = title,
                    style = RaddEmphasized.displaySmall,
                    color = MaterialTheme.colorScheme.onBackground,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }

            Row(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                post.yearLabel?.let { HeroBadge(it) }
                post.typeLabel?.let { HeroBadge(it) }
                languages.forEach { HeroBadge(it, subdued = true) }
            }

            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // UI-fix P1-X1: press scale + haptic on the hero's primary action.
                val watchNowSource = remember { MutableInteractionSource() }
                PressHaptics(watchNowSource)
                // The same press state the haptic reads, reported up: the carousel
                // holds its auto-advance tick while this is true. Collected here,
                // not in the carousel, because the source belongs to this slide's
                // button — the carousel only ever sees the visible slide's press.
                val watchNowPressed by watchNowSource.collectIsPressedAsState()
                LaunchedEffect(watchNowPressed) { onWatchNowPressChange(watchNowPressed) }
                Button(
                    onClick = onWatchNow,
                    shape = RoundedCornerShape(28.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.primary,
                        contentColor = MaterialTheme.colorScheme.onPrimary,
                    ),
                    interactionSource = watchNowSource,
                    modifier = Modifier.height(HERO_BUTTON_HEIGHT_DP.dp).pressScale(watchNowSource),
                ) {
                    Icon(
                        imageVector = Icons.Default.PlayArrow,
                        contentDescription = null,
                        modifier = Modifier.size(22.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(Brand.copy("hero_watch_now", "Watch Now"), fontWeight = FontWeight.Bold)
                }
                // Session 121 (P-26): My List on the hero, so saving a title does not
                // need a trip to its details page first. The filled heart says saved;
                // the treatment matches the year/type badges above it.
                Button(
                    onClick = onToggleFavorite,
                    shape = RoundedCornerShape(28.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.55f),
                        contentColor = MaterialTheme.colorScheme.onBackground,
                    ),
                    // CL-6: the button's visible text is "My List", the same words
                    // as the nav tab — so it announces what the tap does instead:
                    // "Save to My List", or "Saved to My List" once saved.
                    modifier = Modifier
                        .height(HERO_BUTTON_HEIGHT_DP.dp)
                        .semantics { contentDescription = if (isFavorite) "Saved to My List" else "Save to My List" },
                ) {
                    Icon(
                        imageVector = if (isFavorite) Icons.Default.Favorite else Icons.Default.FavoriteBorder,
                        contentDescription = null,
                        modifier = Modifier.size(20.dp),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(if (isFavorite) "Saved" else "My List", fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

/** One small pill: the year badge and the language badges share this exact shape. */
@Composable
private fun HeroBadge(text: String, subdued: Boolean = false) {
    val scheme = MaterialTheme.colorScheme
    Box(
        Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(
                if (subdued) scheme.scrim.copy(alpha = 0.6f) else scheme.surface.copy(alpha = 0.55f)
            )
            .padding(horizontal = 8.dp, vertical = 3.dp),
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.SemiBold,
            // Robo run 2: the subdued pill's 85%-white text on the 0.6f scrim
            // (LC-2) is still ~3.8:1 over bright art — under the 4.5:1 floor.
            // Full-strength text on the same scrim is ~5.7:1 worst case; the
            // pill stays subdued by its darker scrim, not by dimming its words.
            color = scheme.onBackground,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/**
 * Page dots that are also buttons: the active one stretches into a short bar, so the state
 * reads at a glance, and each dot jumps the pager to its slide.
 *
 * The painted dot is 5dp tall and used to be the only thing a finger could aim at. Each one now
 * sits inside the [DOT_TOUCH_WIDTH] by [DOT_TOUCH_HEIGHT] box — 48dp square, the WCAG 2.2 AA
 * minimum in both directions (the 24dp width it used to have failed Robo's 48dp touch-target
 * floor). The row rides at the TOP end of the hero, in a contrast pill: at the bottom end
 * its hit boxes shared the buttons' strip and, on a 6-dot hero, covered the Watch Now
 * button's centre — a centred tap selected a dot instead of starting the title. Up here
 * the row can be as wide as the dot count needs without covering any control, and the
 * pill (0.72f surface, up from 0.55f — the round-2 re-review found the dots blending
 * into bright artwork) keeps the dots readable over bright artwork, where the top scrim
 * is clear. The dots themselves shrank in Batch B (active 18dp → 12dp, 7dp → 5dp tall):
 * the old capsule read oversized next to the badges. Each dot also says what
 * it is in words and carries a `selected` state, because the visual stretch was the only thing
 * that used to show which slide is up.
 */
@Composable
private fun HeroIndicator(
    count: Int,
    current: Int,
    onSelect: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    Row(
        modifier = modifier
            // Session 154 (N-1): the indicator pill is fully round — 24dp is
            // not on the M3 shape scale (20 → 28).
            .clip(RaddTokens.Shape.Pill)
            .background(scheme.surface.copy(alpha = 0.72f))
            .padding(horizontal = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        repeat(count) { index ->
            val active = index == current
            Box(
                modifier = Modifier
                    .size(width = DOT_TOUCH_WIDTH, height = DOT_TOUCH_HEIGHT)
                    .clickable(onClickLabel = "Show banner ${index + 1} of $count") { onSelect(index) }
                    .semantics {
                        contentDescription = "Banner ${index + 1} of $count"
                        selected = active
                    },
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    Modifier
                        .size(width = if (active) 12.dp else 5.dp, height = 5.dp)
                        .clip(RoundedCornerShape(4.dp))
                        .background(scheme.onBackground.copy(alpha = if (active) 0.95f else 0.45f)),
                )
            }
        }
    }
}

/**
 * A language value the server actually knows. The catalog sends the literal words
 * "Unknown" and "N/A" for titles whose language was never recorded — a missing value,
 * not a language — so every place that draws a language name drops those (F2, Batch A),
 * instead of each site re-deciding what counts as unknown.
 */
internal fun isKnownLanguage(value: String): Boolean =
    value.isNotBlank() && !value.equals("unknown", ignoreCase = true) && !value.equals("n/a", ignoreCase = true)

/**
 * Language pills, trimmed to what a banner can show. `posts.language` is free TEXT —
 * "Hindi + English + Japanese", a bare "English", sometimes nothing — so [WireText.listOf]
 * is the only sanctioned reader, and a single long value is cut rather than allowed to
 * push the title off the slide.
 *
 * F2 (Batch A): the server also sends the literal words "Unknown" and "N/A" for titles
 * whose language was never recorded — a missing value, not a language. Those are dropped
 * here, and [DetailScreen]'s meta row and the audio/subtitle badges hide them the same
 * way, so no pill, meta line or badge ever reads "Unknown" at a viewer.
 */
internal fun heroLanguagePills(raw: String?, max: Int = MAX_LANGUAGE_PILLS): List<String> =
    WireText.listOf(raw)
        .map { it.trim() }
        .filter { isKnownLanguage(it) && it.length <= MAX_PILL_LENGTH }
        .distinct()
        .take(max)

/**
 * The auto-advance step, pure so the wrap-around is testable: the next page, or page 0
 * again after the last one. A degenerate count advances nowhere.
 */
internal fun nextHeroPage(currentPage: Int, pageCount: Int): Int =
    if (pageCount <= 0) 0 else (currentPage + 1) % pageCount

/**
 * Whether the auto-advance loop may take the next slide, pure so the timing
 * is testable without a pager. A drag in progress, or a press on Watch Now,
 * holds the tick — an advance starting under a finger moves the button away
 * before tap-up, and the tap is then cancelled instead of navigating. And a
 * full [intervalMs] must have passed since the last page change or user
 * interaction ([lastChangeMs]): a manual swipe or dot tap restarts the clock,
 * so the slide just chosen is never yanked away a beat later (Samsung RTL
 * v1.1.2, Issue 3). A non-positive interval never advances on its own.
 */
internal fun shouldAdvanceHero(
    nowMs: Long,
    lastChangeMs: Long,
    intervalMs: Long,
    isScrolling: Boolean,
    watchNowPressed: Boolean,
): Boolean {
    if (isScrolling || watchNowPressed) return false
    if (intervalMs <= 0L) return false
    return nowMs - lastChangeMs >= intervalMs
}

/**
 * The vertical bands the hero's top and bottom controls live in, in dp from the hero's
 * top edge — the single source of truth for both the layout above and the regression
 * test (HeroCarouselTest). The indicator is top-anchored at [HERO_INDICATOR_TOP_DP]
 * with height [DOT_TOUCH_HEIGHT_DP]; the action row (Watch Now + My List) is
 * bottom-anchored, [HERO_ACTION_BOTTOM_DP] up from the bottom edge, [HERO_BUTTON_HEIGHT_DP]
 * tall. [heroIndicatorOverlapsActionRow] is false exactly when the two bands do not
 * meet — which is what broke Watch Now: the old bottom-anchored indicator sat in the
 * same band as the buttons, and its hit boxes (on top in z-order) ate the taps.
 */
internal const val HERO_INDICATOR_TOP_DP = 16f
internal const val HERO_BUTTON_HEIGHT_DP = 56f
internal const val HERO_ACTION_BOTTOM_DP = 20f
private const val DOT_TOUCH_HEIGHT_DP = 48f

/** True when an indicator whose top edge sits [indicatorTopDp] below the hero's top edge
 *  would overlap the Watch Now / My List button strip of a hero [heroHeightDp] tall. */
internal fun heroIndicatorOverlapsActionRow(heroHeightDp: Float, indicatorTopDp: Float): Boolean {
    val indicatorBottom = indicatorTopDp + DOT_TOUCH_HEIGHT_DP
    val actionsTop = heroHeightDp - HERO_ACTION_BOTTOM_DP - HERO_BUTTON_HEIGHT_DP
    return indicatorBottom > actionsTop
}

private const val MAX_LANGUAGE_PILLS = 3
private const val MAX_PILL_LENGTH = 18
/**
 * Samsung RTL (v1.1.2, Issue 3): 5 s per slide made Watch Now a moving
 * target — a viewer reading the slide and then reaching for the button got
 * the slide yanked away. 8 s is a full read plus a comfortable tap, and the
 * operator can still retune it from the panel (`hero_interval_s`); this is
 * only the default when no theme has been published. HomeScreen, PanelTheme
 * and the theme mirror in ServerSettingsRepository carry the same 8 s, so no
 * layer silently reverts it to 5.
 */
private const val AUTO_ADVANCE_MS = 8_000L

/** The auto-advance loop's tick: short enough to notice a press, a drag, or a
 *  manual page change promptly, long enough to cost nothing. */
private const val HERO_ADVANCE_TICK_MS = 500L

/** The skeleton's shimmer band runs stronger than the shared default
 *  (ShimmerBox), so the first-load hero reads as loading, not blank grey. */
private const val HERO_SKELETON_SHIMMER_ALPHA = 0.30f

/**
 * The page dot's hit box: 48dp square, the WCAG 2.2 AA minimum in both directions.
 * The painted dot inside it stays 7dp.
 */
private val DOT_TOUCH_HEIGHT: Dp = DOT_TOUCH_HEIGHT_DP.dp
private val DOT_TOUCH_WIDTH: Dp = 48.dp

/**
 * The banner's height. A rounded, inset hero wants ~16:9 of a phone screen plus the text
 * block; 400dp keeps the first rail's posters peeking over the fold, so the page still
 * reads as a catalog and not as a single poster. UI-fix P1-H2: on a narrow phone
 * (360dp class) 400dp is 62% of the screen for one title — the hero caps at 320dp
 * there, so the first rail still shows below it.
 */
@Composable
private fun heroHeight(): Dp {
    val width = LocalConfiguration.current.screenWidthDp
    return if (width < 400) 320.dp else 400.dp
}

/** The glow shows through this gutter — enough to read, not enough to look like a border. */
private val heroInset = PaddingValues(start = 14.dp, end = 14.dp, top = 10.dp, bottom = 10.dp)

private val HERO_CORNER: Dp = 28.dp
