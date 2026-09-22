package com.example.pokemmobreederhelper.ui.main

import android.app.Application
import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.test.core.app.ApplicationProvider
import com.example.pokemmobreederhelper.data.*
import java.io.File
import kotlinx.serialization.encodeToString
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class StagedPlanningTest {
  @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

  private val request = PlanRequest("尼多王", nature = "内敛", targetAlpha = true,
    needHiddenAbility = true, allowDitto = false, ivs = listOf("31", "X", "31", "31", "31", "31"),
    excludedIds = setOf("excluded-fixture"))

  private fun isolatedApplication(): Application {
    val base = ApplicationProvider.getApplicationContext<Application>()
    val directory = File(base.cacheDir, "staged-test-${System.nanoTime()}").also { it.mkdirs() }
    return object : Application() {
      init { attachBaseContext(base) }
      override fun getApplicationContext(): Context = this
      override fun getFilesDir(): File = directory
    }
  }

  @Test fun packagedFiveVAlphaLifecycleSurvivesSerializationAndFinishesMale() {
    val context = isolatedApplication()
    val bridge = PlannerBridge(context)
    val repository = InventoryRepository(context)
    var response = bridge.generatePlan("[]", request)
    var inventory = emptyList<MonsterRecord>()
    val phases = mutableListOf<String>()
    repeat(4) {
      assertTrue(response.error + response.report, response.ok)
      val plan = response.plan!!
      phases += plan.naturePhase
      assertEquals(5, plan.targetIvCount)
      assertEquals(5, plan.finalTarget!!.perfectIvCount)
      assertTrue(plan.steps.isNotEmpty())
      for (step in plan.steps) {
        val result = bridge.completeStep(AppJson.codec.encodeToString(inventory), response,
          StepOutcome(step.number, step.plannedGender, if (step.shouldCheckNature) false else null))
        assertTrue(result.error, result.ok)
        inventory = result.inventory
        val saved = result.response!!
        repository.replace(WorkspaceSnapshot(inventory, SavedPlanSession(saved,
          saved.plan!!.steps.filter { it.completed }.map { it.child.id }.toSet(), saved.plan!!.planningOptions)))
        response = InventoryRepository(context).loadPlanSession()!!.response
        assertEquals(plan.id, response.plan!!.id)
      }
      if (plan.naturePhase != "guarantee") {
        assertTrue(response.plan!!.needsReplan)
        assertTrue(inventory.any { it.id == plan.steps.last().child.id })
        response = bridge.generatePlan(AppJson.codec.encodeToString(inventory), response.plan!!.planningOptions!!)
        assertEquals(request.ivs, response.plan!!.planningOptions!!.ivs)
        assertEquals(request.excludedIds, response.plan!!.planningOptions!!.excludedIds)
      }
    }
    assertEquals(listOf("maternal", "gamble_upper", "gamble_lower", "guarantee"), phases)
    val final = response.plan!!.steps.last().child
    assertEquals("尼多朗", final.species)
    assertEquals("M", final.gender)
    assertEquals(5, final.perfectIvCount)
    assertEquals("内敛", final.nature)
    assertTrue(final.isAlpha && final.hasHiddenAbility)
    assertTrue(inventory.isEmpty())
    assertFalse(response.plan!!.needsReplan)
    val restarted = InventoryRepository(context)
    assertTrue(restarted.undo())
    assertFalse(restarted.loadPlanSession()!!.response.plan!!.steps.last().completed)
    assertEquals(2, restarted.inventory.value.size)
  }

  @Test fun completionAutomaticallySuggestsNextWithoutActivationAndUndoStillWorks() {
    val application = isolatedApplication()
    val mother = MonsterRecord(id = "existing-4v", species = "尼多兰", gender = "F", isAlpha = true,
      hasHiddenAbility = true, ivs = listOf(31, null, 31, 31, 31, null))
    val repository = InventoryRepository(application)
    val response = PlannerBridge(application).generatePlan(AppJson.codec.encodeToString(listOf(mother)), request)
    assertTrue(response.error, response.ok)
    repository.replace(WorkspaceSnapshot(listOf(mother), SavedPlanSession(response, request = request)))
    lateinit var model: MainScreenViewModel
    rule.runOnUiThread {
      model = MainScreenViewModel(application)
      model.selectTab(MainTab.Planner)
    }
    rule.setContent { MainScreen(viewModel = model) }
    // Unsubmitted form edits must not shrink the active 5V target on continuation.
    rule.runOnUiThread { model.setIv(5, "X") }
    val steps = response.plan!!.steps
    var beforeLast = emptyList<MonsterRecord>()
    for (step in steps) {
      beforeLast = model.uiState.value.inventory
      rule.runOnUiThread {
        model.toggleStep(step)
        model.completeStep(step.plannedGender, if (step.shouldCheckNature) false else null)
      }
      rule.waitUntil(120_000) { !model.uiState.value.isPlanning }
      assertEquals("", model.uiState.value.error)
    }
    val state = model.uiState.value
    assertEquals(response.plan!!.id, state.plannerResponse!!.plan!!.id)
    assertTrue(state.plannerResponse!!.plan!!.needsReplan)
    assertEquals("gamble_upper", state.pendingResponse!!.plan!!.naturePhase)
    assertEquals(request.ivs, state.pendingResponse!!.plan!!.planningOptions!!.ivs)
    assertEquals(request.excludedIds, state.pendingResponse!!.plan!!.planningOptions!!.excludedIds)
    assertTrue(state.inventory.any { it.id == steps.last().child.id && it.perfectIvCount == 5 })
    rule.onNodeWithText("新路线建议 · 尚未启用").performScrollTo().assertIsDisplayed()
    rule.runOnUiThread { model.undoLastAction() }
    assertEquals(beforeLast, model.uiState.value.inventory)
    assertFalse(model.uiState.value.plannerResponse!!.plan!!.steps.last().completed)
    assertNull(model.uiState.value.pendingResponse)
    rule.runOnUiThread { model.undoLastAction() }
    lateinit var restarted: MainScreenViewModel
    rule.runOnUiThread {
      restarted = MainScreenViewModel(application)
      restarted.suggestNext()
    }
    rule.waitUntil(120_000) { !restarted.uiState.value.isPlanning }
    assertEquals("gamble_upper", restarted.uiState.value.pendingResponse!!.plan!!.naturePhase)
    assertEquals(state.inventory, restarted.uiState.value.inventory)
  }

  @Test fun planningFailureIsVisibleAndKeepsWorkspace() {
    val application = isolatedApplication()
    lateinit var model: MainScreenViewModel
    rule.runOnUiThread {
      model = MainScreenViewModel(application)
      model.selectTab(MainTab.Planner)
    }
    rule.setContent { MainScreen(viewModel = model) }
    rule.runOnUiThread {
      model.setSpeciesQuery("不存在的目标-12345")
      model.generatePlan()
    }
    rule.waitUntil(120_000) { !model.uiState.value.isPlanning }
    assertNotNull(model.uiState.value.planningFailure)
    assertNull(model.uiState.value.plannerResponse)
    assertTrue(model.uiState.value.inventory.isEmpty())
    rule.onNodeWithText("本次规划未生成").performScrollTo().assertIsDisplayed()
    rule.onNodeWithText("重试本次规划").performScrollTo().assertIsDisplayed()
  }
}
