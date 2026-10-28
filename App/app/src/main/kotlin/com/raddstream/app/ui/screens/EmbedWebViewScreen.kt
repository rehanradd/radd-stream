package com.raddstream.app.ui.screens

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.view.View
import android.view.ViewGroup
import android.webkit.PermissionRequest
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.hilt.navigation.compose.hiltViewModel
import com.raddstream.app.R
import com.raddstream.app.viewmodel.EmbedPage
import com.raddstream.app.viewmodel.EmbedWebViewModel
import java.util.Locale

/**
 * The provider's own page, shown to the viewer, for a source the server says is a page rather
 * than a file (`ProviderPageLinks`).
 *
 * WHAT THIS SCREEN IS NOT. It is not a resolver and it inspects nothing. There is no
 * `shouldInterceptRequest`, no `DownloadListener`, no traffic sniffing and no hidden WebView
 * kept off-screen until a media URL floats past: this app does not take a provider's video out of
 * its player, and the owner's decision on that is recorded in
 * `App/docs/PARITY_BACKEND_BLOCKED.md`. What this screen does is display the page the server
 * pointed the handle at, in the foreground, with the hoster's own controls, its own conditions
 * and its own advertising, exactly as the page was written to be watched.
 *
 * WHAT IT LOADS: `<server>/api/v1/stream?id=<handle>` — our redirector for our handle, rebuilt by
 * [EmbedWebViewModel] from the server the viewer connected to. The 302 is the server's, not
 * ours. Consequences the design accepts:
 *  - the address bar never appears here, because the address is not the viewer's information to
 *    have in a UI that could be screenshotted, and because the *page title* is a hoster name —
 *    which is why `onReceivedTitle` is deliberately not wired to the header. The header shows the
 *    work's title, the only name this app knows.
 *  - "Open in browser" hands over OUR redirector, never `webView.url`, so the same-origin rule
 *    every other hand-off in the app obeys holds here too.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EmbedWebViewScreen(
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: EmbedWebViewModel = hiltViewModel(),
) {
    val context = LocalContext.current
    val page by viewModel.page.collectAsState()

    var webView by remember { mutableStateOf<WebView?>(null) }
    var loadedUrl by remember { mutableStateOf<String?>(null) }
    var loadFailure by remember { mutableStateOf<String?>(null) }
    var blockedScheme by remember { mutableStateOf<String?>(null) }
    var progress by remember { mutableIntStateOf(0) }
    var customView by remember { mutableStateOf<View?>(null) }
    var exitCustomView by remember { mutableStateOf<(() -> Unit)?>(null) }

    val loadingCopy = stringResource(R.string.embed_loading)
    val noticeCopy = stringResource(R.string.embed_hosted_notice)
    val retryCopy = stringResource(R.string.embed_retry)
    val openCopy = stringResource(R.string.embed_open_in_browser)
    val backCopy = stringResource(R.string.player_back)
    val headerFallback = stringResource(R.string.embed_page_title)

    // Back leaves the page's own history first: a provider page that navigated to a second
    // screen must not close the whole feature on one press.
    BackHandler {
        val full = customView
        when {
            full != null -> {
                exitCustomView?.invoke()
                customView = null
            }
            webView?.canGoBack() == true -> webView?.goBack()
            else -> onBack()
        }
    }

    // A WebView keeps a renderer process and a native handle alive after the composable is gone.
    DisposableEffect(Unit) {
        onDispose {
            webView?.let { view ->
                (view.parent as? ViewGroup)?.removeView(view)
                view.stopLoading()
                view.destroy()
            }
            webView = null
        }
    }

    Box(modifier = modifier.fillMaxSize()) {
        Scaffold(
            modifier = Modifier.fillMaxSize(),
            topBar = {
                TopAppBar(
                    title = {
                        Text(
                            text = viewModel.title.ifBlank { headerFallback },
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    },
                    navigationIcon = {
                        IconButton(onClick = onBack) {
                            Icon(Icons.Default.ArrowBack, contentDescription = backCopy)
                        }
                    },
                    actions = {
                        // Our own redirector only — see the class note. A page that is still
                        // resolving has no address to hand over yet.
                        val target = (page as? EmbedPage.Ready)?.url
                        IconButton(
                            enabled = target != null,
                            onClick = { target?.let { openInExternalBrowser(context, it) } },
                        ) {
                            Icon(Icons.Default.OpenInNew, contentDescription = openCopy)
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = MaterialTheme.colorScheme.surface,
                        titleContentColor = MaterialTheme.colorScheme.onSurface,
                    ),
                )
            },
        ) { padding ->
            Column(
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize(),
            ) {
                when (val state = page) {
                    is EmbedPage.Resolving -> StatusPanel(
                        headline = loadingCopy,
                        detail = noticeCopy,
                    )

                    is EmbedPage.Refused -> StatusPanel(
                        headline = state.reason,
                        detail = noticeCopy,
                        actionLabel = retryCopy,
                        onAction = viewModel::resolve,
                    )

                    is EmbedPage.Ready -> {
                        if (progress in 1..99) {
                            LinearProgressIndicator(
                                progress = { progress / 100f },
                                modifier = Modifier.fillMaxWidth(),
                            )
                        }
                        blockedScheme?.let { scheme ->
                            Text(
                                text = stringResource(R.string.embed_blocked_scheme, scheme),
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.error,
                                modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                            )
                        }
                        loadFailure?.let { reason ->
                            Column(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 16.dp, vertical = 6.dp),
                            ) {
                                val line = if (reason.isBlank()) {
                                    stringResource(R.string.embed_load_failed_unknown)
                                } else {
                                    stringResource(R.string.embed_load_failed, reason)
                                }
                                Text(
                                    text = line,
                                    style = MaterialTheme.typography.labelMedium,
                                    color = MaterialTheme.colorScheme.error,
                                )
                                OutlinedButton(
                                    onClick = {
                                        loadFailure = null
                                        loadedUrl = null
                                    },
                                ) {
                                    Text(retryCopy)
                                }
                            }
                        }
                        AndroidView(
                            modifier = Modifier
                                .fillMaxWidth()
                                .weight(1f),
                            factory = { ctx ->
                                WebView(ctx).apply {
                                    configureAsProviderView()
                                    webViewClient = providerWebViewClient(
                                        onProgress = { progress = it },
                                        onFail = { reason ->
                                            loadFailure = reason?.trim().orEmpty()
                                        },
                                        onBlocked = { scheme -> blockedScheme = scheme },
                                    )
                                    webChromeClient = providerChromeClient(
                                        onProgress = { progress = it },
                                        onShowCustom = { view, callback ->
                                            exitCustomView = { callback.onCustomViewHidden() }
                                            customView = view
                                        },
                                        onHideCustom = {
                                            customView = null
                                            exitCustomView = null
                                        },
                                    )
                                }.also { webView = it }
                            },
                            update = { view ->
                                val target = state.url
                                if (loadedUrl != target) {
                                    loadedUrl = target
                                    loadFailure = null
                                    blockedScheme = null
                                    view.loadUrl(target)
                                }
                            },
                        )
                    }
                }
            }
        }

        // HTML5 fullscreen is a provider player's own control: give it the whole window, over the
        // app bar, or the player draws its cinema inside a letterbox of our making.
        val full = customView
        if (full != null) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(MaterialTheme.colorScheme.background),
            ) {
                AndroidView(
                    modifier = Modifier.fillMaxSize(),
                    factory = {
                        (full.parent as? ViewGroup)?.removeView(full)
                        full
                    },
                )
            }
        }
    }
}

/**
 * A WebView configured to show one page and nothing else.
 *
 * `javaScriptEnabled` is what the page needs and what this screen exists for: the provider's own
 * player runs, visibly. Everything else a page does not need to do the job is switched off — no
 * file or content access, no window a page opens by itself (a pop-up would leave this screen with
 * no back path), and no interface exposed to the page at all.
 * `mediaPlaybackRequiresUserGesture = false` is the one allowance made in the player's favour: the
 * viewer pressed Play to get here, and a second tap demanded by a page we did not write is our
 * friction, not theirs.
 */
