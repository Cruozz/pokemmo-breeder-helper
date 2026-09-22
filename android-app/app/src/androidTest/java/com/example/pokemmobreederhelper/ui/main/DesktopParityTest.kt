package com.example.pokemmobreederhelper.ui.main

import android.app.Application
import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.test.core.app.ApplicationProvider
import com.example.pokemmobreederhelper.data.*
import com.example.pokemmobreederhelper.theme.PokeMMOBreederHelperTheme
import androidx.compose.foundation.layout.height
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import java.io.File
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class DesktopParityTest {
  @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()
  private fun application(): Application {
    val base = ApplicationProvider.getApplicationContext<Application>()
    val folder = File(base.cacheDir, "parity-${System.nanoTime()}").also { it.mkdirs() }
    return object : Application() {
      init { attachBaseContext(base) }
      override fun getApplicationContext(): Context = this
      override fun getFilesDir(): File = folder
    }
  }

  @Test fun clearKeepsInventoryAcrossRestartAndUndoCannotRestoreRoute() {
    val app = application()
    val repository = InventoryRepository(app)
    val parent = MonsterRecord(id = "parent")
    val child = MonsterRecord(id = "completed-child")
    val response = PlannerResponse(ok = true, rulesVersion = "0.2.8")
    repository.replace(WorkspaceSnapshot(listOf(parent), SavedPlanSession(response)))
    repository.replace(WorkspaceSnapshot(listOf(child), SavedPlanSession(response)))
    repository.clearPlanSession()
    val restored = InventoryRepository(app)
    assertEquals(listOf(child), restored.inventory.value)
    assertNull(restored.loadPlanSession())
    assertTrue(restored.undo())
    val undone = InventoryRepository(app)
    assertEquals(listOf(parent), undone.inventory.value)
    assertNull(undone.loadPlanSession())
  }

  @Test fun clearInvalidatesRunningSearchAndSpeciesChangeClearsSkills() {
    val app = application()
    val bridge = PlannerBridge(app)
    val species = bridge.searchSpecies("伊布").first()
    assertTrue("祈愿" in species.eggMoves)
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread {
      vm = MainScreenViewModel(app)
      vm.chooseSpecies(species)
      vm.toggleTargetMove("祈愿")
      assertEquals(listOf("祈愿"), vm.uiState.value.targetMoves)
      vm.setIv(0, "31")
      vm.setIv(1, "31")
      vm.setIv(2, "31")
      vm.generatePlan()
      vm.clearPlanning()
    }
    // Allow the native Python call to finish even if coroutine cancellation cannot stop it.
    Thread.sleep(3000)
    rule.runOnUiThread {
      assertFalse(vm.uiState.value.isPlanning)
      assertNull(vm.uiState.value.pendingResponse)
      assertNull(vm.uiState.value.plannerResponse)
      vm.setSpeciesQuery("索罗亚")
      assertTrue(vm.uiState.value.targetMoves.isEmpty())
    }
    assertNull(InventoryRepository(app).loadPlanSession())
    assertEquals(listOf("祈愿"), InventoryRepository(app).loadTarget()!!.targetMoves)
  }

  @Test fun packagedSkillRouteRendersWithMaternalOverlay() {
    val bridge = PlannerBridge(application())
    val response = bridge.generatePlan("[]", PlanRequest("伊布", targetMoves = listOf("祈愿"),
      ivs = listOf("31", "31", "31", "X", "X", "X"), allowDitto = false))
    assertTrue(response.error, response.ok)
    val plan = response.plan!!
    val root = buildRouteRoot(plan, emptySet(), true)
    assertEquals("maternal", root.routeRole)
    assertTrue("祈愿" in root.routeMoves)
    assertTrue(root.children.any { hasSkillEdge(root, it) })
    rule.setContent { PokeMMOBreederHelperTheme {
      BreedingMindMap(plan, emptySet(), {}, Modifier.height(600.dp))
    } }
    rule.waitForIdle()
    val context = ApplicationProvider.getApplicationContext<Context>()
    val bitmap = rule.onRoot().captureToImage().asAndroidBitmap()
    File(context.getExternalFilesDir(null), "route-parity.png").outputStream().use {
      bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it)
    }
  }
}
