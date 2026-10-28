package com.raddstream.app.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.raddstream.app.network.ApiProvider
import com.raddstream.app.network.isSameOriginAsServer
import com.raddstream.app.network.streamRedirectUrl
import com.raddstream.app.ui.navigation.Screen
import com.raddstream.app.ui.navigation.Screen.Embed
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** What the provider-page screen may show: nothing yet, our redirector, or a refusal that says why. */
sealed class EmbedPage {
    data object Resolving : EmbedPage()

    /** The ONE address this screen can ever load — ours, never the provider's. */
    data class Ready(val url: String) : EmbedPage()

    /** A refusal with a reason a viewer can act on. Never a blank screen with a spinner. */
    data class Refused(val reason: String) : EmbedPage()
}

/**
 * Resolves the handle this screen was launched with into the single address it is allowed to
 * load: our own `/api/v1/stream?id=<handle>` redirector.
 *
 * WHY THE SCREEN HOLDS NO URL OF ITS OWN. The route argument is the opaque handle, exactly like
 * [Screen.Player]'s, and the address is rebuilt here from the server the viewer actually
 * connected to. The server's 302 then decides which page that handle leads to — this client
 * never composes, stores, or receives a provider address, so there is nothing here to sniff,
 * nothing to leak into a back stack or a bug report, and no hoster name that could reach a
 * screen. It is also why the same-origin check is not decorative: if the address we just built
 * is not on the origin the viewer configured, something above us is wrong and the safe answer is
 * to refuse rather than to load.
 */
@HiltViewModel
class EmbedWebViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val apiProvider: ApiProvider,
) : ViewModel() {

    private val streamId: String = Embed.decodeStreamId(
        savedStateHandle.get<String>(Embed.ARG_STREAM_ID).orEmpty(),
    )

    /** The work's title — the only name this screen ever shows. */
    val title: String = Embed.decodeTitle(savedStateHandle.get<String>(Embed.ARG_TITLE).orEmpty())

    private val _page = MutableStateFlow<EmbedPage>(EmbedPage.Resolving)
    val page = _page.asStateFlow()

    init {
        resolve()
    }

    /** Called on first composition and by the screen's "Try again". */
    fun resolve() {
        _page.value = EmbedPage.Resolving
        viewModelScope.launch {
            val base = runCatching { apiProvider.currentBaseUrl() }.getOrNull().orEmpty()
            val url = when {
                base.isBlank() || streamId.isBlank() -> null
                else -> streamRedirectUrl(base, streamId)
            }
            _page.value = when {
                streamId.isBlank() ->
                    EmbedPage.Refused("This source has no handle, so there is nothing to open.")
                base.isBlank() ->
                    EmbedPage.Refused("Connect to a server first.")
                url == null ->
                    EmbedPage.Refused("This source has no handle, so there is nothing to open.")
                !isSameOriginAsServer(url, base) ->
                    EmbedPage.Refused("That address is not on the server you connected to.")
                else -> EmbedPage.Ready(url)
            }
        }
    }
}