private fun WebView.configureAsProviderView() {
    settings.apply {
        javaScriptEnabled = true
        domStorageEnabled = true
        allowFileAccess = false
        allowContentAccess = false
        javaScriptCanOpenWindowsAutomatically = false
        setSupportMultipleWindows(false)
        mediaPlaybackRequiresUserGesture = false
        loadsImagesAutomatically = true
        cacheMode = WebSettings.LOAD_DEFAULT
    }
}

/**
 * The navigation policy, which is one sentence: the web, or nothing.
 *
 * `shouldOverrideUrlLoading` refuses a scheme this app has no business opening (`intent:`,
 * `market:`, `sms:`, a `file:` path a page invented). It is NOT a sniffer — it reads the scheme
 * of a navigation the WebView was already about to make, decides whether to let the WebView make
 * it, and never looks at a response body, a request header or a media extension. Nothing here is
 * reported to the player, and nothing is ever handed to ExoPlayer: that distinction is the whole
 * line between this screen and the interceptor this project refused to build.
 */
private fun providerWebViewClient(
    onProgress: (Int) -> Unit,
    onFail: (String?) -> Unit,
    onBlocked: (String) -> Unit,
): WebViewClient = object : WebViewClient() {
    override fun shouldOverrideUrlLoading(
        view: WebView?,
        request: WebResourceRequest?,
    ): Boolean {
        val scheme = request?.url?.scheme?.lowercase(Locale.ROOT)
        return if (scheme == "http" || scheme == "https" || scheme == "about") {
            false
        } else {
            onBlocked(scheme ?: "non-web")
            true
        }
    }

    @Suppress("DEPRECATION")
    override fun onReceivedError(
        view: WebView?,
        errorCode: Int,
        description: String?,
        failingUrl: String?,
    ) {
        // `failingUrl` is never read: it can name a hoster, and this screen has no business
        // displaying that. The behaviour word is the whole message. This overload is also the only
        // main-frame error callback that reaches API 21 and 22; on newer levels the framework
        // routes the newer one here through the base class.
        onFail(description)
    }

    override fun onPageFinished(view: WebView?, url: String?) {
        onProgress(100)
    }
}

