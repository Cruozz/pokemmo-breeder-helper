package com.example.pokemmobreederhelper.ui.main

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** UI tests for [com.example.pokemmobreederhelper.ui.main.MainScreen]. */
class MainScreenTest {

  @get:Rule val composeTestRule = createAndroidComposeRule<ComponentActivity>()

  @Before
  fun setup() {
    composeTestRule.activity.filesDir.resolve("plan-session.json").delete()
    composeTestRule.activity.filesDir.resolve("inventory.json").delete()
    composeTestRule.activity.filesDir.resolve("workspace-v2.json").delete()
    composeTestRule.activity.filesDir.resolve("workspace-v2.json.bak").delete()
    composeTestRule.setContent { MainScreen() }
  }

  @Test
  fun primaryTabs_exist() {
    composeTestRule.onNodeWithText("孵蛋规划").assertExists()
    composeTestRule.onNodeWithText("素材库存 0").assertExists()
  }

  @Test
  fun planner_usesCompactIvGridAndExpandableAdvancedRules() {
    composeTestRule.onNodeWithText("孵蛋规划").performClick()

    composeTestRule.onNodeWithText("目标个体值").performScrollTo().assertIsDisplayed()
    composeTestRule.onNodeWithText("HP").assertExists()
    composeTestRule.onNodeWithText("速度").assertExists()
    composeTestRule.onNodeWithText("高级规则").performScrollTo().assertIsDisplayed()
    composeTestRule.onNodeWithText("展开").performScrollTo().performClick()
    composeTestRule.onNodeWithText("孵化头目成品").assertExists()
    composeTestRule.onNodeWithText("允许使用百变怪").assertExists()
  }
}
