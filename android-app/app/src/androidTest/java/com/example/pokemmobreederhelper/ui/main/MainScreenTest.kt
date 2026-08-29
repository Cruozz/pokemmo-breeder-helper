package com.example.pokemmobreederhelper.ui.main

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** UI tests for [com.example.pokemmobreederhelper.ui.main.MainScreen]. */
class MainScreenTest {

  @get:Rule val composeTestRule = createAndroidComposeRule<ComponentActivity>()

  @Before
  fun setup() {
    composeTestRule.setContent { MainScreen() }
  }

  @Test
  fun primaryTabs_exist() {
    composeTestRule.onNodeWithText("孵蛋规划").assertExists()
    composeTestRule.onNodeWithText("素材库存 0").assertExists()
  }
}
