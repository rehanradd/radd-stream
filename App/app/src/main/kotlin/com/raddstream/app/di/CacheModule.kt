package com.raddstream.app.di

import android.content.Context
import com.raddstream.app.brand.Brand
import com.raddstream.app.data.cache.AndroidStorageGate
import com.raddstream.app.data.cache.AndroidUptimeClock
import com.raddstream.app.data.cache.AheadExecutor
import com.raddstream.app.data.cache.AheadFetcher
import com.raddstream.app.data.cache.ByteRangeManifestDao
import com.raddstream.app.data.cache.CacheCoordinator
import com.raddstream.app.data.cache.CacheFileDao
import com.raddstream.app.data.cache.CacheTaskDao
import com.raddstream.app.data.cache.ConnectivityProbe
import com.raddstream.app.data.cache.HlsAheadBuffer
import com.raddstream.app.data.cache.KeepSourceFactory
import com.raddstream.app.data.cache.KeepTtlHolder
import com.raddstream.app.data.cache.NetworkClass
import com.raddstream.app.data.cache.RangeByteFetcher
import com.raddstream.app.data.cache.RedirectorSourceResolver
import com.raddstream.app.data.cache.SchedulerPolicy
import com.raddstream.app.data.cache.SourceResolver
import com.raddstream.app.data.cache.StorageGate
import com.raddstream.app.data.cache.TtlHours
import com.raddstream.app.data.cache.UptimeClock
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import java.util.concurrent.TimeUnit
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import okhttp3.OkHttpClient

/**
 * Builds the offline cache engine the rest of the app never had: the [CacheCoordinator] and every
 * collaborator it needs, wired to the real Room DAOs, a redirector-backed [SourceResolver], the
 * Android storage gate, the app's network layer, and a single application-lifetime [CoroutineScope].
 *
 * Nothing here invents policy: the state machine, scheduler, TTL and eviction classes are the ones
 * already unit-tested in the cache package. This module only supplies their Android/Room/OkHttp
 * implementations so the engine actually runs instead of sitting unwired.
 *
 * THE HARD RULE THIS MODULE UPHOLDS: the only network address it ever hands the engine is our own
 * redirector (`/api/v1/stream?id=<handle>`), produced by [RedirectorSourceResolver] from an opaque
 * handle. No upstream hoster URL is constructed, stored, or returned anywhere in this graph.
 */
@Module
@InstallIn(SingletonComponent::class)
object CacheModule {

    /**
     * A dedicated client for bulk byte transfer: redirects are followed (the redirector answers a
     * 302 to the bytes), and read timeout is long so a multi-gigabyte range pull is not aborted.
     * No logging interceptor is installed, matching [com.raddstream.app.network.ApiProvider] — a
     * media URL is a bearer token and must never reach a log.
     */
    @Provides
    @Singleton
    fun provideCacheOkHttpClient(): OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(120, TimeUnit.SECONDS)
        .followRedirects(true)
        .followSslRedirects(true)
        .retryOnConnectionFailure(true)
        .build()

    @Provides
    @Singleton
    fun provideUptimeClock(): UptimeClock = AndroidUptimeClock()

    @Provides
    @Singleton
    fun provideStorageGate(
        @ApplicationContext context: Context,
        fileDao: CacheFileDao,
        clock: UptimeClock,
    ): StorageGate = AndroidStorageGate(
        context = context,
        fileDao = fileDao,
        clock = clock,
        ceilingBytes = Brand.offlineMaxBytes,
        lowStorageFloorBytes = Brand.lowSpaceWarningBytes,
        perFileMaxBytes = Brand.perFileMaxBytes,
    )

    /**
     * The auto-preview retention window the sweep applies to ephemeral keeps, straight from
     * [KeepTtlHolder] — i.e. from the same DataStore key the Settings screen's 3 h / 6 h control
     * writes. This used to be a hardcoded `TtlHours.SIX`, which is precisely why that control did
     * nothing.
     *
     * DELIBERATELY NOT `@Singleton`: the value changes while the process lives, so caching the
     * instance would freeze whichever window happened to be read first (and on a cold start that is
     * the 3-hour default, silently ignoring a saved 6). [RoomCacheSweepStore] asks through a
     * [javax.inject.Provider] once per sweep, so an unscoped binding is how the fresh value arrives —
     * and the read is a plain volatile field, so calling it off the main thread costs nothing.
     *
     * The holder itself needs no `@Provides`: it is an `@Inject`-constructed `@Singleton` that seeds
     * itself from [com.raddstream.app.RaddStreamApplication], the same way
     * [com.raddstream.app.share.LanShareRunner] is started.
     */
    @Provides
    fun provideTtlHours(holder: KeepTtlHolder): TtlHours = holder.ttlHours()

    @Provides
    @Singleton
    fun provideRangeByteFetcher(client: OkHttpClient): RangeByteFetcher = RangeByteFetcher(client)

    @Provides
    @Singleton
    fun provideHlsAheadBuffer(client: OkHttpClient, clock: UptimeClock): HlsAheadBuffer =
        HlsAheadBuffer(client, clock)

    @Provides
    @Singleton
    fun provideAheadExecutor(
        fetcher: RangeByteFetcher,
        taskDao: CacheTaskDao,
        manifestDao: ByteRangeManifestDao,
        fileDao: CacheFileDao,
        storage: StorageGate,
        clock: UptimeClock,
    ): AheadExecutor = AheadFetcher(
        fetcher = fetcher,
        taskDao = taskDao,
        manifestDao = manifestDao,
        fileDao = fileDao,
        storage = storage,
        clock = clock,
        maxBytesPerPass = Brand.aheadFetchMaxBytesPerPass,
    )

    @Provides
    @Singleton
    fun provideSchedulerPolicy(): SchedulerPolicy = SchedulerPolicy(
        maxConcurrent = 2,
        allowAutoPreviewOnMobile = false,
    )

    @Provides
    @Singleton
    @CacheScope
    fun provideCacheScope(): CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    @Provides
    @Singleton
    fun provideNetworkClassProvider(probe: ConnectivityProbe): () -> NetworkClass = { probe.current() }

    @Provides
    @Singleton
    fun provideSourceResolver(resolver: RedirectorSourceResolver): SourceResolver = resolver

    @Provides
    @Singleton
    fun provideKeepSourceFactory(resolver: RedirectorSourceResolver): KeepSourceFactory = resolver

    @Provides
    @Singleton
    fun provideCacheCoordinator(
        @CacheScope scope: CoroutineScope,
        taskDao: CacheTaskDao,
        manifestDao: ByteRangeManifestDao,
        fileDao: CacheFileDao,
        aheadExecutor: AheadExecutor,
        rangeFetcher: RangeByteFetcher,
        hlsBuffer: HlsAheadBuffer,
        storage: StorageGate,
        resolver: SourceResolver,
        clock: UptimeClock,
        policy: SchedulerPolicy,
        networkProvider: @JvmSuppressWildcards () -> NetworkClass,
    ): CacheCoordinator = CacheCoordinator(
        scope = scope,
        taskDao = taskDao,
        manifestDao = manifestDao,
        fileDao = fileDao,
        aheadFetcher = aheadExecutor,
        rangeFetcher = rangeFetcher,
        hlsBuffer = hlsBuffer,
        storage = storage,
        resolver = resolver,
        clock = clock,
        policy = policy,
        networkProvider = networkProvider,
    )
}
