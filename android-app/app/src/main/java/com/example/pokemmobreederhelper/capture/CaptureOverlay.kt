package com.example.pokemmobreederhelper.capture

import android.app.AlertDialog
import android.content.Context
import android.graphics.*
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.text.InputType
import android.view.*
import android.widget.*

/** Small non-focusable controls let the game receive touches everywhere outside the panel. */
internal class CaptureOverlay(private val context: Context, capture: () -> Unit, next: () -> Unit,
  pause: () -> Unit, settings: () -> Unit, locate: () -> Unit, stop: () -> Unit) {
  private val wm = context.getSystemService(WindowManager::class.java)
  private val prefs = context.getSharedPreferences("live-capture", Context.MODE_PRIVATE)
  private val root = LinearLayout(context).apply {
    orientation = LinearLayout.VERTICAL; setPadding(dp(10),dp(6),dp(10),dp(8))
    background = GradientDrawable().apply { setColor(Color.rgb(22,35,46)); cornerRadius = dp(14).toFloat(); setStroke(dp(1),Color.rgb(77,116,126)) }
    elevation = dp(8).toFloat()
  }
  private val header = text(13).apply { setTextColor(Color.rgb(103,231,198)); maxLines = 2; contentDescription = "拖动采集悬浮窗" }
  private val status = text(12).apply { maxLines = 3 }
  private val controls = LinearLayout(context).apply { orientation = LinearLayout.VERTICAL }
  private val params = WindowManager.LayoutParams(dp(320), -2, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL, PixelFormat.TRANSLUCENT).apply {
    gravity = Gravity.TOP or Gravity.START
    x = prefs.getInt("x",dp(12)); y = prefs.getInt("y",dp(80))
  }
  private var compact = false
  private var modal: AlertDialog? = null
  private var calibration: View? = null
  private var calibrationBitmap: Bitmap? = null
  private val pauseButton: Button
  init {
    val top = row()
    top.addView(header, LinearLayout.LayoutParams(0,-2,1f))
    top.addView(button("收起") { compact = !compact; controls.visibility = if (compact) View.GONE else View.VISIBLE
      status.visibility = if (compact) View.GONE else View.VISIBLE; (it as Button).text = if (compact) "展开" else "收起" }, LinearLayout.LayoutParams(dp(64),dp(48)))
    root.addView(top); root.addView(status); root.addView(controls)
    val first = row(); add(first, button("采集当前") { capture() }); add(first,button("下一只") { next() }); controls.addView(first)
    val second = row(); pauseButton=button("暂停") { pause() }; add(second,pauseButton); add(second,button("位置 / 模式") { settings() }); controls.addView(second)
    val third = row(); add(third,button("识别范围") { locate() }); add(third,button("结束采集") { stop() }); controls.addView(third)
    var downX=0f; var downY=0f; var originX=0; var originY=0
    header.setOnTouchListener { _, event ->
      when(event.actionMasked) {
        MotionEvent.ACTION_DOWN -> { downX=event.rawX;downY=event.rawY;originX=params.x;originY=params.y;true }
        MotionEvent.ACTION_MOVE -> { params.x=originX+(event.rawX-downX).toInt();params.y=originY+(event.rawY-downY).toInt();clamp();wm.updateViewLayout(root,params);true }
        MotionEvent.ACTION_UP -> { prefs.edit().putInt("x",params.x).putInt("y",params.y).apply();true }
        else -> false
      }
    }
    clamp(); wm.addView(root,params)
  }
  private fun dp(value:Int)=(value*context.resources.displayMetrics.density).toInt()
  private fun text(size:Int)=TextView(context).apply { textSize=size.toFloat();setTextColor(Color.WHITE);setPadding(dp(3),dp(3),dp(3),dp(3)) }
  private fun row()=LinearLayout(context).apply { orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL }
  private fun button(label:String,action:(View)->Unit)=Button(context).apply {
    text=label;textSize=12f;isAllCaps=false;minWidth=0;minimumWidth=0;minHeight=dp(48);minimumHeight=dp(48)
    setPadding(dp(3),0,dp(3),0);setOnClickListener(action)
  }
  private fun add(row:LinearLayout,view:View) { row.addView(view,LinearLayout.LayoutParams(0,dp(48),1f).apply { marginEnd=dp(4) }) }
  @Suppress("DEPRECATION") private fun size()=android.util.DisplayMetrics().also { wm.defaultDisplay.getRealMetrics(it) }
  fun screenWidth()=size().widthPixels
  fun screenHeight()=size().heightPixels
  private fun clamp() { params.width=minOf(dp(320),screenWidth()-dp(16));params.x=params.x.coerceIn(0,(screenWidth()-params.width).coerceAtLeast(0));params.y=params.y.coerceIn(0,(screenHeight()-maxOf(root.height,dp(80))).coerceAtLeast(0)) }
  fun bounds():Rect { val point=IntArray(2);root.getLocationOnScreen(point);return Rect(point[0],point[1],point[0]+root.width,point[1]+root.height) }
  fun render(title:String,message:String,paused:Boolean,automatic:Boolean) {
    header.text=title;status.text="${if(automatic) "自动" else "手动"} · $message";pauseButton.text=if(paused) "继续" else "暂停"
    clamp();runCatching { wm.updateViewLayout(root,params) }
  }

  fun configure(position:CapturePosition,automatic:Boolean,onDone:(CapturePosition,Boolean)->Unit,onClose:()->Unit) {
    val themed=ContextThemeWrapper(context,android.R.style.Theme_Material_Light_Dialog_Alert)
    val fields=LinearLayout(themed).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(20),dp(8),dp(20),dp(8)) }
    fun field(label:String,value:String,numeric:Boolean=false):EditText {
      fields.addView(TextView(themed).apply { text=label })
      return EditText(themed).apply { setText(value);setSingleLine();contentDescription=label
        inputType=if(numeric) InputType.TYPE_CLASS_NUMBER else InputType.TYPE_CLASS_TEXT
        fields.addView(this,LinearLayout.LayoutParams(-1,dp(48))) }
    }
    val account=field("用户名 / 角色",position.account)
    val box=field("仓库号",position.box.toString(),true)
    val slot=field("当前第几个",position.slot.toString(),true)
    val slots=field("每仓格数（满仓自动进入下一仓）",position.slotsPerBox.toString(),true)
    val auto=CheckBox(themed).apply { text="自动识别并保存新画面";isChecked=automatic };fields.addView(auto)
    fields.addView(TextView(themed).apply { text="位置按浏览顺序递增。跳格请修改位置；两只画面相同时手动点“下一只”。" })
    val scroll=ScrollView(themed).apply { addView(fields) }
    val dialog=AlertDialog.Builder(themed).setTitle("采集位置与模式").setView(scroll).setPositiveButton("保存",null).setNegativeButton("取消",null).create()
    dialog.window?.setType(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY)
    dialog.setOnDismissListener { modal=null;onClose() };modal=dialog;dialog.show()
    dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
      try { val value=CapturePosition(account.text.toString().trim(),box.text.toString().toInt(),slot.text.toString().toInt(),slots.text.toString().toInt())
        onDone(value,auto.isChecked);dialog.dismiss()
      } catch (_: IllegalArgumentException) { Toast.makeText(context,"用户名不能为空；仓库为正数，格位须在每仓格数范围内。",Toast.LENGTH_LONG).show() }
    }
  }

  fun calibrate(bitmap:Bitmap,current:RectF?,onDone:(RectF)->Unit,onClose:()->Unit) {
    calibrationBitmap=bitmap
    val panel=LinearLayout(context).apply { orientation=LinearLayout.VERTICAL;setBackgroundColor(Color.rgb(18,27,37)) }
    panel.addView(text(15).apply { text="拖动框选名字、性别和个体值区域；浮窗请放到框外" })
    val selector=RegionSelector(context,bitmap,current ?: RectF(0f,0f,1f,1f))
    panel.addView(selector,LinearLayout.LayoutParams(-1,0,1f))
    fun finish() { calibration?.let { runCatching { wm.removeView(it) } };calibration=null;calibrationBitmap?.recycle();calibrationBitmap=null;root.visibility=View.VISIBLE;onClose() }
    val buttons=row();add(buttons,button("使用全屏") { onDone(RectF(0f,0f,1f,1f));finish() });add(buttons,button("保存范围") { onDone(selector.selection);finish() });add(buttons,button("取消") { finish() });panel.addView(buttons)
    root.visibility=View.GONE;calibration=panel
    wm.addView(panel,WindowManager.LayoutParams(-1,-1,WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
      WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,PixelFormat.TRANSLUCENT))
  }
  fun close() { modal?.dismiss();calibration?.let { runCatching { wm.removeView(it) } };calibrationBitmap?.recycle();runCatching { wm.removeView(root) } }

  private class RegionSelector(context:Context,val bitmap:Bitmap,initial:RectF):View(context) {
    var selection=RectF(initial);private set
    private val imageRect=RectF();private val paint=Paint(Paint.ANTI_ALIAS_FLAG)
    private var startX=0f;private var startY=0f
    override fun onDraw(canvas:Canvas) {
      val scale=minOf(width.toFloat()/bitmap.width,height.toFloat()/bitmap.height)
      val w=bitmap.width*scale;val h=bitmap.height*scale
      imageRect.set((width-w)/2,(height-h)/2,(width+w)/2,(height+h)/2)
      canvas.drawBitmap(bitmap,null,imageRect,paint)
      paint.color=Color.GREEN;paint.style=Paint.Style.STROKE;paint.strokeWidth=4f
      canvas.drawRect(imageRect.left+selection.left*w,imageRect.top+selection.top*h,imageRect.left+selection.right*w,imageRect.top+selection.bottom*h,paint)
      paint.style=Paint.Style.FILL
    }
    override fun onTouchEvent(event:MotionEvent):Boolean {
      if(imageRect.width()<=0 || imageRect.height()<=0)return false
      val x=((event.x-imageRect.left)/imageRect.width()).coerceIn(0f,1f)
      val y=((event.y-imageRect.top)/imageRect.height()).coerceIn(0f,1f)
      when(event.actionMasked) {
        MotionEvent.ACTION_DOWN -> { startX=x;startY=y;return true }
        MotionEvent.ACTION_MOVE,MotionEvent.ACTION_UP -> {
          val rect=RectF(minOf(x,startX),minOf(y,startY),maxOf(x,startX),maxOf(y,startY))
          if(rect.width()>0.04f && rect.height()>0.04f)selection=rect
          invalidate();if(event.actionMasked==MotionEvent.ACTION_UP)performClick();return true
        }
      }
      return super.onTouchEvent(event)
    }
    override fun performClick():Boolean { super.performClick();return true }
  }
}
