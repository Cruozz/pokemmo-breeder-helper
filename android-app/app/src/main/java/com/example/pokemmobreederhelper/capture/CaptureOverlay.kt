package com.example.pokemmobreederhelper.capture

import android.app.AlertDialog
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.*
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.text.InputType
import android.view.*
import android.widget.*

internal object CaptureColors {
  val surface = Color.rgb(248,249,255)
  val ink = Color.rgb(36,50,74)
  val muted = Color.rgb(80,94,119)
  val accent = Color.rgb(79,70,229)
  val tint = Color.rgb(232,235,255)
  val border = Color.rgb(210,218,237)
  val danger = Color.rgb(166,42,66)
}

/** The game keeps receiving touches outside this compact, non-focusable panel. */
internal class CaptureOverlay(private val context: Context, capture: () -> Unit, next: () -> Unit,
  pause: () -> Unit, settings: () -> Unit, locate: () -> Unit, stop: () -> Unit) {
  private val themed = ContextThemeWrapper(context, com.example.pokemmobreederhelper.R.style.CaptureOverlayTheme)
  private val wm = context.getSystemService(WindowManager::class.java)
  private val prefs = context.getSharedPreferences("live-capture", Context.MODE_PRIVATE)
  private val root = LinearLayout(themed).apply {
    orientation = LinearLayout.VERTICAL; setPadding(dp(10),dp(4),dp(10),dp(8))
    background = shape(CaptureColors.surface, 18).apply { setStroke(dp(1),CaptureColors.border) }
    elevation = dp(6).toFloat()
  }
  private val header = text(12).apply { setTypeface(typeface,Typeface.BOLD); maxLines=2; contentDescription="拖动采集悬浮窗" }
  private val status = text(11).apply { setTextColor(CaptureColors.muted); maxLines=3 }
  private val positionButton = button("选择账号与仓位") { settings() }
  private val controls = LinearLayout(themed).apply { orientation=LinearLayout.VERTICAL }
  private val compactNext = button("下一只") { next() }
  private val params = WindowManager.LayoutParams(dp(288), -2, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL, PixelFormat.TRANSLUCENT).apply {
    gravity=Gravity.TOP or Gravity.START; x=prefs.getInt("x",dp(12)); y=prefs.getInt("y",dp(80))
  }
  private var compact = prefs.getBoolean("compact",false)
  private var modal: AlertDialog? = null
  private var calibration: View? = null
  private var calibrationBitmap: Bitmap? = null
  private val pauseButton: Button
  private val toggle = ImageButton(themed).apply {
    background=ripple(CaptureColors.surface); setPadding(dp(12),dp(12),dp(12),dp(12))
    setOnClickListener { compact=!compact; prefs.edit().putBoolean("compact",compact).apply(); applyCompact() }
  }
  init {
    val top=row(); top.addView(header,LinearLayout.LayoutParams(0,dp(44),1f)); top.addView(toggle,LinearLayout.LayoutParams(dp(44),dp(44)))
    header.gravity=Gravity.CENTER_VERTICAL
    root.addView(top); root.addView(positionButton,LinearLayout.LayoutParams(-1,dp(44)))
    root.addView(status,LinearLayout.LayoutParams(-1,-2).apply { topMargin=dp(3);bottomMargin=dp(3) })
    root.addView(controls);root.addView(compactNext,LinearLayout.LayoutParams(-1,dp(44)))
    val first=row();add(first,button("采集当前",true) { capture() });add(first,button("下一只",true) { next() });controls.addView(first)
    val toolbar=row();pauseButton=button("暂停") { pause() };add(toolbar,pauseButton)
    add(toolbar,button("识别范围") { locate() });add(toolbar,button("结束采集") { stop() }.apply { setTextColor(CaptureColors.danger) })
    controls.addView(toolbar,LinearLayout.LayoutParams(-1,-2).apply { topMargin=dp(6) })
    var downX=0f;var downY=0f;var originX=0;var originY=0
    header.setOnTouchListener { _,event ->
      when(event.actionMasked) {
        MotionEvent.ACTION_DOWN -> { downX=event.rawX;downY=event.rawY;originX=params.x;originY=params.y;true }
        MotionEvent.ACTION_MOVE -> { params.x=originX+(event.rawX-downX).toInt();params.y=originY+(event.rawY-downY).toInt();clamp();wm.updateViewLayout(root,params);true }
        MotionEvent.ACTION_UP -> { prefs.edit().putInt("x",params.x).putInt("y",params.y).apply();header.performClick();true }
        else -> false
      }
    }
    applyCompact(false);clamp();wm.addView(root,params)
  }
  private fun dp(value:Int)=(value*context.resources.displayMetrics.density).toInt()
  private fun shape(color:Int,radius:Int=10)=GradientDrawable().apply { setColor(color);cornerRadius=dp(radius).toFloat() }
  private fun ripple(color:Int)=RippleDrawable(ColorStateList.valueOf(0x22504BE8),shape(color),null)
  private fun text(size:Int)=TextView(themed).apply { textSize=size.toFloat();setTextColor(CaptureColors.ink);setPadding(dp(3),dp(3),dp(3),dp(3)) }
  private fun row()=LinearLayout(themed).apply { orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL }
  private fun button(label:String,primary:Boolean=false,action:(View)->Unit)=Button(themed).apply {
    text=label;textSize=11f;isAllCaps=false;minWidth=0;minimumWidth=0;minHeight=dp(44);minimumHeight=dp(44)
    setTextColor(if(primary) Color.WHITE else CaptureColors.accent);backgroundTintList=null
    background=ripple(if(primary) CaptureColors.accent else CaptureColors.tint)
    stateListAnimator=null;setPadding(dp(8),0,dp(8),0);setOnClickListener(action)
  }
  private fun add(row:LinearLayout,view:View) { row.addView(view,LinearLayout.LayoutParams(0,dp(44),1f).apply { marginEnd=dp(4) }) }
  private fun applyCompact(update:Boolean=true) {
    controls.visibility=if(compact) View.GONE else View.VISIBLE;compactNext.visibility=if(compact) View.VISIBLE else View.GONE
    status.maxLines=if(compact) 1 else 3
    toggle.contentDescription=if(compact) "展开采集控制" else "收起采集控制"
    toggle.setImageDrawable(object:android.graphics.drawable.Drawable() {
      override fun draw(canvas:Canvas) {
        val paint=Paint(Paint.ANTI_ALIAS_FLAG).apply { color=CaptureColors.accent;style=Paint.Style.STROKE;strokeWidth=dp(2).toFloat();strokeCap=Paint.Cap.ROUND;strokeJoin=Paint.Join.ROUND }
        val x=bounds.exactCenterX();val y=bounds.exactCenterY();val d=dp(5).toFloat();val sign=if(compact) 1 else -1
        canvas.drawPath(Path().apply { moveTo(x-d,y-sign*d/2);lineTo(x,y+sign*d/2);lineTo(x+d,y-sign*d/2) },paint)
      }
      override fun setAlpha(alpha:Int) {}
      override fun setColorFilter(colorFilter:ColorFilter?) {}
      @Deprecated("Drawable opacity is unused") override fun getOpacity()=PixelFormat.TRANSLUCENT
    })
    if(update) { clamp();wm.updateViewLayout(root,params) }
  }
  @Suppress("DEPRECATION") private fun size()=android.util.DisplayMetrics().also { wm.defaultDisplay.getRealMetrics(it) }
  fun screenWidth()=size().widthPixels
  fun screenHeight()=size().heightPixels
  private fun clamp() { params.width=minOf(dp(if(compact)244 else 288),screenWidth()-dp(16));params.x=params.x.coerceIn(0,(screenWidth()-params.width).coerceAtLeast(0));params.y=params.y.coerceIn(0,(screenHeight()-maxOf(root.height,dp(80))).coerceAtLeast(0)) }
  fun bounds():Rect { val point=IntArray(2);root.getLocationOnScreen(point);return Rect(point[0],point[1],point[0]+root.width,point[1]+root.height) }
  fun render(position:CapturePosition,count:Int,message:String,paused:Boolean,automatic:Boolean) {
    header.text="库存采集 · 已存 "+count
    positionButton.text=position.account+"  ·  仓 "+position.box+" / 格 "+position.slot
    positionButton.contentDescription="选择账号与仓位"
    status.text=(if(paused) "已暂停" else if(automatic) "自动" else "手动")+" · "+message
    status.contentDescription=status.text;pauseButton.text=if(paused) "继续" else "暂停"
    clamp();runCatching { wm.updateViewLayout(root,params) }
  }

  fun configure(position:CapturePosition,automatic:Boolean,direct:Boolean,accounts:List<String>,
    onDone:(CapturePosition,Boolean,Boolean)->Unit,onClose:()->Unit) {
    val fields=LinearLayout(themed).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(20),dp(4),dp(20),dp(12)) }
    fun label(value:String) { fields.addView(text(12).apply { text=value;setTypeface(typeface,Typeface.BOLD) }) }
    label("选择用户名，或填写新用户名")
    val account=EditText(themed).apply { setText(position.account);textSize=14f;isSingleLine=true;contentDescription="用户名 / 角色";inputType=InputType.TYPE_CLASS_TEXT }
    val choices=row()
    val accountButtons=mutableListOf<Button>()
    (listOf(position.account)+accounts).map { it.trim() }.filter { it.isNotBlank() }.distinct().forEach { name ->
      val choice=button(name) { account.setText(name);account.setSelection(name.length)
        accountButtons.forEach { it.background=ripple(if(it.text.toString()==name) CaptureColors.accent else CaptureColors.tint);it.setTextColor(if(it.text.toString()==name) Color.WHITE else CaptureColors.accent) } }
      choice.textSize=12f;choice.contentDescription="选择用户名 "+name
      if(name==position.account) { choice.background=ripple(CaptureColors.accent);choice.setTextColor(Color.WHITE) }
      accountButtons.add(choice);choices.addView(choice,LinearLayout.LayoutParams(-2,dp(44)).apply { marginEnd=dp(6) })
    }
    fields.addView(HorizontalScrollView(themed).apply { isHorizontalScrollBarEnabled=true;addView(choices) })
    val accountRow=row()
    accountRow.addView(text(12).apply { text="用户名" },LinearLayout.LayoutParams(dp(54),dp(44)))
    account.hint="输入新用户名"
    accountRow.addView(account,LinearLayout.LayoutParams(0,dp(44),1f));fields.addView(accountRow)
    val positions=row()
    fun number(label:String,description:String,value:Int):EditText {
      val column=LinearLayout(themed).apply { orientation=LinearLayout.VERTICAL }
      column.addView(text(12).apply { text=label })
      val field=EditText(themed).apply { textSize=16f;setText(value.toString());inputType=InputType.TYPE_CLASS_NUMBER;isSingleLine=true;contentDescription=description }
      column.addView(field,LinearLayout.LayoutParams(-1,dp(48)));positions.addView(column,LinearLayout.LayoutParams(0,-2,1f).apply { marginEnd=dp(10) });return field
    }
    val box=number("仓库页","仓库号",position.box);val slot=number("仓库格","当前第几个",position.slot)
    val slots=number("每页格数","每仓格数",position.slotsPerBox);fields.addView(positions)
    val auto=CheckBox(themed).apply { text="自动识别并保存新画面";textSize=12f;minHeight=dp(48);isChecked=automatic }
    val intoInventory=CheckBox(themed).apply { text="识别后直接入库";textSize=12f;minHeight=dp(48);isChecked=direct }
    val modes=row();modes.addView(auto,LinearLayout.LayoutParams(0,-2,1f));modes.addView(intoInventory,LinearLayout.LayoutParams(0,-2,1f));fields.addView(modes)
    fields.addView(text(11).apply { text="直接入库标为待确认，可在库存修改并导出 JSON。缺少名称或个体值时保留草稿。跳格请修改位置；同种同 IV 精灵点“下一只”。";setTextColor(CaptureColors.muted) })
    val error=text(12).apply { setTextColor(CaptureColors.danger);visibility=View.GONE };fields.addView(error)
    val dialog=AlertDialog.Builder(themed).setCustomTitle(text(16).apply { text="账号与仓位";setTypeface(typeface,Typeface.BOLD);setPadding(dp(20),dp(12),dp(20),dp(8)) }).setView(ScrollView(themed).apply { addView(fields) })
      .setPositiveButton("保存",null).setNegativeButton("取消",null).create()
    dialog.window?.setType(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY)
    dialog.setOnDismissListener { modal=null;onClose() };modal=dialog;dialog.show()
    dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
      try {
        val value=CapturePosition(account.text.toString().trim(),box.text.toString().toInt(),slot.text.toString().toInt(),slots.text.toString().toInt())
        onDone(value,auto.isChecked,intoInventory.isChecked);dialog.dismiss()
      } catch (_:IllegalArgumentException) { error.text="用户名不能为空；页数为正数，格位须在每页格数范围内。";error.visibility=View.VISIBLE }
    }
  }

  fun calibrate(bitmap:Bitmap,current:RectF?,onDone:(RectF)->Unit,onClose:()->Unit) {
    calibrationBitmap=bitmap
    val panel=LinearLayout(themed).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(12),dp(8),dp(12),dp(8));setBackgroundColor(CaptureColors.surface) }
    panel.addView(text(13).apply { text="框选名字、性别和六项个体值；浮窗请放到框外" })
    val selector=RegionSelector(themed,bitmap,current ?: RectF(0f,0f,1f,1f))
    panel.addView(selector,LinearLayout.LayoutParams(-1,0,1f))
    fun finish() { calibration?.let { runCatching { wm.removeView(it) } };calibration=null;calibrationBitmap?.recycle();calibrationBitmap=null;root.visibility=View.VISIBLE;onClose() }
    val buttons=row();add(buttons,button("使用全屏") { onDone(RectF(0f,0f,1f,1f));finish() });add(buttons,button("保存范围",true) { onDone(selector.selection);finish() });add(buttons,button("取消") { finish() });panel.addView(buttons)
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
      paint.color=CaptureColors.accent;paint.style=Paint.Style.STROKE;paint.strokeWidth=4f
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
