package com.raddstream.app.di

import javax.inject.Qualifier

/**
 * Marks the single long-lived application scope that owns the offline cache engine's work — the
 * scheduler ticks, the download jobs the coordinator launches, and the TTL sweep. It is deliberately
 * a distinct qualifier so it never collides with a ViewModel's own scope (those are cancelled with
 * the ViewModel; the cache work is not).
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class CacheScope
