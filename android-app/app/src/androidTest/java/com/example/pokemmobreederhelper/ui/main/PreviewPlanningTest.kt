package com.example.pokemmobreederhelper.ui.main

import android.app.Application
import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.core.app.ApplicationProvider
import com.example.pokemmobreederhelper.data.*
import java.io.File
import kotlinx.serialization.encodeToString
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class PreviewPlanningTest {
  @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()
  private val request = PlanRequest("伊布", ivs = listOf("31", "31", "31", "X", "X", "X"), allowDitto = false)
  private val inventory = listOf(
    MonsterRecord(id = "preview-mother", species = "伊布", gender = "F", ivs = listOf(31,31,null,null,null,null)),
    MonsterRecord(id = "preview-father", species = "伊布", gender = "M", ivs = listOf(null,31,31,null,null,null)),
  )
  private fun application(): Application {
    val base = ApplicationProvider.getApplicationContext<Application>()
    val directory = File(base.cacheDir, "preview-${System.nanoTime()}").also { it.mkdirs() }
    return object : Application() {
      init { attachBaseContext(base) }
      override fun getApplicationContext(): Context = this
      override fun getFilesDir(): File = directory
    }
  }
  private fun awaitPlan(vm: MainScreenViewModel) {
    rule.waitUntil(120_000) { !vm.uiState.value.isPlanning }
    assertEquals("", vm.uiState.value.error)
    assertNotNull(vm.uiState.value.pendingResponse?.plan)
  }

  @Test fun firstSuggestionShowsMapAndMaterialsBeforeActivation() {
    val app = application()
    InventoryRepository(app).replace(WorkspaceSnapshot(inventory))
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread {
      vm = MainScreenViewModel(app)
      vm.selectTab(MainTab.Planner)
      vm.setSpeciesQuery("伊布")
      repeat(3) { vm.setIv(it, "31") }
      vm.setAllowDitto(false)
      vm.generatePlan()
    }
    rule.setContent { MainScreen(viewModel = vm) }
    awaitPlan(vm)
    assertNull(InventoryRepository(app).loadPlanSession())
    rule.onNode(hasScrollAction()).performScrollToNode(hasContentDescription("孵蛋路线思维导图", substring = true))
    rule.onNodeWithContentDescription("孵蛋路线思维导图", substring = true).assertIsDisplayed()
    rule.onNode(hasScrollAction()).performScrollToNode(hasText("本轮素材 · 2 只"))
    rule.onNodeWithText("本轮素材 · 2 只").performClick()
    rule.onNode(hasScrollAction()).performScrollToNode(hasText("本轮禁用并重算"))
    rule.onAllNodesWithText("本轮禁用并重算")[0].performScrollTo().performClick()
    awaitPlan(vm)
    assertEquals(1, vm.uiState.value.previewRequest!!.excludedIds.size)
    assertEquals(inventory, InventoryRepository(app).inventory.value)
    assertNull(InventoryRepository(app).loadPlanSession())
    rule.onNodeWithText("恢复全部并重算").performScrollTo().assertIsDisplayed()
    rule.runOnUiThread { vm.toggleStep(vm.uiState.value.pendingResponse!!.plan!!.steps.first()) }
    assertNull(vm.uiState.value.pendingStep)
  }

  @Test fun exclusionsAccumulateWithoutChangingActiveRouteAndCanBeRestored() {
    val app = application()
    val active = PlannerBridge(app).generatePlan(AppJson.codec.encodeToString(inventory), request)
    assertTrue(active.ok)
    InventoryRepository(app).replace(WorkspaceSnapshot(inventory, SavedPlanSession(active, request = request)))
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread { vm = MainScreenViewModel(app); vm.suggestNext() }
    awaitPlan(vm)
    for (material in inventory) {
      rule.runOnUiThread { vm.excludePreviewMaterial(material.id) }
      awaitPlan(vm)
    }
    assertEquals(inventory.map { it.id }.toSet(), vm.uiState.value.previewRequest!!.excludedIds)
    val pending = vm.uiState.value.pendingResponse!!
    assertTrue(pending.plan!!.steps.none { it.parentAId in inventory.map { m -> m.id } || it.parentBId in inventory.map { m -> m.id } })
    assertEquals(active, InventoryRepository(app).loadPlanSession()!!.response)
    assertEquals(inventory, InventoryRepository(app).inventory.value)
    rule.runOnUiThread { vm.showSuggestion(false) }
    assertFalse(vm.uiState.value.showingSuggestion)
    assertEquals(pending, vm.uiState.value.pendingResponse)
    rule.runOnUiThread { vm.showSuggestion(true); vm.restorePreviewMaterials() }
    awaitPlan(vm)
    assertTrue(vm.uiState.value.previewRequest!!.excludedIds.isEmpty())
    rule.runOnUiThread { vm.excludePreviewMaterial(inventory.first().id) }
    awaitPlan(vm)
    rule.runOnUiThread { vm.activateSuggestion() }
    val restored = InventoryRepository(app).loadPlanSession()!!.response
    assertEquals(setOf(inventory.first().id), restored.plan!!.planningOptions!!.excludedIds)
    assertFalse(vm.uiState.value.showingSuggestion)
    assertNull(vm.uiState.value.pendingResponse)
    assertEquals(inventory, InventoryRepository(app).inventory.value)
  }
}
