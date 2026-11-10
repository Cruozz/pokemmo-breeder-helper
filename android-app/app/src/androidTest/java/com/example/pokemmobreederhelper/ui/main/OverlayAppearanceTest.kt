package com.example.pokemmobreederhelper.ui.main

import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.widget.TextView
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.example.pokemmobreederhelper.capture.*
import com.example.pokemmobreederhelper.data.MonsterRecord
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class OverlayAppearanceTest {
  @get:Rule val rule=createComposeRule()
  private val context=InstrumentationRegistry.getInstrumentation().targetContext
  @Test fun appearanceControlsPersistAndRestoreDefaults() {
    OverlayAppearance().save(context)
    rule.setContent { MaterialTheme { OverlayAppearanceSettings {} } }
    rule.onNodeWithText("浮窗外观").assertIsDisplayed()
    rule.onAllNodes(SemanticsMatcher.keyIsDefined(androidx.compose.ui.semantics.SemanticsProperties.ProgressBarRangeInfo))[1].performSemanticsAction(SemanticsActions.SetProgress) { it(14f) }
    rule.waitForIdle();assertEquals(14f,OverlayAppearance.load(context).fontSp)
    rule.onNode(isToggleable()).performClick()
    rule.onNodeWithText("宽度 264 dp").performScrollTo().assertIsDisplayed()
    assertFalse(OverlayAppearance.load(context).autoSize)
    rule.onNodeWithText("恢复默认").performClick()
    rule.waitForIdle();assertEquals(OverlayAppearance(),OverlayAppearance.load(context))
    rule.onNodeWithText("字体大小 10 sp").performScrollTo().assertIsDisplayed()
    InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()?.let { bitmap ->
      java.io.File(context.getExternalFilesDir(null),"appearance-settings.png").outputStream().use {
        bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it)
      };bitmap.recycle()
    }
  }
  @Test fun coloredResultsDistinguishGenderAndOnlyPerfectIvs() {
    InstrumentationRegistry.getInstrumentation().runOnMainSync {
      val view=CaptureResultView(context);view.font(10f)
      val pet=MonsterRecord(species="皮卡丘",gender="M",nature="固执",ivs=listOf(31,30,0,31,5,6))
      fun colors(index:Int) = ((view.getChildAt(index) as TextView).text as Spanned).let {
        it.getSpans(0,it.length,ForegroundColorSpan::class.java).map { span ->
          span.foregroundColor to it.subSequence(it.getSpanStart(span),it.getSpanEnd(span)).toString()
        }
      }
      view.show(pet)
      assertEquals(listOf(CaptureColors.male to "公"),colors(0))
      assertEquals(listOf(CaptureColors.perfect to "31",CaptureColors.perfect to "31"),colors(1))
      view.show(pet.copy(gender="F"));assertEquals(listOf(CaptureColors.female to "母"),colors(0))
      view.show(pet.copy(gender="",nature=""));assertTrue(view.contentDescription.toString().contains("性别待确认"))
      assertTrue(view.contentDescription.toString().contains("性格待确认"))
    }
  }
}
