package com.raddstream.app

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

/**
 * Application class — Hilt entry point.
 * Referenced in AndroidManifest.xml as android:name=".RaddStreamApplication"
 */
@HiltAndroidApp
class RaddStreamApplication : Application()
