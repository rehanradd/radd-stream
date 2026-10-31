package com.raddstream.app.tooling

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Room schema, checked as text, because nothing here can open a database.
 *
 * `FavoritePost` is a Room entity and `AppDatabase` holds the hand-written DDL that grows it.
 * The two are one contract in two files, and the way they disagree is a crash on a real device:
 * add a field to the entity without a migration and Room's runtime validation throws when the
 * app opens its own table, which is the worst possible moment to learn it. Robolectric has no
 * native runtime on this aarch64 host (`app/build.gradle.kts` excludes those suites), so an
 * in-memory database test would be a test that never runs. This scan is the proof that is
 * actually available offline, and it is deliberately dumb: it reads the same identifiers a
 * compiler or a device would compare.
 *
 * The positive controls matter as much as the assertions — a regex that matches nothing makes
 * every rule below vacuously true.
 */
class FavoritesSchemaGuardTest {

    private val repoRoot: File by lazy {
        var dir: File? = File("").absoluteFile
        while (dir != null) {
            if (File(dir, "brand.properties").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("brand.properties not found above ${File("").absolutePath}")
    }

    private val entity = File(
        repoRoot,
        "App/app/src/main/kotlin/com/raddstream/app/data/local/FavoritePost.kt",
    )
    private val database = File(
        repoRoot,
        "App/app/src/main/kotlin/com/raddstream/app/data/local/AppDatabase.kt",
    )
    private val module = File(
        repoRoot,
        "App/app/src/main/kotlin/com/raddstream/app/di/DatabaseModule.kt",
    )

    private val alterColumn =
        Regex("""ALTER TABLE favorite_posts ADD COLUMN (\w+)([^()]*)""")

    private val property = Regex("""^val (\w+)""")

    /** Property names of the entity constructor — Room's column names, verbatim. */
    private fun entityColumns(): List<String> {
        val text = entity.readText()
        val start = text.indexOf("data class FavoritePost(").takeIf { it >= 0 }
            ?: error("the favorites entity is not where this test thinks it is")
        val end = text.indexOf("\n)", start)
        assertTrue("the constructor of FavoritePost was never closed", end > start)
        return text.substring(start, end).lines()
            .map { it.trim() }
            .filterNot { it.startsWith("*") || it.startsWith("/*") || it.startsWith("//") }
            .mapNotNull { declaration -> property.find(declaration)?.groupValues?.get(1) }
    }

    /** Kotlin's string bodies flattened into the SQL they hold, in file order. */
    private fun flattenedDdl(): String = database.readText()
        .replace("\"", " ")
        .replace("+", " ")
        .replace(Regex("""\s+"""), " ")

    /** Every `favorite_posts` column the DDL history can produce, in the order it produces it. */
    private fun ddlColumns(): List<String> {
        val flat = flattenedDdl()
        val anchor = "CREATE TABLE IF NOT EXISTS favorite_posts"
        val createAt = flat.lastIndexOf(anchor)
        assertTrue("the favorites table has no rebuild DDL to read", createAt >= 0)
        val open = flat.indexOf('(', createAt + anchor.length)
        assertTrue("the favorites CREATE has no column list", open > createAt)

        var depth = 0
        var close = -1
        for (i in open until flat.length) {
            when (flat[i]) {
                '(' -> depth++
                ')' -> {
                    depth--
                    if (depth == 0) {
                        close = i
                        break
                    }
                }
            }
        }
        assertTrue("the favorites column list never closes", close > open)

        val created = flat.substring(open + 1, close).split(',')
            .map { it.trim() }
            .filter { it.isNotEmpty() && !it.startsWith("PRIMARY KEY") }
            .map { it.split(Regex("""\s+""")).first() }
        val added = alterColumn.findAll(flat.substring(close))
            .map { it.groupValues[1] }
            .toList()
        return created + added
    }

    @Test
    fun `the scan sees the same table a device would open`() {
        val columns = entityColumns()
        val ddl = ddlColumns()

        // Positive controls: a parse that returned nothing would make every rule below green.
        assertTrue(columns.containsAll(listOf("id", "title", "contentType", "addedAt")))
        assertTrue(ddl.containsAll(listOf("id", "title", "contentType", "addedAt")))
        assertEquals(
            "the favorites CREATE is the one full rebuild this scan may treat as a baseline",
            1,
            flattenedDdl().split("CREATE TABLE IF NOT EXISTS favorite_posts").size - 1,
        )
    }

    @Test
    fun `the entity and the DDL history declare exactly the same favorites columns`() {
        assertEquals(
            "a field on the entity with no column in the DDL throws at database open on a device",
            ddlColumns().sorted(),
            entityColumns().sorted(),
        )
    }

    @Test
    fun `the animation flag and the subtitles flag are both carried and both added by migration`() {
        val columns = entityColumns()
        assertTrue("the saved row must know the work is animated", columns.contains("isAnimated"))
        assertTrue("and whether any print claims subtitles", columns.contains("subtitled"))

        val flat = flattenedDdl()
        assertTrue(flat.contains("ALTER TABLE favorite_posts ADD COLUMN isAnimated INTEGER"))
        assertTrue(flat.contains("ALTER TABLE favorite_posts ADD COLUMN subtitled INTEGER"))
    }

    @Test
    fun `a column added to a saved list is nullable, so no old row gains an invented fact`() {
        val flat = flattenedDdl()
        val history = flat.substring(flat.lastIndexOf("CREATE TABLE IF NOT EXISTS favorite_posts"))
        val added = alterColumn.findAll(history).toList()
        assertTrue("positive control: the scan found no ALTER statement at all", added.isNotEmpty())
        added.forEach { match ->
            val declaration = match.groupValues[2]
            assertFalse(
                "${match.groupValues[1]} would force a value on every row saved before it",
                declaration.contains("NOT NULL"),
            )
        }
    }

    @Test
    fun `the declared database version is the target of the newest migration`() {
        val flat = database.readText().replace(Regex("""\s+"""), " ")
        val steps = Regex("""object : Migration\((\d+), (\d+)\)""").findAll(flat)
            .map { it.groupValues[1].toInt() to it.groupValues[2].toInt() }
            .toList()
        assertTrue("positive control: no migration was found to read", steps.isNotEmpty())
        steps.forEach { (from, to) ->
            assertEquals("every migration climbs exactly one version", to, from + 1)
        }
        val declared = Regex("""version = (\d+)""").find(flat)
            ?.groupValues?.get(1)?.toIntOrNull()
        assertEquals(steps.maxOf { it.second }, declared)
    }

    @Test
    fun `version 7 is the adult step and it only ever adds`() {
        val flat = flattenedDdl()
        assertTrue(
            "a saved list may not be rebuilt to close the adult hole — 6 -> 7 must exist as DDL",
            flat.contains("object : Migration(6, 7)"),
        )
        // Bounded at the next declared step, so a later 7 -> 8 that legitimately rebuilds the
        // table cannot be charged to this one — and a scan that read to end-of-file would be.
        val body = flat.substringAfter("object : Migration(6, 7)")
            .substringBefore("object : Migration(")
        assertTrue(
            "the flag column must be added, not assumed",
            body.contains("ALTER TABLE favorite_posts ADD COLUMN is18Plus INTEGER"),
        )
        assertTrue(
            "and the answer stamp alongside it",
            body.contains("ALTER TABLE favorite_posts ADD COLUMN checkedAt INTEGER"),
        )
        listOf("DROP TABLE", "DELETE FROM", "RENAME TO").forEach { verb ->
            assertFalse(
                "6 -> 7 would discard the viewer's own rows if it contained $verb",
                body.contains(verb),
            )
        }
    }

    @Test
    fun `the refusal ledger is declared once, in both files, with the same columns`() {
        val ledger = File(
            repoRoot,
            "App/app/src/main/kotlin/com/raddstream/app/data/local/UnavailableWork.kt",
        )
        assertTrue("the refusal entity file vanished", ledger.isFile)
        val text = ledger.readText()
        val start = text.indexOf("data class UnavailableWorkEntity(").takeIf { it >= 0 }
            ?: error("the refusal entity is not where this test thinks it is")
        val end = text.indexOf("\n)", start)
        val columns = text.substring(start, end).lines()
            .map { it.trim() }
            .filterNot { it.startsWith("*") || it.startsWith("/*") || it.startsWith("//") }
            .mapNotNull { declaration -> property.find(declaration)?.groupValues?.get(1) }
        assertTrue("positive control: no refusal column parsed", columns.contains("postId"))
        assertTrue(columns.containsAll(listOf("refusedAt", "reason")))

        val flat = flattenedDdl()
        val create = flat.substringAfter("CREATE TABLE IF NOT EXISTS unavailable_works")
            .substringBefore("PRIMARY KEY")
        listOf("postId", "refusedAt", "reason").forEach { column ->
            assertTrue(
                "$column is on the entity but not in the DDL, which throws at database open",
                create.contains(column),
            )
        }
        assertTrue(
            "a refusal is keyed by the id it refuses, or a second 404 stacks rows",
            flat.substringAfter("CREATE TABLE IF NOT EXISTS unavailable_works")
                .contains("PRIMARY KEY(postId)"),
        )
    }

    @Test
    fun `every migration the database declares is registered on the builder`() {
        val declared = Regex("""val (MIGRATION_\d+_\d+)""").findAll(database.readText())
            .map { it.groupValues[1] }
            .toList()
        assertTrue("positive control: nothing declared itself a migration", declared.isNotEmpty())
        val registered = module.readText()
        declared.forEach { name ->
            assertTrue("$name is declared but never handed to Room", registered.contains(name))
        }
    }
}
