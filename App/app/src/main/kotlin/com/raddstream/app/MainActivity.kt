package com.raddstream.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import com.raddstream.app.data.ServerSettingsRepository
import com.raddstream.app.ui.navigation.Screen
import com.raddstream.app.ui.navigation.RaddStreamNavGraph
import com.raddstream.app.ui.theme.RaddStreamTheme
import com.raddstream.app.ui.theme.BackgroundDark
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import kotlinx.coroutines.flow.first

/**
 * Single-activity host.
 * Routes first-time users to server setup and returning users to the catalog.
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject
    lateinit var serverSettingsRepository: ServerSettingsRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            RaddStreamTheme {
                var startDestination by remember { mutableStateOf<String?>(null) }
                LaunchedEffect(Unit) {
                    val savedUrl = try {
                        serverSettingsRepository.serverUrl.first()
                    } catch (_: Exception) {
                        null
                    }
                    startDestination = if (savedUrl.isNullOrBlank()) {
                        Screen.Setup.route
                    } else {
                        Screen.Home.route
                    }
                }

                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = BackgroundDark,
                ) {
                    val destination = startDestination
                    if (destination == null) {
                        Box(
                            modifier = Modifier.fillMaxSize(),
                            contentAlignment = Alignment.Center,
                        ) {
                            CircularProgressIndicator()
                        }
                    } else {
                        RaddStreamNavGraph(startDestination = destination)
                    }
                }
            }
        }
    }
}
