package com.raddstream.app.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Test

class PanelTabsTest {

    @Test
    fun `empty remote list falls back to the shipped four`() {
        assertEquals(
            listOf("home", "search", "my_list", "settings"),
            PanelTabs.resolve(emptyList(), searchEnabled = true),
        )
    }

    @Test
    fun `operator order stands and unknown ids drop out`() {
        assertEquals(
            listOf("home", "my_list", "settings"),
            PanelTabs.resolve(listOf("my_list", "home", "nope", "settings"), searchEnabled = true),
        )
    }

    @Test
    fun `home is pinned first even when listed last`() {
        assertEquals(
            listOf("home", "settings"),
            PanelTabs.resolve(listOf("settings", "home"), searchEnabled = true),
        )
    }

    @Test
    fun `home is added when the operator omitted it`() {
        assertEquals(
            listOf("home", "settings"),
            PanelTabs.resolve(listOf("settings"), searchEnabled = true),
        )
    }

    @Test
    fun `duplicates collapse and casing and spaces are forgiven`() {
        assertEquals(
            listOf("home", "search"),
            PanelTabs.resolve(listOf(" Home ", "SEARCH", "home"), searchEnabled = true),
        )
    }

    @Test
    fun `search drops out when its feature flag is off`() {
        assertEquals(
            listOf("home", "my_list"),
            PanelTabs.resolve(listOf("search", "my_list"), searchEnabled = false),
        )
    }

    @Test
    fun `all-unknown remote list falls back to the shipped four`() {
        assertEquals(
            listOf("home", "search", "my_list", "settings"),
            PanelTabs.resolve(listOf("nope", "alsono"), searchEnabled = true),
        )
    }
}
