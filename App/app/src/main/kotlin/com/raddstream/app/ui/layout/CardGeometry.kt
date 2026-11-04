package com.raddstream.app.ui.layout

/**
 * The one place catalog geometry is decided.
 *
 * A row scans cleanly only when every tile in it — and the placeholder that stood there a
 * second earlier — is the same shape. Before this object existed the poster ratio was written
 * out three times (a card, a detail header, a skeleton), the rail tile width twice, and
 * the design spec asked for `2f/3f` while the code drew `0.68f`. Nothing reported the drift,
 * because each copy was individually correct-looking.
 *
 * [CardGeometryTest] keeps it that way: it walks the UI sources and refuses an `aspectRatio`
 * literal that is not one of the values defined here.
 *
 * Shapes are named by ARTWORK CLASS, not by screen: a poster, a season art band and an episode
 * still are three different crops of three different assets, and forcing them to share one
 * ratio would crop faces out of episode thumbs. The rule this file enforces is that each class
 * has exactly one ratio for every screen that draws it.
 */
object CardGeometry {

    /**
     * Poster tiles: home rails, the browse and my-list grids, search results, the detail
     * header and every skeleton that stands in for one.
     *
     * Shipped at the value the code already drew at all three call sites, so consolidating them
     * changes no pixel. `design/DESIGN_SYSTEM.md` §8 still asks for 2:3 (0.667); that is an open
     * owner question, and the answer is now a one-line edit here rather than three.
     */
    const val POSTER_ASPECT: Float = 0.68f

    /** Rail tile width. A rail cell and its placeholder both draw from this one number. */
    const val RAIL_CARD_WIDTH_DP: Int = 132

    /** The detail header's poster column: the same ratio, a fixed column instead of a rail cell. */
    const val DETAIL_POSTER_WIDTH_DP: Int = 120

    /** The wide art band above a season's episode list: the work's art cropped wide. */
    const val SEASON_ART_ASPECT: Float = 3.2f

    /** Episode stills and backdrops — the 16:9 class, including the hero. */
    const val WIDE_ART_ASPECT: Float = 16f / 9f
}
