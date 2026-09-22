package com.example.pokemmobreederhelper

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.example.pokemmobreederhelper.theme.PokeMMOBreederHelperTheme
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import kotlinx.coroutines.delay

class MainActivity : ComponentActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)

    enableEdgeToEdge()
    setContent {
      var showArtwork by rememberSaveable { mutableStateOf(savedInstanceState == null) }
      LaunchedEffect(Unit) { delay(1000); showArtwork = false }
      PokeMMOBreederHelperTheme {
        Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
          if (showArtwork) LaunchArtwork { showArtwork = false } else MainNavigation()
        }
      }
    }
  }
}
