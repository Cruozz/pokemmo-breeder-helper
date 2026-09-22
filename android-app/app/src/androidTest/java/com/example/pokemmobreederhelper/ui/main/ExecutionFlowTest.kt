package com.example.pokemmobreederhelper.ui.main

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.core.app.ApplicationProvider
import android.content.Context
import com.example.pokemmobreederhelper.data.*
import com.example.pokemmobreederhelper.theme.PokeMMOBreederHelperTheme
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class ExecutionFlowTest {
  @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

  @Test fun confirmationRequiresOutcomeAndCancelDoesNotComplete() {
    var calls = 0
    val step = ExecutionStepRecord(1, "a", "b", child = MonsterRecord(id = "child", species = "索罗亚"),
      genderPolicy = "random", shouldCheckNature = true)
    rule.setContent { PokeMMOBreederHelperTheme {
      CompletionDialog(step, "固执", { }, { _, _ -> calls++ }, { })
    } }
    rule.onNodeWithText("确认已孵完").assertIsNotEnabled()
    rule.onNodeWithText("母").performScrollTo().performClick()
    rule.onNodeWithText("确认已孵完").assertIsNotEnabled()
    rule.onNodeWithText("没有爆性格").performScrollTo().performClick()
    rule.onNodeWithText("确认已孵完").assertIsEnabled()
    rule.onNodeWithText("取消").performClick()
    assertEquals(0, calls)
    rule.onNodeWithText("确认已孵完").performClick()
    assertEquals(1, calls)
  }

  @Test fun dittoMateDoesNotAskGender() {
    val step = ExecutionStepRecord(1, "a", "buy:ditto", child = MonsterRecord(id = "child"), genderPolicy = "irrelevant")
    rule.setContent { PokeMMOBreederHelperTheme { CompletionDialog(step, "", {}, { _, _ -> }, {}) } }
    rule.onNodeWithText("实际孵出的性别（必选）").assertDoesNotExist()
    rule.onNodeWithText("确认已孵完").assertIsEnabled()
  }

  @Test fun atomicWorkspaceSurvivesRestartAndUndoRestoresInventoryAndPlan() {
    val base = ApplicationProvider.getApplicationContext<Context>()
    val isolated = object : android.content.ContextWrapper(base) {
      override fun getFilesDir() = java.io.File(base.cacheDir, "workspace-test-${System.nanoTime()}").also { it.mkdirs() }
    }
    // A stable directory for the three repository instances below.
    val folder = isolated.filesDir
    val context = object : android.content.ContextWrapper(base) { override fun getFilesDir() = folder }
    val repository = InventoryRepository(context)
    val parent = MonsterRecord(id = "parent", species = "索罗亚")
    val before = WorkspaceSnapshot(listOf(parent), SavedPlanSession(PlannerResponse(ok = true)))
    repository.replace(before)
    repository.replace(WorkspaceSnapshot(emptyList(), null))
    val restarted = InventoryRepository(context)
    assertTrue(restarted.inventory.value.isEmpty())
    assertTrue(restarted.undo())
    val restored = InventoryRepository(context)
    assertEquals(listOf(parent), restored.inventory.value)
    assertEquals(before.session, restored.loadPlanSession())
    assertTrue(folder.resolve("workspace-v2.json").exists())
  }

  @Test fun packagedPlannerAndCompletionUse022Rules() {
    val bridge = PlannerBridge(ApplicationProvider.getApplicationContext())
    var response = bridge.generatePlan("[]", PlanRequest("索罗亚克", ivs = listOf("31", "31", "31", "X", "X", "X"), allowDitto = false))
    assertTrue(response.ok)
    assertEquals("0.2.8", response.rulesVersion)
    var inventory = "[]"
    val originalId = response.plan!!.id
    val steps = response.plan!!.steps
    for (step in steps) {
      val completed = bridge.completeStep(inventory, response, StepOutcome(step.number, step.plannedGender))
      assertTrue(completed.error, completed.ok)
      response = completed.response!!
      inventory = AppJson.codec.encodeToString(kotlinx.serialization.builtins.ListSerializer(MonsterRecord.serializer()), completed.inventory)
      assertEquals(originalId, response.plan!!.id)
      assertFalse(response.plan!!.needsReplan)
    }
    assertEquals("[]", inventory)
    assertTrue(response.plan!!.steps.all { it.completed })
  }
}
