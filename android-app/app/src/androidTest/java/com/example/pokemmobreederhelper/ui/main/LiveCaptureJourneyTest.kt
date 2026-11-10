package com.example.pokemmobreederhelper.ui.main

import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.os.Bundle
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import com.example.pokemmobreederhelper.capture.InventoryCaptureService
import com.example.pokemmobreederhelper.capture.LiveCaptureState
import com.example.pokemmobreederhelper.data.*
import org.junit.Assert.*
import org.junit.Test

class LiveCaptureJourneyTest {
  private val instrumentation=InstrumentationRegistry.getInstrumentation()
  private val context=instrumentation.targetContext
  private val automation=instrumentation.uiAutomation
  private fun awaitCondition(timeout:Long=30000, condition:()->Boolean) {
    val until=SystemClock.elapsedRealtime()+timeout
    while(SystemClock.elapsedRealtime()<until) { if(condition())return;Thread.sleep(180) }
    automation.takeScreenshot()?.let { bitmap ->
      val diagnostic=kotlinx.coroutines.runBlocking { com.example.pokemmobreederhelper.data.CaptureOcr(PlannerBridge(context)).use { it.recognize(bitmap) } }
      java.io.File(context.getExternalFilesDir(null),"capture-failure.txt").writeText(diagnostic.toString())
      java.io.File(context.getExternalFilesDir(null),"capture-failure.png").outputStream().use { bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it) };bitmap.recycle()
    }
    assertTrue("Timed out: "+LiveCaptureState.state.value,condition())
  }
  private fun nodes():List<AccessibilityNodeInfo> {
    val result=mutableListOf<AccessibilityNodeInfo>()
    fun visit(node:AccessibilityNodeInfo?) { if(node==null)return;result.add(node);for(i in 0 until node.childCount)visit(node.getChild(i)) }
    automation.windows.forEach { visit(it.root) }
    if(result.isEmpty())visit(automation.rootInActiveWindow)
    return result
  }
  private fun click(vararg labels:String) {
    var found:AccessibilityNodeInfo?=null
    awaitCondition {
      found=nodes().firstOrNull { node -> labels.any { label ->
        node.text?.toString().equals(label,true) || node.contentDescription?.toString()==label
      } }
      found!=null
    }
    assertTrue(found!!.performAction(AccessibilityNodeInfo.ACTION_CLICK))
  }
  private fun screenshot(name:String) {
    instrumentation.waitForIdleSync()
    SystemClock.sleep(250) // Capture the rendered frame, after the native window has relaid out.
    automation.takeScreenshot()?.let { bitmap ->
      java.io.File(context.getExternalFilesDir(null), name).outputStream().use {
        bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)
      }
      bitmap.recycle()
    }
  }
  private fun fill(label:String,value:String) {
    val field=nodes().first { it.contentDescription?.toString()==label }
    assertTrue(field.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT,Bundle().apply {
      putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE,value)
    }))
  }
  private fun popupVisible(): Boolean {
    var found=false
    instrumentation.runOnMainSync {
      fun visit(view:android.view.View):Boolean = view.contentDescription?.toString()?.startsWith("自动入库提示 · ")==true ||
        (view is android.view.ViewGroup && (0 until view.childCount).any { visit(view.getChildAt(it)) })
      found=android.view.inspector.WindowInspector.getGlobalWindowViews().any { visit(it) }
    }
    return found
  }
  private fun tapGame() {
    val node=nodes().first { it.contentDescription?.toString()=="游戏精灵画面" }
    val bounds=android.graphics.Rect();node.getBoundsInScreen(bounds)
    // Use real input dispatch: an accessibility ACTION_CLICK does not generate ACTION_OUTSIDE.
    val now=SystemClock.uptimeMillis();val x=bounds.right-40f;val y=bounds.exactCenterY()
    for(action in listOf(android.view.MotionEvent.ACTION_DOWN,android.view.MotionEvent.ACTION_UP)) {
      val event=android.view.MotionEvent.obtain(now,SystemClock.uptimeMillis(),action,x,y,0).apply { source=android.view.InputDevice.SOURCE_TOUCHSCREEN }
      assertTrue(automation.injectInputEvent(event,true));event.recycle()
    }
  }
  @Test fun manualConfirmationBothNextOrdersAndMinimizedAutomaticResults() {
    check(context.packageName.endsWith(".devtest"))
    automation.serviceInfo=automation.serviceInfo.apply { flags=flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS }
    automation.executeShellCommand("appops set "+context.packageName+" SYSTEM_ALERT_WINDOW allow").use { android.os.ParcelFileDescriptor.AutoCloseInputStream(it).readBytes() }
    val store=CaptureStore(context);store.save(emptyList())
    val repository=InventoryRepository(context);repository.replace(WorkspaceSnapshot(emptyList()))
    context.getSharedPreferences("live-capture",0).edit().clear().putString("account","模拟账号").putInt("box",2).putInt("slot",59).putStringSet("accounts",setOf("第二账号")).apply()
    context.getSharedPreferences("capture-appearance",0).edit().clear().apply()
    val intent=Intent().setClassName(context.packageName,"com.example.pokemmobreederhelper.ScreenCaptureFixtureActivity")
    val scenario=ActivityScenario.launch<android.app.Activity>(intent)
    try {
      click("Start capture fixture");click("Start now","立即开始","开始录制","开始共享")
      awaitCondition(90000) { LiveCaptureState.state.value.hasPreview }
      assertEquals(0,repository.inventory.value.size)
      assertTrue(nodes().any { it.text?.toString()?.contains("皮卡丘  母 · 坦率")==true })
      screenshot("manual-preview.png")
      // Software next first: confirmation saves A, the old page must remain excluded.
      click("下一只");awaitCondition { repository.inventory.value.size==1 }
      Thread.sleep(1800);assertEquals(1,repository.inventory.value.size);assertFalse(LiveCaptureState.state.value.hasPreview)
      assertEquals("59",repository.inventory.value[0].slot)
      click("Show second specimen");awaitCondition { LiveCaptureState.state.value.hasPreview }
      assertEquals(1,repository.inventory.value.size)
      assertTrue(nodes().any { it.text?.toString()?.contains("皮卡丘  公 · 坦率")==true })
      screenshot("manual-male.png")
      // Game next first: preview B stays frozen even though game C is already visible.
      click("Show third specimen");Thread.sleep(1000)
      assertTrue(nodes().any { it.text?.toString()?.contains("皮卡丘  公 · 坦率")==true })
      click("下一只");awaitCondition { repository.inventory.value.size==2 && LiveCaptureState.state.value.hasPreview }
      assertEquals("60",repository.inventory.value[1].slot);assertEquals("M",repository.inventory.value[1].gender)
      click("下一只");awaitCondition { repository.inventory.value.size==3 }
      assertEquals("3",repository.inventory.value[2].page);assertEquals("1",repository.inventory.value[2].slot)
      assertEquals("F",repository.inventory.value[2].gender)
      click("Show third specimen");Thread.sleep(1800);assertFalse(LiveCaptureState.state.value.hasPreview)
      click("最小化自动采集");awaitCondition { LiveCaptureState.state.value.minimized }
      Thread.sleep(1000);assertEquals(3,repository.inventory.value.size)
      // Same species/IV/gender, but different nature: automatic mode must save the new specimen.
      click("Show fourth specimen");awaitCondition { repository.inventory.value.size==4 && popupVisible() }
      assertEquals("固执",repository.inventory.value[3].nature)
      screenshot("automatic-popup.png")
      val tapAt=SystemClock.elapsedRealtime();tapGame()
      awaitCondition(1500) { !popupVisible() }
      assertTrue("Outside tap did not promptly dismiss popup",SystemClock.elapsedRealtime()-tapAt<1200)
      assertTrue(nodes().any { it.text?.toString()=="Game taps: 1" })
      click("Show fifth specimen");awaitCondition { repository.inventory.value.size==5 && popupVisible() }
      Thread.sleep(1200);assertTrue(popupVisible())
      awaitCondition(6000) { !popupVisible() }
      screenshot("minimized-bubble.png")
      // Appearance updates a running overlay without requesting a new projection.
      com.example.pokemmobreederhelper.capture.OverlayAppearance(fontSp=12f,opacity=.7f,autoSize=false,widthDp=250,heightDp=280).save(context)
      click("展开手动采集");awaitCondition { !LiveCaptureState.state.value.minimized }
      click("暂停");awaitCondition { LiveCaptureState.state.value.paused }
      click("识别范围");click("使用全屏")
      click("选择账号与仓位");click("选择用户名 第二账号");fill("仓库号","4");fill("当前第几个","5")
      screenshot("account-position.png");click("保存");click("继续")
      Thread.sleep(1200);assertFalse(LiveCaptureState.state.value.hasPreview)
      click("Show first specimen");awaitCondition { LiveCaptureState.state.value.hasPreview }
      // Last specimen has an explicit confirmation path and the next position is persisted.
      click("保存并结束");awaitCondition { !LiveCaptureState.state.value.running }
      assertEquals(6,repository.inventory.value.size)
      assertEquals("第二账号",repository.inventory.value.last().account)
      assertEquals("4",repository.inventory.value.last().page);assertEquals("5",repository.inventory.value.last().slot)
      assertEquals(6,context.getSharedPreferences("live-capture",0).getInt("slot",0))
      assertTrue(store.load().isEmpty());assertTrue(repository.inventory.value.none { it.verified })
      assertEquals(6,repository.inventory.value.map { it.id }.distinct().size)
      assertEquals(repository.inventory.value,AppJson.decodeInventory(repository.inventoryJson()))
      java.io.File(context.getExternalFilesDir(null),"live-export.json").writeText(repository.inventoryJson())
    } finally { context.stopService(Intent(context,InventoryCaptureService::class.java));scenario.close() }
  }
}
