package com.example.pokemmobreederhelper.ui.main

import android.os.SystemClock
import android.view.*
import androidx.test.platform.app.InstrumentationRegistry
import com.example.pokemmobreederhelper.capture.*
import com.example.pokemmobreederhelper.data.MonsterRecord
import org.junit.Assert.*
import org.junit.Test

class CapturePopupTest {
  @Test fun earlierOutsideTapDoesNotHideJustSavedResult() {
    val i=InstrumentationRegistry.getInstrumentation();val context=i.targetContext
    i.uiAutomation.executeShellCommand("appops set "+context.packageName+" SYSTEM_ALERT_WINDOW allow").use {
      android.os.ParcelFileDescriptor.AutoCloseInputStream(it).readBytes()
    }
    val prefs=context.getSharedPreferences("live-capture",0)
    val previous=prefs.getBoolean("minimized",false)
    prefs.edit().putBoolean("minimized",true).commit()
    lateinit var overlay: CaptureOverlay
    lateinit var root: View
    fun includes(view:View,label:String):Boolean = view.contentDescription?.toString()?.startsWith(label)==true ||
      (view is ViewGroup && (0 until view.childCount).any { includes(view.getChildAt(it),label) })
    fun popup()=android.view.inspector.WindowInspector.getGlobalWindowViews().firstOrNull { includes(it,"自动入库提示 · ") }
    try {
      i.runOnMainSync { overlay=CaptureOverlay(context,{},{},{},{},{},{},{},{true})
        val earlier=SystemClock.uptimeMillis()-1000
        overlay.showSaved(MonsterRecord(species="伊布",gender="F",nature="胆小",ivs=listOf(31,4,9,2,8,30)))
        val shown=popup();assertNotNull(shown)
        assertTrue((shown!!.layoutParams as WindowManager.LayoutParams).flags and WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE != 0)
        root=android.view.inspector.WindowInspector.getGlobalWindowViews().first { includes(it,"展开手动采集") }
        MotionEvent.obtain(earlier,earlier,MotionEvent.ACTION_OUTSIDE,0f,0f,0).also { root.dispatchTouchEvent(it);it.recycle() }
        assertNotNull("An old game tap dismissed the new result",popup())
      }
      i.waitForIdleSync()
      i.runOnMainSync {
        assertNotNull(popup())
        val later=SystemClock.uptimeMillis()+1
        MotionEvent.obtain(later,later,MotionEvent.ACTION_OUTSIDE,0f,0f,0).also { root.dispatchTouchEvent(it);it.recycle() }
      }
      i.waitForIdleSync()
      i.runOnMainSync { assertNull(popup()) }
    } finally { i.runOnMainSync { overlay.close() };prefs.edit().putBoolean("minimized",previous).commit() }
  }
}
