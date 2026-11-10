package com.example.pokemmobreederhelper.ui.main

import android.app.Application
import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.test.core.app.ApplicationProvider
import com.example.pokemmobreederhelper.data.*
import com.example.pokemmobreederhelper.theme.PokeMMOBreederHelperTheme
import java.io.File
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class PlanningCostsTest {
  @get:Rule val rule = createAndroidComposeRule<ComponentActivity>()
  private fun application(): Application {
    val base = ApplicationProvider.getApplicationContext<Application>()
    val folder = File(base.cacheDir, "cost-test-" + System.nanoTime()).also { it.mkdirs() }
    return object : Application() {
      init { attachBaseContext(base) }
      override fun getApplicationContext(): Context = this
      override fun getFilesDir(): File = folder
    }
  }

  @Test fun purchaseAndFeeControlsSurviveRestart() {
    val app = application()
    lateinit var vm: MainScreenViewModel
    rule.runOnUiThread { vm = MainScreenViewModel(app); vm.selectTab(MainTab.Planner); vm.setIvPreset(listOf("31","31","31","X","31","31")) }
    rule.setContent { PokeMMOBreederHelperTheme { MainScreen(viewModel = vm) } }
    rule.onNodeWithText("省钱规划").performScrollTo().performClick()
    rule.onNodeWithText("自动 3V").performScrollTo().assertIsDisplayed()
    rule.onNodeWithText("2V", substring = false).performScrollTo().performClick()
    rule.onNodeWithText("费用设置").performScrollTo().performClick()
    rule.onNodeWithText("不变之石单价").performScrollTo().performTextReplacement("8500")
    rule.runOnUiThread { vm.clearPlanning() }
    val target = InventoryRepository(app).loadTarget()!!
    assertEquals("cost", target.strategy)
    assertEquals(2, target.maxPurchaseV)
    assertEquals(8500L, target.costPricing.everstone)
    assertTrue(target.costPricing.requireMarketAvailability)
    rule.runOnUiThread {
      val restored = MainScreenViewModel(app).uiState.value
      assertEquals("8500", restored.everstonePrice)
      assertEquals(2, restored.maxPurchaseV)
    }
  }

  @Test fun skillPreparationMustBeConfirmedBeforeConsumingParents() {
    var confirmed = false
    val step = ExecutionStepRecord(1, "a", "b", child = MonsterRecord(id = "child"),
      preparations = listOf(SkillPreparation("a", "伊布", "祈愿", "回忆技能")))
    rule.setContent { PokeMMOBreederHelperTheme {
      CompletionDialog(step, "", {}, { _, _, ready -> confirmed = ready }, {})
    } }
    rule.onNodeWithText("配种前技能准备").assertExists()
    rule.onNodeWithText("确认已孵完").assertIsNotEnabled()
    rule.onNodeWithText("已完成上述技能准备").performScrollTo().performClick()
    rule.onNodeWithText("确认已孵完").assertIsEnabled().performClick()
    assertTrue(confirmed)
  }

  @Test fun packagedPlannerUsesCostModuleAndKeepsModernRouteFields() {
    val bridge = PlannerBridge(application())
    val response = bridge.generatePlan("[]", PlanRequest("伊布", strategy = "cost", maxPurchaseV = 1,
      ivs = listOf("31","31","X","X","X","X")))
    assertTrue(response.error, response.ok)
    assertTrue(response.plan!!.costSummary.contains("还需支出"))
    val restored = AppJson.codec.decodeFromString<PlannerResponse>(AppJson.codec.encodeToString(PlannerResponse.serializer(), response))
    assertEquals(response, restored)
  }
}
