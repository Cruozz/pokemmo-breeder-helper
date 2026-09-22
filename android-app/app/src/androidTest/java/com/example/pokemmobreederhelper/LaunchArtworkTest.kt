package com.example.pokemmobreederhelper

import android.graphics.Bitmap
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.example.pokemmobreederhelper.theme.PokeMMOBreederHelperTheme
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import java.io.File

class LaunchArtworkTest {
  @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

  @Test fun artworkAndSloganAreVisibleAndTappable() {
    var continued = false
    rule.setContent { PokeMMOBreederHelperTheme { LaunchArtwork { continued = true } } }
    rule.onNodeWithContentDescription("孵蛋助手开屏画面").assertIsDisplayed()
    rule.onNodeWithText("让孵蛋更简单").assertIsDisplayed()
    rule.waitForIdle()
    val screenshot = InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()
    assertNotNull(screenshot)
    File(rule.activity.getExternalFilesDir(null), "qa-launch.png").outputStream().use {
      screenshot.compress(Bitmap.CompressFormat.PNG, 100, it)
    }
    screenshot.recycle()
    rule.onNodeWithText("让孵蛋更简单").performClick()
    assertTrue(continued)
  }
}
