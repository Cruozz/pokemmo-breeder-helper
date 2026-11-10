package com.example.pokemmobreederhelper.capture

import android.app.AlertDialog
import android.content.Context
import android.content.SharedPreferences
import android.content.res.ColorStateList
import android.graphics.*
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.hardware.input.InputManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.text.InputType
import android.view.*
import android.widget.*
import com.example.pokemmobreederhelper.data.MonsterRecord
import kotlin.math.abs

internal object CaptureColors {
  val surface = Color.rgb(248,249,255)
  val ink = Color.rgb(36,50,74)
  val muted = Color.rgb(80,94,119)
  val accent = Color.rgb(79,70,229)
  val tint = Color.rgb(232,235,255)
  val border = Color.rgb(210,218,237)
  val danger = Color.rgb(166,42,66)
  val male = Color.rgb(30,91,184)
  val female = Color.rgb(185,46,110)
  val perfect = Color.rgb(22,117,58)
}

/** A small touchable control observes outside DOWN events without intercepting the game. */
internal class CaptureOverlay(private val context: Context, retry: () -> Unit, next: () -> Unit,
  pause: () -> Unit, settings: () -> Unit, locate: () -> Unit, stop: () -> Unit,
  finish: () -> Unit, private val modeChanged: (Boolean) -> Boolean) {
  private val themed = ContextThemeWrapper(context, com.example.pokemmobreederhelper.R.style.CaptureOverlayTheme)
  private val wm = context.getSystemService(WindowManager::class.java)
  private val prefs = context.getSharedPreferences("live-capture", Context.MODE_PRIVATE)
  private val stylePrefs = OverlayAppearance.preferences(context)
  private var appearance = OverlayAppearance.load(context)
  private val main = Handler(Looper.getMainLooper())
  private val retiredBounds = mutableListOf<Pair<Rect, Long>>()
  private val fontViews = mutableListOf<Pair<TextView, Int>>()
  private val root = object : LinearLayout(themed) {
    override fun dispatchTouchEvent(event: MotionEvent): Boolean {
      if (event.actionMasked == MotionEvent.ACTION_OUTSIDE) { dismissPopup(); return false }
      return super.dispatchTouchEvent(event)
    }
  }.apply { orientation = LinearLayout.VERTICAL; elevation = dp(3).toFloat() }
  private val header = text(10).apply {
    setTypeface(typeface, Typeface.BOLD); maxLines = 2; gravity = Gravity.CENTER_VERTICAL
    contentDescription = "拖动采集悬浮窗"
  }
  private val status = text(9).apply { setTextColor(CaptureColors.muted); maxLines = 3 }
  private val positionButton = button("选择账号与仓位") { settings() }
  private val result = CaptureResultView(themed).apply { visibility = View.GONE }
  private val panel = LinearLayout(themed).apply { orientation = LinearLayout.VERTICAL }
  private val scroll = ScrollView(themed).apply { isFillViewport = false; addView(panel) }
  private val top = row()
  private val bubble = button("自动") { changeMode(false) }.apply { contentDescription = "展开手动采集" }
  private val nextButton = button("下一只", true) { next() }
  private val finishButton = button("保存并结束") { finish() }
  private val pauseButton = button("暂停") { pause() }
  private val params = WindowManager.LayoutParams(dp(264), -2, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
      WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH, PixelFormat.TRANSLUCENT).apply {
    gravity = Gravity.TOP or Gravity.START; x = prefs.getInt("x",dp(12)); y = prefs.getInt("y",dp(48))
  }
  var minimized = prefs.getBoolean("minimized", false); private set
  private var attached = false
  private var modal: AlertDialog? = null
  private var calibration: View? = null
  private var calibrationBitmap: Bitmap? = null
  private var popup: CaptureResultView? = null
  private val hidePopup = Runnable { dismissPopup() }
  private val styleListener = SharedPreferences.OnSharedPreferenceChangeListener { _, _ ->
    main.post { appearance = OverlayAppearance.load(context); updateStyle() }
  }

  init {
    val minimize = ImageButton(themed).apply {
      contentDescription = "最小化自动采集"; background = ripple(CaptureColors.surface)
      setImageDrawable(object : android.graphics.drawable.Drawable() {
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = CaptureColors.accent; strokeWidth = dp(2).toFloat(); strokeCap = Paint.Cap.ROUND }
        override fun draw(canvas: Canvas) { canvas.drawLine(bounds.exactCenterX()-dp(6),bounds.exactCenterY(),bounds.exactCenterX()+dp(6),bounds.exactCenterY(),paint) }
        override fun setAlpha(alpha: Int) { paint.alpha = alpha }
        override fun setColorFilter(filter: ColorFilter?) { paint.colorFilter = filter }
        @Deprecated("Drawable opacity is unused") override fun getOpacity() = PixelFormat.TRANSLUCENT
      })
      setOnClickListener { changeMode(true) }
    }
    top.addView(header, LinearLayout.LayoutParams(0,dp(48),1f))
    top.addView(minimize, LinearLayout.LayoutParams(dp(48),dp(48)))
    root.addView(top); root.addView(scroll, LinearLayout.LayoutParams(-1,-2,1f))
    root.addView(bubble, LinearLayout.LayoutParams(-1,-1))
    panel.addView(positionButton,LinearLayout.LayoutParams(-1,dp(48)))
    panel.addView(result,LinearLayout.LayoutParams(-1,-2).apply { topMargin=dp(4); bottomMargin=dp(4) })
    panel.addView(status,LinearLayout.LayoutParams(-1,-2))
    val actions=row(); add(actions,nextButton); add(actions,finishButton); panel.addView(actions)
    val toolbar=row(); add(toolbar,button("重识别") { retry() }); add(toolbar,pauseButton); add(toolbar,button("范围") { locate() }.apply { contentDescription="识别范围" }); panel.addView(toolbar)
    panel.addView(button("结束采集") { stop() }.apply { setTextColor(CaptureColors.danger) },LinearLayout.LayoutParams(-1,dp(48)))
    draggable(header, false); draggable(bubble, true)
    updateStyle(false); wm.addView(root,params); attached=true
    stylePrefs.registerOnSharedPreferenceChangeListener(styleListener)
  }
  private fun dp(value:Int)=(value*context.resources.displayMetrics.density).toInt()
  private fun shape(color:Int,radius:Int=10)=GradientDrawable().apply { setColor(color);cornerRadius=dp(radius).toFloat() }
  private fun ripple(color:Int)=RippleDrawable(ColorStateList.valueOf(0x22504BE8),shape(color),null)
  private fun text(size:Int)=TextView(themed).apply {
    textSize=appearance.fontSp+(size-10);setTextColor(CaptureColors.ink);setPadding(dp(3),dp(2),dp(3),dp(2));fontViews.add(this to (size-10))
  }
  private fun row()=LinearLayout(themed).apply { orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL }
  private fun button(label:String,primary:Boolean=false,action:(View)->Unit)=Button(themed).apply {
    text=label;textSize=appearance.fontSp;isAllCaps=false;minWidth=0;minimumWidth=0;minHeight=dp(48);minimumHeight=dp(48)
    setTextColor(if(primary)Color.WHITE else CaptureColors.accent);background=ripple(if(primary)CaptureColors.accent else CaptureColors.tint)
    stateListAnimator=null;setPadding(dp(5),0,dp(5),0);setOnClickListener(action);fontViews.add(this to 0)
  }
  private fun add(row:LinearLayout,view:View) { row.addView(view,LinearLayout.LayoutParams(0,dp(48),1f).apply { marginEnd=dp(4);topMargin=dp(4) }) }
  private fun draggable(view: View, clickable: Boolean) {
    var downX=0f;var downY=0f;var originX=0;var originY=0;var moved=false
    val slop=ViewConfiguration.get(context).scaledTouchSlop
    view.setOnTouchListener { _,event ->
      when(event.actionMasked) {
        MotionEvent.ACTION_DOWN -> { downX=event.rawX;downY=event.rawY;originX=params.x;originY=params.y;moved=false;true }
        MotionEvent.ACTION_MOVE -> {
          if(abs(event.rawX-downX)>slop || abs(event.rawY-downY)>slop) moved=true
          if(moved) { retire(root);dismissPopup();params.x=originX+(event.rawX-downX).toInt();params.y=originY+(event.rawY-downY).toInt();layout() };true
        }
        MotionEvent.ACTION_UP -> { prefs.edit().putInt("x",params.x).putInt("y",params.y).apply();if(!moved && clickable)view.performClick();true }
        MotionEvent.ACTION_CANCEL -> true
        else -> false
      }
    }
  }
  private fun changeMode(value: Boolean) {
    if(value==minimized || !modeChanged(value)) return
    retire(root);dismissPopup();minimized=value;prefs.edit().putBoolean("minimized",value).apply();updateStyle()
  }
  private fun updateStyle(update: Boolean=true) {
    fontViews.forEach { (view,offset) -> view.textSize=(appearance.fontSp+offset).coerceAtLeast(8f) }
    result.font(appearance.fontSp);popup?.font(appearance.fontSp)
    top.visibility=if(minimized)View.GONE else View.VISIBLE;scroll.visibility=top.visibility
    bubble.visibility=if(minimized)View.VISIBLE else View.GONE
    root.setPadding(dp(if(minimized)0 else 8),0,dp(if(minimized)0 else 8),dp(if(minimized)0 else 6))
    root.background=shape(CaptureColors.surface,if(minimized)24 else 14).apply { setStroke(dp(1),CaptureColors.border) }
    bubble.background=ripple(CaptureColors.tint)
    params.alpha=appearance.opacity
    layout(update)
  }
  @Suppress("DEPRECATION") private fun size()=android.util.DisplayMetrics().also { wm.defaultDisplay.getRealMetrics(it) }
  fun screenWidth()=size().widthPixels
  fun screenHeight()=size().heightPixels
  private fun layout(update: Boolean=true) {
    val metrics=size()
    val maxHeight=(metrics.heightPixels-dp(32)).coerceAtLeast(dp(48))
    params.width=if(minimized)dp(48) else minOf(dp(appearance.panelWidth(context.resources.configuration.fontScale)),metrics.widthPixels-dp(16))
    params.height=if(minimized)dp(48) else if(!appearance.autoSize)minOf(dp(appearance.heightDp),maxHeight) else {
      root.measure(View.MeasureSpec.makeMeasureSpec(params.width,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED))
      root.measuredHeight.coerceIn(dp(48),maxHeight)
    }
    params.x=params.x.coerceIn(0,(metrics.widthPixels-params.width).coerceAtLeast(0))
    params.y=params.y.coerceIn(0,(metrics.heightPixels-params.height-dp(24)).coerceAtLeast(0))
    if(update && attached)runCatching { wm.updateViewLayout(root,params) }
  }
  private fun rect(view:View):Rect { val point=IntArray(2);view.getLocationOnScreen(point);return Rect(point[0]-dp(3),point[1]-dp(3),point[0]+view.width+dp(3),point[1]+view.height+dp(3)) }
  private fun retire(view:View) { if(view.width>0)retiredBounds.add(rect(view) to (SystemClock.elapsedRealtime()+1000)) }
  fun bounds():List<Rect> {
    retiredBounds.removeAll { it.second < SystemClock.elapsedRealtime() }
    return listOf(rect(root))+listOfNotNull(popup?.let(::rect))+retiredBounds.map { it.first }
  }
  fun render(position:CapturePosition,count:Int,message:String,paused:Boolean,hasPreview:Boolean) {
    header.text="手动 · 已存 "+count
    bubble.text=if(paused)"暂停" else "自动\n"+count
    positionButton.text=position.account+"  ·  仓 "+position.box+" / 格 "+position.slot
    positionButton.contentDescription="选择账号与仓位"
    status.text=message;status.contentDescription=message
    pauseButton.text=if(paused)"继续" else "暂停"
    nextButton.isEnabled=hasPreview;finishButton.isEnabled=hasPreview
    nextButton.alpha=if(hasPreview)1f else .5f;finishButton.alpha=nextButton.alpha
    layout()
  }
  fun preview(material:MonsterRecord?) {
    result.visibility=if(material==null)View.GONE else View.VISIBLE
    if(material!=null)result.show(material)
    layout()
  }
  fun showSaved(material:MonsterRecord) {
    if(!minimized)return
    dismissPopup()
    val view=CaptureResultView(themed).apply {
      font(appearance.fontSp);show(material);contentDescription="自动入库提示 · "+contentDescription;setPadding(dp(8),dp(6),dp(8),dp(6))
      background=shape(CaptureColors.surface,10).apply { setStroke(dp(1),CaptureColors.border) }
    }
    val maxOpacity=if(Build.VERSION.SDK_INT>=31)context.getSystemService(InputManager::class.java).maximumObscuringOpacityForTouch else 1f
    val p=WindowManager.LayoutParams(minOf(dp((220*appearance.fontSp/10).toInt()),screenWidth()-dp(16)),-2,
      WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
        WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,PixelFormat.TRANSLUCENT).apply {
      gravity=Gravity.TOP or Gravity.START;alpha=minOf(appearance.opacity,maxOpacity)
      x=if(params.x+params.width+width<=screenWidth())params.x+params.width else (params.x-width).coerceAtLeast(0)
      view.measure(View.MeasureSpec.makeMeasureSpec(width,View.MeasureSpec.EXACTLY),View.MeasureSpec.makeMeasureSpec(0,View.MeasureSpec.UNSPECIFIED))
      y=params.y.coerceIn(0,(screenHeight()-view.measuredHeight-dp(24)).coerceAtLeast(0))
      // On narrow screens place it below the bubble to avoid combined overlay opacity.
      if(x<params.x+params.width && x+width>params.x) {
        y=if(params.y+params.height+dp(4)+view.measuredHeight<=screenHeight()-dp(24))params.y+params.height+dp(4)
          else (params.y-view.measuredHeight-dp(4)).coerceAtLeast(0)
      }
    }
    popup=view;wm.addView(view,p);main.postDelayed(hidePopup,5000)
  }
  fun dismissPopup() {
    main.removeCallbacks(hidePopup)
    popup?.let { retire(it);runCatching { wm.removeView(it) } };popup=null
  }

  fun configure(position:CapturePosition,accounts:List<String>,
    onDone:(CapturePosition)->Unit,onClose:()->Unit) {
    val fields=LinearLayout(themed).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(20),dp(4),dp(20),dp(12)) }
    fun label(value:String) { fields.addView(text(10).apply { text=value;setTypeface(typeface,Typeface.BOLD) }) }
    label("选择用户名，或填写新用户名")
    val account=EditText(themed).apply { setText(position.account);textSize=appearance.fontSp+2;isSingleLine=true;contentDescription="用户名 / 角色";inputType=InputType.TYPE_CLASS_TEXT }
    val choices=row()
    val accountButtons=mutableListOf<Button>()
    (listOf(position.account)+accounts).map { it.trim() }.filter { it.isNotBlank() }.distinct().forEach { name ->
      val choice=button(name) { account.setText(name);account.setSelection(name.length)
        accountButtons.forEach { it.background=ripple(if(it.text.toString()==name) CaptureColors.accent else CaptureColors.tint);it.setTextColor(if(it.text.toString()==name) Color.WHITE else CaptureColors.accent) } }
      choice.textSize=appearance.fontSp;choice.contentDescription="选择用户名 "+name
      if(name==position.account) { choice.background=ripple(CaptureColors.accent);choice.setTextColor(Color.WHITE) }
      accountButtons.add(choice);choices.addView(choice,LinearLayout.LayoutParams(-2,dp(44)).apply { marginEnd=dp(6) })
    }
    fields.addView(HorizontalScrollView(themed).apply { isHorizontalScrollBarEnabled=true;addView(choices) })
    val accountRow=row()
    accountRow.addView(text(10).apply { text="用户名" },LinearLayout.LayoutParams(dp(54),dp(44)))
    account.hint="输入新用户名"
    accountRow.addView(account,LinearLayout.LayoutParams(0,dp(44),1f));fields.addView(accountRow)
    val positions=row()
    fun number(label:String,description:String,value:Int):EditText {
      val column=LinearLayout(themed).apply { orientation=LinearLayout.VERTICAL }
      column.addView(text(10).apply { text=label })
      val field=EditText(themed).apply { textSize=appearance.fontSp+4;setText(value.toString());inputType=InputType.TYPE_CLASS_NUMBER;isSingleLine=true;contentDescription=description }
      column.addView(field,LinearLayout.LayoutParams(-1,dp(48)));positions.addView(column,LinearLayout.LayoutParams(0,-2,1f).apply { marginEnd=dp(10) });return field
    }
    val box=number("仓库页","仓库号",position.box);val slot=number("仓库格","当前第几个",position.slot)
    val slots=number("每页格数","每仓格数",position.slotsPerBox);fields.addView(positions)
    fields.addView(text(9).apply { text="最小化时自动入库；展开后先预览，点下一只确认入库。相同资料会继续等待新画面。跳格请在这里修改位置。";setTextColor(CaptureColors.muted) })
    val error=text(10).apply { setTextColor(CaptureColors.danger);visibility=View.GONE };fields.addView(error)
    val dialog=AlertDialog.Builder(themed).setCustomTitle(text(14).apply { text="账号与仓位";setTypeface(typeface,Typeface.BOLD);setPadding(dp(20),dp(12),dp(20),dp(8)) }).setView(ScrollView(themed).apply { addView(fields) })
      .setPositiveButton("保存",null).setNegativeButton("取消",null).create()
    dialog.window?.setType(WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY)
    dialog.setOnDismissListener { modal=null;onClose() };modal=dialog;dialog.show()
    dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
      try {
        val value=CapturePosition(account.text.toString().trim(),box.text.toString().toInt(),slot.text.toString().toInt(),slots.text.toString().toInt())
        onDone(value);dialog.dismiss()
      } catch (_:IllegalArgumentException) { error.text="用户名不能为空；页数为正数，格位须在每页格数范围内。";error.visibility=View.VISIBLE }
    }
  }

  fun calibrate(bitmap:Bitmap,current:RectF?,onDone:(RectF)->Unit,onClose:()->Unit) {
    calibrationBitmap=bitmap
    val panel=LinearLayout(themed).apply { orientation=LinearLayout.VERTICAL;setPadding(dp(12),dp(8),dp(12),dp(8));setBackgroundColor(CaptureColors.surface) }
    panel.addView(text(11).apply { text="框选名字、性别和六项个体值；浮窗请放到框外" })
    val selector=RegionSelector(themed,bitmap,current ?: RectF(0f,0f,1f,1f))
    panel.addView(selector,LinearLayout.LayoutParams(-1,0,1f))
    fun finish() { calibration?.let { runCatching { wm.removeView(it) } };calibration=null;calibrationBitmap?.recycle();calibrationBitmap=null;root.visibility=View.VISIBLE;onClose() }
    val buttons=row();add(buttons,button("使用全屏") { onDone(RectF(0f,0f,1f,1f));finish() });add(buttons,button("保存范围",true) { onDone(selector.selection);finish() });add(buttons,button("取消") { finish() });panel.addView(buttons)
    root.visibility=View.GONE;calibration=panel
    wm.addView(panel,WindowManager.LayoutParams(-1,-1,WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
      WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE,PixelFormat.TRANSLUCENT))
  }
  fun close() {
    stylePrefs.unregisterOnSharedPreferenceChangeListener(styleListener)
    main.removeCallbacksAndMessages(null); dismissPopup()
    modal?.dismiss(); calibration?.let { runCatching { wm.removeView(it) } }
    calibrationBitmap?.recycle(); runCatching { wm.removeView(root) }
  }

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
