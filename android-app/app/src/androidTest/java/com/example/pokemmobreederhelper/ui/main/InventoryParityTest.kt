package com.example.pokemmobreederhelper.ui.main

import android.app.Application
import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.height
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.core.app.ApplicationProvider
import com.example.pokemmobreederhelper.data.*
import com.example.pokemmobreederhelper.theme.PokeMMOBreederHelperTheme
import java.io.File
import kotlinx.serialization.encodeToString
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class InventoryParityTest {
  @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()
  private fun application(): Application {
    val base = ApplicationProvider.getApplicationContext<Application>()
    val folder = File(base.cacheDir, "inventory-parity-${System.nanoTime()}").also { it.mkdirs() }
    return object : Application() {
      init { attachBaseContext(base) }
      override fun getApplicationContext(): Context = this
      override fun getFilesDir(): File = folder
    }
  }
  private val mother = MonsterRecord(id="mother",species="伊布",gender="F",nature="固执",ivs=listOf(31,12,8,9,7,4),moves=listOf("祈愿"))
  private val father = mother.copy(id="father",gender="M",ivs=listOf(12,31,8,9,7,4))
  private fun plan(app: Application) = PlannerBridge(app).generatePlan(AppJson.codec.encodeToString(listOf(mother,father)),
    PlanRequest("伊布",ivs=listOf("31","31","X","X","X","X"),allowDitto=false))

  @Test fun editingAndDeletingUsedMaterialPausesRouteAndUndoRestoresBoth() {
    val app = application()
    val response = plan(app)
    assertTrue(response.ok)
    val repository = InventoryRepository(app)
    repository.replace(WorkspaceSnapshot(listOf(mother,father),SavedPlanSession(response)))
    repository.editInventory(listOf(mother.copy(ivs=listOf(1,2,3,4,5,6)),father))
    assertTrue(InventoryRepository(app).loadPlanSession()!!.response.plan!!.needsReplan)
    assertTrue(repository.undo())
    assertEquals(listOf(mother,father),InventoryRepository(app).inventory.value)
    assertEquals(response,InventoryRepository(app).loadPlanSession()!!.response)
    repository.editInventory(emptyList())
    assertTrue(InventoryRepository(app).inventory.value.isEmpty())
    assertTrue(InventoryRepository(app).loadPlanSession()!!.response.plan!!.needsReplan)
    repository.undo()
    assertEquals(response,InventoryRepository(app).loadPlanSession()!!.response)
  }

  @Test fun newMaterialDoesNotPauseUnrelatedRouteAndSharedDuplicateRulesWorkInApk() {
    val app = application()
    val response = plan(app)
    val repository = InventoryRepository(app)
    repository.replace(WorkspaceSnapshot(listOf(mother,father),SavedPlanSession(response)))
    repository.editInventory(listOf(mother,father,mother.copy(id="duplicate")))
    assertFalse(repository.loadPlanSession()!!.response.plan!!.needsReplan)
    val groups = PlannerBridge(app).duplicateGroups(repository.inventoryJson())
    assertEquals(listOf(setOf("mother","duplicate")),groups.map { it.toSet() })
  }

  @Test fun manualSaveValidationPersistsAndInvalidEditDoesNotOverwrite() {
    val app = application()
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread { vm = MainScreenViewModel(app); vm.editMaterial() }
    val draft = vm.uiState.value.editingMaterial!!.copy(species="eevee",gender="F",ivs=mother.ivs,moves=mother.moves)
    rule.runOnUiThread { vm.saveMaterial(draft) }
    rule.waitUntil(30_000) { !vm.uiState.value.isPlanning }
    assertEquals("",vm.uiState.value.materialError)
    val saved = InventoryRepository(app).inventory.value.single()
    assertEquals("伊布",saved.species)
    assertEquals(draft.id,saved.id)
    rule.runOnUiThread { vm.editMaterial(saved); vm.saveMaterial(saved.copy(ivs=listOf(99,1,1,1,1,1))) }
    rule.waitUntil(30_000) { !vm.uiState.value.isPlanning }
    assertTrue(vm.uiState.value.materialError.isNotBlank())
    assertEquals(saved,InventoryRepository(app).inventory.value.single())
    rule.runOnUiThread { vm.dismissMaterialEditor(); vm.clearInventory() }
    rule.waitUntil(30_000) { !vm.uiState.value.isPlanning }
    assertTrue(InventoryRepository(app).inventory.value.isEmpty())
    rule.runOnUiThread { vm.undoLastAction() }
    assertEquals(saved,InventoryRepository(app).inventory.value.single())
  }

  @Test fun doubleTapMarksAndUnmarksHatchingWithoutConsumingInventory() {
    val app = application()
    val response = plan(app)
    assertEquals(1,response.plan!!.steps.size)
    InventoryRepository(app).replace(WorkspaceSnapshot(listOf(mother,father),SavedPlanSession(response)))
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread { vm = MainScreenViewModel(app) }
    rule.setContent {
      val state by vm.uiState.collectAsState()
      PokeMMOBreederHelperTheme {
        BreedingMindMap(state.plannerResponse!!.plan!!,emptySet(),vm::toggleStep,Modifier.height(560.dp),onMarkInProgress=vm::toggleInProgress)
      }
    }
    val y = with(rule.density) { 160.dp.toPx() }
    repeat(2) { index ->
      rule.onNodeWithContentDescription("孵蛋路线思维导图",substring=true).performTouchInput { doubleClick(Offset(center.x,y)) }
      rule.waitForIdle()
      assertEquals(index == 0,InventoryRepository(app).loadPlanSession()!!.response.plan!!.steps.single().inProgress)
      assertEquals(listOf(mother,father),InventoryRepository(app).inventory.value)
    }
    rule.runOnUiThread { vm.suggestNext() }
    rule.waitUntil(30_000) { !vm.uiState.value.isPlanning }
    rule.runOnUiThread { vm.toggleInProgress(vm.uiState.value.pendingResponse!!.plan!!.steps.first()) }
    assertFalse(InventoryRepository(app).loadPlanSession()!!.response.plan!!.steps.single().inProgress)
  }

  @Test fun inventoryEditorAndClearConfirmationAreReachable() {
    val app = application()
    InventoryRepository(app).replace(WorkspaceSnapshot(listOf(mother,father)))
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread { vm = MainScreenViewModel(app) }
    rule.setContent { MainScreen(viewModel=vm) }
    rule.onNodeWithText("新增素材").performClick()
    rule.onNodeWithText("保存素材").assertIsDisplayed()
    rule.onNodeWithText("取消").performClick()
    rule.onNode(hasScrollAction()).performScrollToNode(hasText("清空库存"))
    rule.onNodeWithText("清空库存").performClick()
    rule.onNodeWithText("清空全部库存？").assertIsDisplayed()
    rule.onNodeWithText("取消").performClick()
    assertEquals(2,InventoryRepository(app).inventory.value.size)
  }
}
