package com.raddstream.app.viewmodel

import com.raddstream.app.network.models.Post

/**
 * One work, one row.
 *
 * The same film can reach the search results as two catalog rows: the importer wrote it once from
 * one source and again from another, and the server's `work_ref` — the handle it mints for a WORK,
 * not for a row — says so. Nothing merged them on the way to the screen, so the viewer saw
 * Inception twice, the results count claimed two titles where there was one, and tapping the other
 * copy opened the other's id. The spec's list is explicit: duplicate search results are forbidden.
 *
 * Merging is a rule about identity, so it belongs next to its only caller ([SearchViewModel]) and
 * out of that caller's flow chain, where a device would be needed to prove anything. It never
 * deletes a row the wire has not proved identical.
 */
object SearchMerge {

    /**
     * The result list with duplicate works collapsed to one row each, in the order the server sent
     * them.
     *
     * Two rules bound what may merge, and both exist to stop this file guessing:
     *  - a row merges only with a row carrying the SAME non-blank [Post.workRef]. A blank or absent
     *    work_ref is not "the same unknown work" — it is a row the server has not named, and two
     *    unnamed rows are two rows. Dropping one would drop a title from the catalog as far as the
     *    viewer can tell.
     *  - the row that stays is the one that tells the viewer the most, chosen by [richer]: more
     *    releases and sources first (a work with six prints is worth opening over the same work
     *    with one), then artwork, then IMDb rating, then year, then the older id. Nothing here
     *    re-scores a print or invents a count the wire did not send.
     *
     * Position is the FIRST row of the group, so a viewer who scanned the list top-down finds the
     * title where they left it; the richer copy of it moves into that slot rather than the list
     * reordering under their finger.
     */
    fun dedupe(posts: List<Post>): List<Post> {
        val winnerByRef = LinkedHashMap<String, Post>()
        val firstPosition = HashMap<String, Int>()
        val out = ArrayList<Post>(posts.size)
        posts.forEachIndexed { index, post ->
            val ref = post.workRef?.trim()?.takeIf { it.isNotEmpty() }
            if (ref == null) {
                out += post
                return@forEachIndexed
            }
            val held = winnerByRef[ref]
            if (held == null) {
                winnerByRef[ref] = post
                firstPosition[ref] = out.size
                out += post
            } else {
                val best = if (richer(post, held)) post else held
                winnerByRef[ref] = best
                out[firstPosition.getValue(ref)] = best
            }
        }
        return out
    }

    /**
     * Does [candidate] tell the viewer more about the work than [incumbent]? A strict order, so
     * two equally informative copies never swap for no reason: the one the server sent first stays.
     */
    private fun richer(candidate: Post, incumbent: Post): Boolean {
        val bySources = sourcesOf(candidate).compareTo(sourcesOf(incumbent))
        if (bySources != 0) return bySources > 0
        val byArt = hasArt(candidate).compareTo(hasArt(incumbent))
        if (byArt != 0) return byArt > 0
        val byImdb = imdbOf(candidate).compareTo(imdbOf(incumbent))
        if (byImdb != 0) return byImdb > 0
        val byYear = (candidate.year ?: 0).compareTo(incumbent.year ?: 0)
        if (byYear != 0) return byYear > 0
        return candidate.id < incumbent.id
    }

    /** The counts the wire sends, treating an absent field as zero rather than as a win. */
    private fun sourcesOf(post: Post): Int = (post.releaseCount ?: 0) + (post.sourceCount ?: 0)

    private fun hasArt(post: Post): Int =
        if (!post.posterUrl.isNullOrBlank() || !post.backdropUrls.isNullOrBlank()) 1 else 0

    private fun imdbOf(post: Post): Double = post.imdbRating?.toDoubleOrNull() ?: 0.0
}
