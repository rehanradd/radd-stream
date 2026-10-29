package com.raddstream.app.di

import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.player.AdInventory
import com.raddstream.app.player.AdSwitch
import com.raddstream.app.player.AdWallClock
import com.raddstream.app.player.DataStoreAdSwitch
import com.raddstream.app.player.NoAdInventory
import com.raddstream.app.player.SystemAdWallClock
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * The two bindings an ad integration is allowed to change.
 *
 * Both are deliberately singletons and both are deliberately the *boring* implementation: the
 * cadence reads the wall clock because its stamps have to survive a reboot, and the inventory says
 * nothing can be filled because this build ships no ad SDK. Replacing the second one is what
 * turning an SDK on means — the caps in [AdCadenceLimits] stay exactly where they are, which is
 * the point of wiring the question through an interface instead of asking the network at a call
 * site.
 */
@Module
@InstallIn(SingletonComponent::class)
object AdModule {

    @Provides
    @Singleton
    fun provideAdWallClock(): AdWallClock = SystemAdWallClock()

    /**
     * The honest answer until a network is wired: no surface can be filled, so every ask ends as
     * `None` and the layouts that would host a creative stay as they are today. There is no
     * binding here that could return a placeholder, and a viewer never waits on one.
     */
    @Provides
    @Singleton
    fun provideAdInventory(): AdInventory = NoAdInventory()

    /**
     * The operator's switch, read from the DataStore mirror that
     * [com.raddstream.app.data.RemoteConfigWatcher] keeps in step with `/api/v1/app/remote-config`.
     * Bound through [AdSwitch] so the governor's every-ask read is the same fail-closed rule a JVM
     * test can drive with a boolean, rather than a DataStore dependency inside the class that
     * decides whether a viewer sees an ad.
     */
    @Provides
    @Singleton
    fun provideAdSwitch(settings: ServerSettingsRepository): AdSwitch = DataStoreAdSwitch(settings)
}
