package com.example.pokemmobreederhelper.ui.main

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.net.Uri
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.ViewModelProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.example.pokemmobreederhelper.MainActivity
import com.example.pokemmobreederhelper.data.*
import java.io.File
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test

class CaptureImportTest {
  @get:Rule val rule = createAndroidComposeRule<MainActivity>()
  private lateinit var captureVm: InventoryCaptureViewModel
  private lateinit var mainVm: MainScreenViewModel

  @Before fun setup() {
    rule.runOnUiThread {
      check(rule.activity.packageName.endsWith(".devtest")) { "Only run these fixtures in the isolated test app." }
      captureVm = ViewModelProvider(rule.activity)[InventoryCaptureViewModel::class.java]
      mainVm = ViewModelProvider(rule.activity)[MainScreenViewModel::class.java]
    }
    rule.waitUntil(10000) { !captureVm.state.value.busy }
    rule.runOnUiThread {
      captureVm.clearDrafts()
      mainVm.clearInventory()
    }
    rule.waitUntil(10000) { !mainVm.uiState.value.isPlanning && captureVm.state.value.drafts.isEmpty() }
  }

  private fun screenshot(nameLine: String = "Lv.1 伊布"): Uri {
    val file = File(rule.activity.cacheDir, "synthetic-inventory.png")
    val bitmap = Bitmap.createBitmap(1280, 720, Bitmap.Config.ARGB_8888)
    val canvas = Canvas(bitmap)
    canvas.drawColor(Color.WHITE)
    val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.BLACK; textSize = 42f }
    listOf(nameLine, "能力值：12/5/6/5/6/5", "个体值：31/2/19/0/16/6", "努力值：0/0/0/0/0/0", "性格：坦率 Docile")
      .forEachIndexed { index, line -> canvas.drawText(line, 60f, 90f + index * 100, paint) }
    file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    bitmap.recycle()
    return Uri.fromFile(file)
  }

  @Test fun screenshotIsLocalAndRequiresReviewBeforeInventoryChanges() {
    val uri = screenshot()
    rule.waitUntil(15000) { rule.onAllNodesWithText("实时浮窗 / 截图 / 录屏采集库存").fetchSemanticsNodes().size == 1 }
    rule.onNodeWithText("实时浮窗 / 截图 / 录屏采集库存").performClick()
    rule.runOnUiThread { captureVm.scan(listOf(uri), false) }
    rule.waitUntil(90000) { !captureVm.state.value.busy }
    val draft = captureVm.state.value.drafts.single()
    android.util.Log.i("CaptureFixture", draft.rawText)
    assertTrue(draft.warnings.isNotEmpty())
    assertEquals(listOf(31, 2, 19, 0, 16, 6), draft.material.ivs)
    assertFalse(draft.material.verified)
    assertTrue(mainVm.uiState.value.inventory.isEmpty())
    assertEquals(1, CaptureStore(rule.activity).load().size)
    rule.onNode(hasScrollAction() and hasAnyDescendant(hasText("实时悬浮采集")))
      .performScrollToNode(hasText("核对入库"))
    rule.onNodeWithText("核对入库").performClick()
    rule.onNodeWithText("确认入库").performClick()
    rule.onNodeWithText("请对照原画面核对，并勾选“已核对，可参与规划”。").assertIsDisplayed()
    // Model output is a draft; the review must also support correcting an unreadable name.
    rule.onNodeWithText("精灵名称（中文、英文或编号）").performScrollTo().performTextReplacement("伊布")
    rule.onNodeWithText("母", useUnmergedTree = true).performScrollTo().performClick()
    rule.onNodeWithTag("material-editor-fields").performScrollToNode(hasText("已核对，可参与规划"))
    rule.onNodeWithText("已核对，可参与规划").performClick()
    rule.onNodeWithText("确认入库").performClick()
    rule.waitUntil(15000) { mainVm.uiState.value.inventory.size == 1 && captureVm.state.value.drafts.isEmpty() }
    val saved = InventoryRepository(rule.activity).inventory.value.single()
    assertTrue(saved.verified)
    assertEquals(draft.material.id, saved.id)
    assertEquals("F", saved.gender)
    assertEquals("伊布", saved.species)
  }

  @Test fun screenshotCanGoStraightToInventoryAndExportAsUnconfirmed() {
    rule.runOnUiThread { captureVm.scan(listOf(screenshot("名字：皮卡丘")), false) }
    rule.waitUntil(90000) { !captureVm.state.value.busy }
    val draft=captureVm.state.value.drafts.single()
    assertTrue(draft.rawText,draft.material.species.isNotBlank())
    rule.runOnUiThread { captureVm.importDirect(draft.material.id) }
    rule.waitUntil(15000) { !captureVm.state.value.busy && mainVm.uiState.value.inventory.size==1 }
    assertTrue(captureVm.state.value.drafts.isEmpty())
    val repository=InventoryRepository(rule.activity)
    val saved=AppJson.decodeInventory(repository.inventoryJson()).single()
    assertEquals(draft.material.id,saved.id)
    assertFalse(saved.verified)
    assertEquals(draft.material.ivs,saved.ivs)
    rule.runOnUiThread { captureVm.importDirect(draft.material.id) }
    assertEquals(1,repository.inventory.value.size)
  }

  @Test fun recordingSamplesAndGroupsOnlyAdjacentEqualFrames() {
    val file = File(rule.activity.cacheDir, "synthetic-inventory.mp4")
    InstrumentationRegistry.getInstrumentation().context.assets.open("synthetic-inventory.mp4").use { source ->
      file.outputStream().use { source.copyTo(it) }
    }
    rule.runOnUiThread { captureVm.scan(listOf(Uri.fromFile(file)), true) }
    rule.waitUntil(90000) { !captureVm.state.value.busy }
    val state = captureVm.state.value
    assertEquals(state.error, "", state.error)
    assertEquals(4, state.processed)
    // OCR can disagree on compressed repeated characters. Preserve those uncertain frames.
    assertTrue(state.drafts.size in 2..4)
    assertEquals(4, state.drafts.sumOf { it.frameCount })
    assertEquals(4 - state.drafts.size, state.grouped)
    assertEquals(listOf(31, 2, 19, 0, 16, 6), state.drafts.first().material.ivs)
    assertEquals(listOf(31, 31, 20, 0, 15, 6), state.drafts.last().material.ivs)
    assertEquals("伊布", state.drafts.last().material.species)
    assertTrue(state.drafts.all { !it.material.verified })
    assertTrue(mainVm.uiState.value.inventory.isEmpty())
    rule.runOnUiThread { captureVm.copyDraft(state.drafts.first().material.id) }
    rule.waitUntil(5000) { captureVm.state.value.drafts.size == state.drafts.size + 1 }
    assertEquals(state.drafts.size + 1, CaptureStore(rule.activity).load().map { it.material.id }.distinct().size)
  }
}
