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
import com.example.pokemmobreederhelper.data.CaptureStore
import org.junit.Assert.*
import org.junit.Test

class LiveCaptureJourneyTest {
  private val instrumentation=InstrumentationRegistry.getInstrumentation()
  private val context=instrumentation.targetContext
  private val automation=instrumentation.uiAutomation
  private fun awaitCondition(timeout:Long=30000, condition:()->Boolean) {
    val until=SystemClock.elapsedRealtime()+timeout
    while(SystemClock.elapsedRealtime()<until) { if(condition())return;Thread.sleep(180) }
    assertTrue("Timed out: ${LiveCaptureState.state.value}",condition())
  }
  private fun nodes():List<AccessibilityNodeInfo> {
    val result=mutableListOf<AccessibilityNodeInfo>()
    fun visit(node:AccessibilityNodeInfo?) { if(node==null)return;result.add(node);for(i in 0 until node.childCount)visit(node.getChild(i)) }
    automation.windows.forEach { visit(it.root) }
    if(result.isEmpty())visit(automation.rootInActiveWindow)
    return result
  }
  private fun click(vararg labels:String) {
    awaitCondition { nodes().any { node -> labels.any { node.text?.toString().equals(it,true) } } }
    val node=nodes().first { node -> labels.any { node.text?.toString().equals(it,true) } }
    assertTrue(node.performAction(AccessibilityNodeInfo.ACTION_CLICK))
  }
  private fun screenshot(name:String) {
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
  @Test fun projectionSavesPositionsAvoidsDuplicatesAndStopsCleanly() {
    check(context.packageName.endsWith(".devtest"))
    automation.serviceInfo=automation.serviceInfo.apply { flags=flags or AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS }
    automation.executeShellCommand("appops set ${context.packageName} SYSTEM_ALERT_WINDOW allow").use { android.os.ParcelFileDescriptor.AutoCloseInputStream(it).readBytes() }
    val store=CaptureStore(context);store.save(emptyList())
    context.getSharedPreferences("live-capture",0).edit().clear().putString("account","模拟账号").putInt("box",2).putInt("slot",59).apply()
    val intent=Intent().setClassName(context.packageName,"com.example.pokemmobreederhelper.ScreenCaptureFixtureActivity")
    val scenario=ActivityScenario.launch<android.app.Activity>(intent)
    try {
      click("Start capture fixture")
      click("Start now","立即开始","开始录制","开始共享")
      awaitCondition(90000) { store.load().size==1 }
      assertEquals("2",store.load()[0].material.page);assertEquals("59",store.load()[0].material.slot)
      assertEquals("模拟账号",store.load()[0].material.account);assertFalse(store.load()[0].material.verified)
      Thread.sleep(2200);assertEquals(1,store.load().size)
      click("Show second specimen")
      awaitCondition(45000) { store.load().size==2 }
      assertEquals("60",store.load()[1].material.slot)
      screenshot("live-overlay.png")
      // Explicit advancement permits two indistinguishable pets and rolls the box over.
      click("下一只")
      awaitCondition(30000) { store.load().size==3 }
      assertEquals("3",store.load()[2].material.page);assertEquals("1",store.load()[2].material.slot)
      click("暂停")
      awaitCondition { LiveCaptureState.state.value.paused }
      Thread.sleep(1800);assertEquals(3,store.load().size)
      click("收起");click("展开")
      click("识别范围");click("使用全屏")
      click("位置 / 模式")
      awaitCondition { nodes().any { it.contentDescription?.toString()=="用户名 / 角色" } }
      fill("用户名 / 角色","第二账号");fill("仓库号","4");fill("当前第几个","5")
      click("自动识别并保存新画面")
      screenshot("live-settings.png")
      click("保存")
      click("继续")
      Thread.sleep(2200);assertEquals(3,store.load().size)
      click("采集当前")
      awaitCondition { store.load().size==4 }
      assertEquals("第二账号",store.load()[3].material.account)
      assertEquals("4",store.load()[3].material.page);assertEquals("5",store.load()[3].material.slot)
      click("结束采集")
      awaitCondition { !LiveCaptureState.state.value.running }
      assertEquals(4,CaptureStore(context).load().size)
      assertEquals(6,context.getSharedPreferences("live-capture",0).getInt("slot",0))
    } finally { context.stopService(Intent(context,InventoryCaptureService::class.java));scenario.close() }
  }
}
