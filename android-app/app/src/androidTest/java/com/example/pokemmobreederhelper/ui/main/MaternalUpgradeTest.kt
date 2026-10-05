package com.example.pokemmobreederhelper.ui.main

import android.app.Application
import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.core.app.ApplicationProvider
import com.example.pokemmobreederhelper.BuildConfig
import com.example.pokemmobreederhelper.data.*
import com.example.pokemmobreederhelper.theme.PokeMMOBreederHelperTheme
import java.io.File
import kotlinx.serialization.encodeToString
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class MaternalUpgradeTest {
  @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()

  private fun application(): Application {
    val base = ApplicationProvider.getApplicationContext<Application>()
    val directory = File(base.cacheDir, "maternal-upgrade-${System.nanoTime()}").also { it.mkdirs() }
    return object : Application() {
      init { attachBaseContext(base) }
      override fun getApplicationContext(): Context = this
      override fun getFilesDir(): File = directory
    }
  }

  private fun inventory(): List<MonsterRecord> {
    fun material(id: String, species: String, gender: String, mask: Int, nature: String = "") =
      MonsterRecord(id = id, species = species, gender = gender, nature = nature, isAlpha = true,
        ivs = (0..5).map { if (mask and (1 shl it) != 0) 31 else 1 })
    return listOf(material("adamant-source", "双尾怪手", "M", 6, "固执"),
      material("ditto2", "百变怪", "N", 6), material("ditto3", "百变怪", "N", 7),
      material("donor3", "伊布", "M", 7), material("donor4", "伊布", "M", 23),
      material("donor5", "伊布", "M", 55), material("weak-female", "长尾怪手", "F", 33))
  }

  @Test fun packagedFiveVChainUsesNaturedTwoVSourceAndThreeVDittoThenConsumesCorrectParents() {
    val bridge = PlannerBridge(application())
    val stock = inventory()
    val request = PlanRequest("长尾怪手", nature = "固执", natureStrategy = "chain", targetAlpha = true,
      ivs = listOf("31", "31", "31", "X", "31", "31"), allowDitto = false, convertMaternalWithDitto = true)
    val response = bridge.generatePlan(AppJson.codec.encodeToString(stock), request)
    assertTrue(response.error + response.report, response.ok)
    assertEquals(BuildConfig.PLANNER_RULES_VERSION, response.rulesVersion)
    val plan = response.plan!!
    assertEquals(3, plan.steps.size)
    val conversion = plan.steps.first { "ditto3" in listOf(it.parentAId, it.parentBId) }
    assertEquals(setOf("adamant-source", "ditto3"), setOf(conversion.parentAId, conversion.parentBId))
    assertEquals("不变之石", conversion.itemA)
    assertEquals("HP护腕", conversion.itemB)
    assertEquals("固执", conversion.child.nature)
    assertEquals("长尾怪手", conversion.child.species)
    assertEquals("F", conversion.child.gender)
    assertEquals(3, conversion.child.perfectIvCount)
    assertEquals("固执", plan.steps.last().child.nature)
    assertEquals(5, plan.steps.last().child.perfectIvCount)
    val completed = bridge.completeStep(AppJson.codec.encodeToString(stock), response, StepOutcome(conversion.number, "F"))
    assertTrue(completed.error, completed.ok)
    assertFalse(completed.inventory.any { it.id in setOf("adamant-source", "ditto3") })
    assertTrue(completed.inventory.any { it.id == conversion.child.id && it.nature == "固执" && it.perfectIvCount == 3 })
  }

  @Test fun commonControlsSetPhysicalFiveVAndConversionOnlyWithoutChangingOtherRules() {
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread {
      vm = MainScreenViewModel(application())
      vm.selectTab(MainTab.Planner)
      vm.setNature("固执")
    }
    rule.setContent { PokeMMOBreederHelperTheme { MainScreen(viewModel = vm) } }
    rule.onNodeWithText("5V 物攻").performScrollTo().performClick()
    assertEquals(listOf("31", "31", "31", "X", "31", "31"), vm.uiState.value.ivs)
    rule.onNodeWithText("仅转母").performScrollTo().performClick()
    assertFalse(vm.uiState.value.allowDitto)
    assertTrue(vm.uiState.value.convertMaternalWithDitto)
    rule.onNodeWithText("全程锁性格").performScrollTo().performClick()
    assertEquals("chain", vm.uiState.value.natureStrategy)
    assertEquals("固执", vm.uiState.value.nature)
    assertFalse(vm.uiState.value.targetAlpha)
    rule.onNodeWithText("素材库存 0").performClick()
    rule.onNodeWithText("孵蛋规划").performClick()
    rule.onNodeWithText("全程锁性格").performScrollTo().assertIsDisplayed()
    assertEquals("chain", vm.uiState.value.natureStrategy)
  }

  @Test fun legacyRouteCannotOpenCompletionAndShowsReplanEntry() {
    val app = application()
    val stock = inventory()
    val request = PlanRequest("长尾怪手", nature = "固执", natureStrategy = "chain", targetAlpha = true,
      ivs = listOf("31", "31", "31", "X", "31", "31"), allowDitto = false, convertMaternalWithDitto = true)
    val response = PlannerBridge(app).generatePlan(AppJson.codec.encodeToString(stock), request).copy(rulesVersion = "0.2.8")
    InventoryRepository(app).replace(WorkspaceSnapshot(stock, SavedPlanSession(response, request = request)))
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread {
      vm = MainScreenViewModel(app)
      vm.selectTab(MainTab.Planner)
      vm.toggleStep(response.plan!!.steps.first())
    }
    assertNull(vm.uiState.value.pendingStep)
    assertEquals(stock, vm.uiState.value.inventory)
    rule.setContent { PokeMMOBreederHelperTheme { MainScreen(viewModel = vm) } }
    rule.onNodeWithText("路线已暂停").performScrollTo().assertIsDisplayed()
    rule.onNodeWithText("按原目标生成建议").performScrollTo().assertIsDisplayed()
  }

  @Test fun activeRouteKeepsExpandedTargetWhenReturningFromInventory() {
    val app = application()
    val stock = inventory()
    val request = PlanRequest("长尾怪手", nature = "固执", natureStrategy = "chain", targetAlpha = true,
      ivs = listOf("31", "31", "31", "X", "31", "31"), allowDitto = false, convertMaternalWithDitto = true)
    val response = PlannerBridge(app).generatePlan(AppJson.codec.encodeToString(stock), request)
    InventoryRepository(app).replace(WorkspaceSnapshot(stock, SavedPlanSession(response, request = request)))
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread { vm = MainScreenViewModel(app); vm.selectTab(MainTab.Planner) }
    rule.setContent { PokeMMOBreederHelperTheme { MainScreen(viewModel = vm) } }
    rule.onNodeWithText("修改目标").performScrollTo().performClick()
    rule.onNodeWithText("目标与规则").performScrollTo().assertIsDisplayed()
    rule.onNodeWithText("素材库存 7").performClick()
    rule.onNodeWithText("孵蛋规划").performClick()
    rule.onNodeWithText("目标与规则").assertIsDisplayed()
  }
}
