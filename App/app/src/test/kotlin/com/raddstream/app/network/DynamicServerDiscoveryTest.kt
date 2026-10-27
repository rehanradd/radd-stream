package com.raddstream.app.network

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class DynamicServerDiscoveryTest {

    @Test
    fun parseHtmlNodes_extractsPrimaryAndBackups() {
        val sampleHtml = """
            <!DOCTYPE html>
            <html>
            <head>
              <meta content="noindex, nofollow" name="robots"/>
              <meta content="http://92.4.95.252" name="radd-primary"/>
              <meta content="https://backup1.yourdomain.com" name="radd-backup-1"/>
              <meta content="https://backup2.yourdomain.com" name="radd-backup-2"/>
            </head>
            <body>ok</body>
            </html>
        """.trimIndent()

        val (primary, backups) = DynamicServerDiscovery.parseHtmlNodes(sampleHtml)

        assertEquals("http://92.4.95.252", primary)
        assertEquals(2, backups.size)
        assertEquals("https://backup1.yourdomain.com", backups[0])
        assertEquals("https://backup2.yourdomain.com", backups[1])
    }

    @Test
    fun parseHtmlNodes_handlesNameFirstMetaTags() {
        val sampleHtml = """
            <html>
            <head>
              <meta name='radd-primary' content='http://10.0.0.1:8080'/>
              <meta name='radd-backup-alpha' content='https://fallback.node.com'/>
            </head>
            </html>
        """.trimIndent()

        val (primary, backups) = DynamicServerDiscovery.parseHtmlNodes(sampleHtml)

        assertEquals("http://10.0.0.1:8080", primary)
        assertEquals(1, backups.size)
        assertEquals("https://fallback.node.com", backups[0])
    }

    @Test
    fun parseHtmlNodes_emptyOnIrrelevantHtml() {
        val (primary, backups) = DynamicServerDiscovery.parseHtmlNodes("<html><body>Nothing here</body></html>")
        assertEquals(null, primary)
        assertEquals(0, backups.size)
    }
}
