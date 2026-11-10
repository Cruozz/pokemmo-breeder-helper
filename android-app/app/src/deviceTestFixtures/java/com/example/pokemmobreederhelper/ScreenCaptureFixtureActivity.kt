package com.example.pokemmobreederhelper

import android.app.Activity
import android.content.Intent
import android.graphics.*
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.view.View
import android.widget.*
import com.example.pokemmobreederhelper.capture.InventoryCaptureService

/** Synthetic screen only included by -PisolatedDeviceTests=true. */
class ScreenCaptureFixtureActivity : Activity() {
  private var specimen=0
  private var taps=0
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    check(packageName.endsWith(".devtest"))
    val layout=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setBackgroundColor(Color.WHITE) }
    val tapCounter=TextView(this).apply { text="Game taps: 0";setTextColor(Color.BLACK) }
    val page=object:View(this) {
      override fun onDraw(canvas:Canvas) {
        canvas.drawColor(Color.WHITE)
        val paint=Paint(Paint.ANTI_ALIAS_FLAG).apply { color=Color.BLACK;textSize=width/38f }
        val gender=if(specimen==1) "雄性" else "雌性"
        val iv=when(specimen) { 0->"31/2/19/0/16/6";4->"31/31/20/0/15/31";else->"31/31/20/0/15/6" }
        val nature=if(specimen>=3) "固执 Adamant" else "坦率 Docile"
        val lines=listOf("名字：皮卡丘", "Lv.50 "+gender, "个体值："+iv, "性格："+nature)
        lines.forEachIndexed { i,text -> canvas.drawText(text,width*0.43f,height*(0.16f+i*0.19f),paint) }
      }
    }.apply { contentDescription="游戏精灵画面";setOnClickListener { taps++;tapCounter.text="Game taps: "+taps } }
    layout.addView(page,LinearLayout.LayoutParams(-1,0,1f));layout.addView(tapCounter)
    val row=LinearLayout(this)
    row.addView(Button(this).apply { text="Start capture fixture";setOnClickListener {
      startActivityForResult(getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent(),7)
    } },LinearLayout.LayoutParams(0,80,1f))
    val labels=listOf("Show first specimen","Show second specimen","Show third specimen","Show fourth specimen","Show fifth specimen")
    labels.forEachIndexed { index,label ->
      row.addView(Button(this).apply { text=label;textSize=10f;setOnClickListener { specimen=index;page.invalidate() } },LinearLayout.LayoutParams(0,80,1f))
    }
    layout.addView(row);setContentView(layout)
  }
  @Deprecated("Fixture uses the platform activity result API")
  override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?) {
    super.onActivityResult(requestCode,resultCode,data)
    if(requestCode==7 && resultCode==RESULT_OK && data!=null) startForegroundService(Intent(this,InventoryCaptureService::class.java)
      .setAction(InventoryCaptureService.START).putExtra("result",resultCode).putExtra("token",data))
  }
}
