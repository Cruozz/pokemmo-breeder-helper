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
  private var second=false
  override fun onCreate(savedInstanceState: Bundle?) {
    super.onCreate(savedInstanceState)
    check(packageName.endsWith(".devtest"))
    val layout=LinearLayout(this).apply { orientation=LinearLayout.VERTICAL;setBackgroundColor(Color.WHITE) }
    val page=object:View(this) {
      override fun onDraw(canvas:Canvas) {
        canvas.drawColor(Color.WHITE)
        val paint=Paint(Paint.ANTI_ALIAS_FLAG).apply { color=Color.BLACK;textSize=width/38f }
        val lines=listOf("名字：皮卡丘", "Lv.50", "个体值：${if(second) "31/31/20/0/15/6" else "31/2/19/0/16/6"}", "性格：坦率 Docile")
        lines.forEachIndexed { i,text -> canvas.drawText(text,width*0.46f,height*(0.16f+i*0.19f),paint) }
      }
    }
    layout.addView(page,LinearLayout.LayoutParams(-1,0,1f))
    val row=LinearLayout(this)
    row.addView(Button(this).apply { text="Start capture fixture";setOnClickListener {
      startActivityForResult(getSystemService(MediaProjectionManager::class.java).createScreenCaptureIntent(),7)
    } },LinearLayout.LayoutParams(0,80,1f))
    row.addView(Button(this).apply { text="Show second specimen";setOnClickListener { second=true;page.invalidate() } },LinearLayout.LayoutParams(0,80,1f))
    layout.addView(row);setContentView(layout)
  }
  @Deprecated("Fixture uses the platform activity result API")
  override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?) {
    super.onActivityResult(requestCode,resultCode,data)
    if(requestCode==7 && resultCode==RESULT_OK && data!=null) startForegroundService(Intent(this,InventoryCaptureService::class.java)
      .setAction(InventoryCaptureService.START).putExtra("result",resultCode).putExtra("token",data))
  }
}
