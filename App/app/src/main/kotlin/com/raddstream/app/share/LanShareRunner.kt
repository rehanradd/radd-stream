package com.raddstream.app.share

import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.data.cache.CacheFileDao
import com.raddstream.app.di.CacheScope
import java.net.NetworkInterface
import java.util.Collections
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The single owner of the LAN share socket's process lifecycle — the share-feature mirror of
 * [com.raddstream.app.data.cache.CacheEngineRunner]. The Application starts it once; from then on it
 * owns exactly one [LanShareServer] and reacts to the persisted `share over LAN` preference flipping
 * on and off. Nothing else may bind this port, and no Composable starts a socket: the honest model is
 * one class the Application owns, driven by the DataStore the Settings ViewModel already writes.
 *
 * How the toggle reaches the server: the Settings ViewModel saves the boolean through
 * [ServerSettingsRepository]; this runner collects that flow together with the operator's
 * `sharing` switch and calls [enable]/[disable]. The UI never touches the socket, and the socket
 * never reads the UI — the two persisted switches are the only channel.
 *
 * Why the catalog is a snapshot refreshed on the app's clock rather than queried per request: the
 * server's `catalogProvider` is a plain (non-suspend) function, and Room reads are suspend. So we
 * periodically rebuild the servable set here (off the main thread, from the engine's committed-file
 * listing) and hand the server an immutable snapshot. The set stays fixed by our own catalog — a
 * request can still only ever select a token this listing produced.
 */
@Singleton
class LanShareRunner @Inject constructor(
    private val settings: ServerSettingsRepository,
    private val fileDao: CacheFileDao,
    @CacheScope private val scope: CoroutineScope,
) {

    private val started = AtomicBoolean(false)
    private val catalog = AtomicReference<Map<String, ShareTarget>>(emptyMap())

    private var server: LanShareServer? = null
    private var refreshJob: Job? = null

    private val _status = MutableStateFlow<LanShareStatus>(LanShareStatus.Off)
    val status: StateFlow<LanShareStatus> = _status.asStateFlow()

    /** Idempotent: begins observing the share preference. Never binds unless that preference is on. */
    fun start() {
        if (!started.compareAndSet(false, true)) return
        scope.launch {
            // Two switches, one socket: the viewer's own row ANDs with the operator's
            // `feature_flags.sharing`, because a viewer toggle that outranks the server's board
            // would make the operator's switch decorative. Either one off means nothing is served;
            // collecting both as one flow also means a remote-config refresh can close a socket
            // that a viewer opened minutes earlier, without waiting for them to touch the row.
            combine(settings.lanShareEnabled, settings.sharingFeatureEnabled) { wanted, allowed ->
                shouldServe(wanted, allowed)
            }.collect { serve ->
                if (serve) enable() else disable()
            }
        }
    }

    // enable/disable are driven by a single sequential preference collector, so they can never
    // overlap; the mutable socket/job fields are only ever touched from that one coroutine.
    private suspend fun enable() {
        if (server != null) return
        val initial = refreshCatalog()
        catalog.set(initial)
        val srv = LanShareServer(
            sharingEnabled = true,
            port = LanShareServer.DEFAULT_PORT,
            catalogProvider = { catalog.get() },
        )
        val port = srv.start()
        if (port == null) {
            runCatching { srv.close() }
            catalog.set(emptyMap())
            _status.value = LanShareStatus.Failed
            return
        }
        server = srv
        _status.value = LanShareStatus.Listening(
            port = port,
            address = ShareCatalog.firstSiteLocalIpv4(privateIpv4Candidates()),
            servableCount = initial.size,
        )
        refreshJob = scope.launch {
            while (isActive) {
                delay(REFRESH_MILLIS)
                val snapshot = refreshCatalog()
                catalog.set(snapshot)
                (_status.value as? LanShareStatus.Listening)?.let {
                    _status.value = it.copy(servableCount = snapshot.size)
                }
            }
        }
    }

    @Synchronized
    private fun disable() {
        refreshJob?.cancel()
        refreshJob = null
        server?.let { runCatching { it.stop() } }
        server = null
        catalog.set(emptyMap())
        _status.value = LanShareStatus.Off
    }

    /** Read the engine's committed-file listing off the main thread; a failed read shares nothing. */
    private suspend fun refreshCatalog(): Map<String, ShareTarget> =
        withContext(Dispatchers.IO) {
            runCatching { ShareCatalog.fromCommittedFiles(fileDao.listLive()) }
                .getOrDefault(emptyMap())
        }

    /** The device's own IPv4 addresses as dotted-quad strings — never a media or upstream address. */
    private suspend fun privateIpv4Candidates(): List<String> =
        withContext(Dispatchers.IO) {
            runCatching {
                Collections.list(NetworkInterface.getNetworkInterfaces())
                    .flatMap { iface ->
                        runCatching { Collections.list(iface.inetAddresses) }
                            .getOrDefault(emptyList())
                    }
                    .mapNotNull { it.hostAddress }
            }.getOrDefault(emptyList())
        }

    companion object {
        private const val REFRESH_MILLIS = 15_000L

        /**
         * Whether the socket may serve: the viewer's row ANDs with the operator's board.
         *
         * Pure, because this is the whole policy and it is the kind of rule that gets quietly
         * inverted by whoever wires the next switch — either input off must mean nothing served.
         */
        fun shouldServe(wantedByViewer: Boolean, allowedByOperator: Boolean): Boolean =
            wantedByViewer && allowedByOperator
    }
}