/** The player's own fullscreen request, plus a flat refusal of anything it could ask for. */
private fun providerChromeClient(
    onProgress: (Int) -> Unit,
    onShowCustom: (View, WebChromeClient.CustomViewCallback) -> Unit,
    onHideCustom: () -> Unit,
): WebChromeClient = object : WebChromeClient() {
    override fun onProgressChanged(view: WebView?, newProgress: Int) {
        onProgress(newProgress)
    }

    override fun onShowCustomView(view: View, callback: CustomViewCallback) {
        onShowCustom(view, callback)
    }

    override fun onHideCustomView() {
        onHideCustom()
    }

    override fun onPermissionRequest(request: PermissionRequest?) {
        // No camera, no microphone, no media keys: this product has no feature that needs them,
        // and a page cannot be allowed to decide otherwise.
        request?.deny()
    }
}

@Composable
private fun StatusPanel(
    headline: String,
    detail: String,
    actionLabel: String? = null,
    onAction: (() -> Unit)? = null,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(
            imageVector = Icons.Default.Refresh,
            contentDescription = null,
            modifier = Modifier.size(40.dp),
            tint = MaterialTheme.colorScheme.primary,
        )
        Spacer(modifier = Modifier.height(16.dp))
        Text(
            text = headline,
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onBackground,
            textAlign = TextAlign.Center,
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = detail,
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.widthIn(max = 320.dp),
        )
        if (actionLabel != null && onAction != null) {
            Spacer(modifier = Modifier.height(20.dp))
            Button(onClick = onAction) {
                Text(actionLabel)
            }
        }
    }
}

/**
 * Hand OUR OWN redirector to the browser the viewer already trusts. Never call this with
 * `webView.url`: the same-origin rule that guards every other hand-off in the app applies here
 * too, and a browser intent carrying an address we did not build is exactly what that rule
 * exists to stop.
 */
private fun openInExternalBrowser(context: Context, ourRedirector: String) {
    val intent = Intent(Intent.ACTION_VIEW, Uri.parse(ourRedirector))
    try {
        context.startActivity(intent)
    } catch (_: ActivityNotFoundException) {
        // No browser on the device: the in-app page is still on screen, which is the answer.
    } catch (_: SecurityException) {
        // A managed profile that refuses the hand-off must not crash the screen holding it.
    }
}
