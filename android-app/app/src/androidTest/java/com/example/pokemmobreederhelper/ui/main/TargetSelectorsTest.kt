package com.example.pokemmobreederhelper.ui.main

import androidx.activity.ComponentActivity
import androidx.compose.runtime.*
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import com.example.pokemmobreederhelper.theme.PokeMMOBreederHelperTheme
import com.example.pokemmobreederhelper.data.PlanRequest
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class TargetSelectorsTest {
  @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

  @Test fun typingFullNatureAndConfirmingDoesNotClearIt() {
    var selected = ""
    rule.setContent { PokeMMOBreederHelperTheme { NatureSelectionDialog("", {}, { selected = it }) } }
    rule.onNodeWithTag("nature-search").performTextInput("天真")
    rule.onNodeWithText("确定").performClick()
    assertEquals("天真", selected)
    rule.onNodeWithTag("nature-search").assertTextContains("天真")
  }

  @Test fun partialSearchAndOptionTapChooseNaive() {
    var selected = ""
    rule.setContent { PokeMMOBreederHelperTheme { NatureSelectionDialog("", {}, { selected = it }) } }
    rule.onNodeWithTag("nature-search").performTextInput("天")
    rule.onNodeWithText("天真").performClick()
    assertEquals("天真", selected)
  }

  @Test fun confirmingWithoutEditsPreservesCurrentNature() {
    var selected = ""
    rule.setContent { PokeMMOBreederHelperTheme { NatureSelectionDialog("天真", {}, { selected = it }) } }
    rule.onNodeWithText("确定").performClick()
    assertEquals("天真", selected)
  }

  @Test fun allNaturesAvailableAndIvDropdownHasOnlyThreeChoices() {
    assertEquals(27, natureOptions.size)
    assertEquals(listOf("", "固执", "内敛", "爽朗", "胆小"), natureOptions.take(5).map { it.value })
    assertEquals(List(6) { "X" }, MainScreenUiState().ivs)
    assertEquals(List(6) { "X" }, PlanRequest("索罗亚").ivs)
    var current by mutableStateOf("X")
    rule.setContent { PokeMMOBreederHelperTheme { IvSelector("攻击", current, { current = it }) } }
    rule.onNodeWithTag("iv-攻击").performClick()
    rule.onNodeWithText("31").performClick()
    assertEquals("31", current)
    rule.onNodeWithTag("iv-攻击").performClick()
    rule.onNodeWithText("0").performClick()
    assertEquals("0", current)
    rule.onNodeWithTag("iv-攻击").performClick()
    rule.onNodeWithText("X").performClick()
    assertEquals("X", current)
  }
}
