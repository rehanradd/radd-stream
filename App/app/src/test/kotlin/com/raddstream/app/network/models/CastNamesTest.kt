package com.raddstream.app.network.models

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The cast parser only ever drops a chunk that cannot be a name — it never
 * invents one. The cases below are the real rows the staging databases
 * carry: comma-joined names, space-glued names, a synopsis fragment filed
 * as cast, and a scraper's UI text ("Bradley AndyDay tvgard") in front of
 * real names.
 */
class CastNamesTest {

    @Test
    fun `comma separated names parse in order`() {
        assertEquals(
            listOf("Noah Centineo", "Andrew Koji", "Callina Liang"),
            parseCastNames("Noah Centineo, Andrew Koji, Callina Liang"),
        )
    }

    @Test
    fun `a short comma-less string is one name`() {
        assertEquals(listOf("Shah Rukh Khan"), parseCastNames("Shah Rukh Khan"))
        assertEquals(listOf("Kajol"), parseCastNames("Kajol"))
    }

    @Test
    fun `a long comma-less string is several names glued together so it reads as no cast`() {
        assertTrue(parseCastNames("Mark Hamill Harrison Ford Carrie Fisher").isEmpty())
        assertTrue(parseCastNames("Dwayne Johnson Neve Campbell Chin Han").isEmpty())
    }

    @Test
    fun `a synopsis fragment filed as cast is dropped`() {
        assertTrue(
            parseCastNames(
                "Priya and Ranjan have paranormal experiences after she buys an antique box from a",
            ).isEmpty(),
        )
    }

    @Test
    fun `a junk chunk is dropped but the real names beside it survive`() {
        assertEquals(
            listOf("David Oakes", "Frida Gustavsson", "Goran Visnjic"),
            parseCastNames(
                "Bradley  AndyDay tvgard, David Oakes, Frida Gustavsson, Goran Visnjic",
            ),
        )
    }

    @Test
    fun `particles inside a name survive and duplicates collapse`() {
        assertEquals(
            listOf("Robert de Niro", "Jean-Claude Van Damme"),
            parseCastNames("Robert de Niro, Jean-Claude Van Damme, Robert de Niro"),
        )
    }

    @Test
    fun `blank or null is no cast`() {
        assertTrue(parseCastNames(null).isEmpty())
        assertTrue(parseCastNames("   ").isEmpty())
        assertTrue(parseCastNames("").isEmpty())
    }

    @Test
    fun `at most twelve names come back`() {
        val raw = ('A'..'O').joinToString(", ") { "Actor $it" }
        assertEquals(12, parseCastNames(raw).size)
    }
}
