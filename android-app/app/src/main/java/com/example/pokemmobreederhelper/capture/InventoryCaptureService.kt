package com.example.pokemmobreederhelper.capture

import android.app.*
import android.content.*
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.graphics.*
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.*
import android.provider.Settings
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import com.example.pokemmobreederhelper.MainActivity
import com.example.pokemmobreederhelper.R
import com.example.pokemmobreederhelper.data.*
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

internal data class LiveCaptureStatus(val running: Boolean = false, val paused: Boolean = false,
  val saved: Int = 0, val message: String = "", val minimized: Boolean = false, val hasPreview: Boolean = false,
  val reviewRevision: Int = 0)
internal object LiveCaptureState {
  val editing = AtomicBoolean(false)
  val mutable = MutableStateFlow(LiveCaptureStatus())
  val state = mutable.asStateFlow()
}

/** User-authorized screen session. Never reuses projection consent or controls the game. */
class InventoryCaptureService : Service() {
  private val main = Handler(Looper.getMainLooper())
  private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
  private val processing = AtomicBoolean(false)
  private val prefs by lazy { getSharedPreferences("live-capture", MODE_PRIVATE) }
  private val store by lazy { CaptureStore(this) }
  private val repository by lazy { InventoryRepository(this) }
  private val ocrProvider = lazy { CaptureOcr(PlannerBridge(this)) }
  private val ocr by ocrProvider
  private var projection: MediaProjection? = null
  private var display: VirtualDisplay? = null
  private var reader: ImageReader? = null
  private var overlay: CaptureOverlay? = null
  private var preview: Bitmap? = null
  private val previewLock = Any()
  private var cachedFrame: Bitmap? = null
  private var cachedRecognition: CaptureRecognition? = null
  private var region: RectF? = null
  private var width = 0
  private var height = 0
  private var generation = 0L
  private var visible = true
  private var finalMessage = "采集已结束，可到库存查看、修改或导出 JSON"
  private var closed = false
  private var interacting = false
  private var paused = false
  private var automatic = false
  private var pending: CaptureRecognition? = null
  private var pendingImage: Bitmap? = null
  private var saving = false
  private var saved = 0
  private val batch = UUID.randomUUID().toString()
  private val gate = LiveCaptureGate()
  private val partialGate = PartialCaptureGate()
  private var reviewRevision = 0
  private var reviewFrame: Bitmap? = null
  private var reviewId: String? = null
  private var reviewPosition: CapturePosition? = null
  private var pendingReviewId: String? = null
  private var pendingPosition: CapturePosition? = null
  private var position = CapturePosition("主账号", 1, 1)
  // Virtual displays may stop producing frames on a static detail page. Sample the
  // newest buffer periodically and recheck the retained frame to establish stability.
  private val sample = object : Runnable {
    override fun run() {
      if (closed) return
      reader?.let(::frame)
      main.postDelayed(this, 250L)
    }
  }

  override fun onBind(intent: Intent?) = null
  override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    if (intent?.action == STOP) { stopSelf(); return START_NOT_STICKY }
    if (projection != null) return START_NOT_STICKY
    try {
      require(intent?.action == START && Settings.canDrawOverlays(this)) { "请允许显示悬浮窗后重新开始。" }
      val token = if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra("token", Intent::class.java)
        else @Suppress("DEPRECATION") intent.getParcelableExtra("token") as? Intent
      require(token != null && intent.getIntExtra("result", 0) == Activity.RESULT_OK) { "需要重新授权屏幕采集。" }
      val nm = getSystemService(NotificationManager::class.java)
      nm.createNotificationChannel(NotificationChannel(CHANNEL, "库存实时采集", NotificationManager.IMPORTANCE_LOW))
      if (Build.VERSION.SDK_INT >= 29) startForeground(71, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
      else startForeground(71, notification())
      position = runCatching { CapturePosition(prefs.getString("account", "主账号")!!,
        prefs.getInt("box", 1), prefs.getInt("slot", 1), prefs.getInt("slots", 60)) }.getOrDefault(position)
      automatic = prefs.getBoolean("minimized", false)
      region = if (prefs.contains("left")) RectF(prefs.getFloat("left",0f), prefs.getFloat("top",0f),
        prefs.getFloat("right",1f), prefs.getFloat("bottom",1f)) else null
      overlay = CaptureOverlay(this, ::captureCurrent, ::nextSpecimen, ::togglePause, ::configure, ::calibrate, ::stopSelf,
        { confirmPreview(finish = true) }, ::changeMode)
      projection = getSystemService(MediaProjectionManager::class.java).getMediaProjection(Activity.RESULT_OK, token)
      projection!!.registerCallback(object : MediaProjection.Callback() {
        override fun onStop() { stopSelf() }
        override fun onCapturedContentResize(w: Int, h: Int) { if (!closed && w > 0 && h > 0) resize(w, h) }
        override fun onCapturedContentVisibilityChanged(isVisible: Boolean) {
          visible = isVisible
          generation++
          if (!visible) { gate.resetObservation(); message("游戏画面暂不可见，返回后继续") }
        }
      }, main)
      @Suppress("DEPRECATION") val metrics = android.util.DisplayMetrics().also {
        getSystemService(WindowManager::class.java).defaultDisplay.getRealMetrics(it)
      }
      width = metrics.widthPixels; height = metrics.heightPixels
      reader = makeReader(width, height)
      display = projection!!.createVirtualDisplay("InventoryCapture", width, height, metrics.densityDpi,
        DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, reader!!.surface, null, main)
      main.post(sample)
      message(if (automatic) "自动识别已开启，请打开精灵个体值页" else "打开精灵个体值页，识别后点下一只确认入库")
    } catch (error: Exception) {
      finalMessage = "无法开启采集：${error.message}"
      LiveCaptureState.mutable.value = LiveCaptureStatus(message = finalMessage)
      stopSelf()
    }
    return START_NOT_STICKY
  }

  override fun onConfigurationChanged(newConfig: Configuration) {
    super.onConfigurationChanged(newConfig)
    if (Build.VERSION.SDK_INT < 34 && projection != null) {
      @Suppress("DEPRECATION") val metrics = android.util.DisplayMetrics().also {
        getSystemService(WindowManager::class.java).defaultDisplay.getRealMetrics(it)
      }
      resize(metrics.widthPixels, metrics.heightPixels)
    }
  }

  private fun notification(): Notification {
    val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
    val stop = PendingIntent.getService(this, 1, Intent(this, javaClass).setAction(STOP), PendingIntent.FLAG_IMMUTABLE)
    return NotificationCompat.Builder(this, CHANNEL).setSmallIcon(R.mipmap.breeder_launcher)
      .setContentTitle("正在采集精灵库存").setContentText("识别结果保存在本机；点击停止可结束屏幕共享")
      .setContentIntent(open).addAction(0, "停止采集", stop).setOngoing(true).build()
  }

  private fun makeReader(w: Int, h: Int): ImageReader = ImageReader.newInstance(w, h, PixelFormat.RGBA_8888, 2)
  private fun resize(w: Int, h: Int) {
    if (w == width && h == height) return
    generation++; width = w; height = h; gate.resetObservation()
    val replacement = makeReader(w, h)
    val old = reader
    display?.surface = null
    display?.resize(w, h, resources.displayMetrics.densityDpi)
    display?.surface = replacement.surface
    reader = replacement; old?.close()
    synchronized(previewLock) { preview?.recycle(); preview = null }
    message("画面尺寸已调整，识别框按比例保留")
  }

  private fun frame(source: ImageReader) {
    if (closed || !visible || paused || interacting || saving || LiveCaptureState.editing.get() ||
      (!automatic && pending != null) || !processing.compareAndSet(false, true)) return
    val image = runCatching { source.acquireLatestImage() }.getOrNull()
    val now = SystemClock.elapsedRealtime(); val epoch = generation
    val bounds = overlay?.bounds()
    val fullDisplay = overlay?.screenWidth() == width && overlay?.screenHeight() == height
    val crop = region?.let { RectF(it) } ?: RectF(0f,0f,1f,1f)
    scope.launch {
      var cropped: Bitmap? = null
      var heldImage = image
      try {
        val bitmap = if(image==null) synchronized(previewLock) { preview?.copy(Bitmap.Config.ARGB_8888,true) }
        else {
          val frameWidth=image.width; val frameHeight=image.height
          val plane=image.planes[0]; val paddedWidth=plane.rowStride/plane.pixelStride
          val padded=Bitmap.createBitmap(paddedWidth,frameHeight,Bitmap.Config.ARGB_8888)
          padded.copyPixelsFromBuffer(plane.buffer)
          image.close(); heldImage = null
          val actual=Bitmap.createBitmap(padded,0,0,frameWidth,frameHeight)
          if(actual!==padded)padded.recycle()
          if(bounds!=null && fullDisplay) OverlayFrameMask.apply(actual,bounds)
          synchronized(previewLock) { preview?.recycle(); preview=actual.copy(Bitmap.Config.ARGB_8888,false) }
          actual
        }
        if(bitmap==null) return@launch
        val left=(crop.left*bitmap.width).toInt().coerceIn(0,bitmap.width-1)
        val top=(crop.top*bitmap.height).toInt().coerceIn(0,bitmap.height-1)
        val right=(crop.right*bitmap.width).toInt().coerceIn(left+1,bitmap.width)
        val bottom=(crop.bottom*bitmap.height).toInt().coerceIn(top+1,bitmap.height)
        val current=Bitmap.createBitmap(bitmap,left,top,right-left,bottom-top)
        cropped=current; if(current!==bitmap)bitmap.recycle()
        val result = if(cachedRecognition!=null && cachedFrame?.sameAs(current)==true) cachedRecognition!! else {
          val recognized=ocr.recognize(current)
          cachedFrame?.recycle(); cachedFrame=current.copy(Bitmap.Config.ARGB_8888,false)
          cachedRecognition=recognized; recognized
        }
        withContext(Dispatchers.Main) {
          if(!closed && epoch==generation && visible && !paused && !interacting && !saving &&
            !LiveCaptureState.editing.get() && pending==null) accept(result,current,now)
        }
      } catch (_: CancellationException) { }
      catch(error: Exception) {
        withContext(Dispatchers.Main) { if(!closed) { gate.failed();message("识别失败：${error.message}") } }
      } finally { heldImage?.close();cropped?.recycle();processing.set(false) }
    }
  }

  private suspend fun queueIncomplete(result: CaptureRecognition, bitmap: Bitmap) {
    val material=result.material ?: return
    val destination=position
    val child=material.copy(id=UUID.randomUUID().toString(),account=destination.account,
      page=destination.box.toString(),slot=destination.slot.toString(),source="mobile-live-review",verified=false)
    val draft=CaptureDraft(child,result.warnings,result.rawText,result.fingerprint,child.id+".jpg",
      "实时采集 · "+destination.account+" · 仓"+destination.box+" 第"+destination.slot+"个 · 待补资料",batch)
    saving=true
    try {
      withContext(Dispatchers.IO+NonCancellable) { store.append(draft,bitmap) }
      reviewFrame?.recycle();reviewFrame=bitmap.copy(Bitmap.Config.ARGB_8888,false)
      reviewId=child.id;reviewPosition=destination;reviewRevision++
      partialGate.committed(result.fingerprint)
      position=destination.next();persist(position)
      message("反复识别未完整，已转待审核；可继续切换下一只")
    } catch(error:Exception) { paused=true;message("待审核保存失败，已暂停：${error.message}") }
    finally { saving=false }
  }

  private suspend fun accept(result: CaptureRecognition, bitmap: Bitmap, now: Long) {
    val material = result.material
    if (LiveCaptureGate.key(material) == null) {
      gate.observe(null, now)
      if (material == null) partialGate.observe("", now)
      if (material != null && partialGate.observe(result.fingerprint, now)) {
        queueIncomplete(result, bitmap)
        return
      }
      message(if (material != null) "未完整："+material.species.ifBlank { "名称待确认" }+" · "+material.ivText+"；请保持详情页可见" else "等待精灵详情，请打开个体值页或重新定位")
      return
    }
    if (gate.isPrevious(material)) {
      gate.observe(material, now)
      message("与上一只资料相同，等待新的精灵画面")
      return
    }
    if (!gate.observe(material, now)) return
    pending = result
    if (reviewId != null && reviewFrame?.sameAs(bitmap) == true) {
      pendingReviewId = reviewId; pendingPosition = reviewPosition
    } else { pendingReviewId = null; pendingPosition = null }
    pendingImage?.recycle(); pendingImage = bitmap.copy(Bitmap.Config.ARGB_8888, false)
    if (automatic) savePending(false)
    else {
      overlay?.preview(material)
      message("请核对；点下一只确认入库，或保存并结束")
    }
  }

  private suspend fun savePending(finish: Boolean) {
    if (saving) return
    val result = pending ?: return
    val material = result.material ?: return
    val bitmap = pendingImage ?: return
    val destination = pendingPosition ?: position
    val key = LiveCaptureGate.key(material) ?: return
    val child = material.copy(id = pendingReviewId ?: UUID.randomUUID().toString(), account = destination.account,
      page = destination.box.toString(), slot = destination.slot.toString(), source = "mobile-live", verified = false,
      notes = "屏幕实时采集，尚未标记为已核对；请核对性别、性格、头目、梦特、技能与实际仓位。")
    val draft = CaptureDraft(child, result.warnings, result.rawText, key, child.id + ".jpg",
      "实时采集 · "+destination.account+" · 仓"+destination.box+" 第"+destination.slot+"个", batch)
    saving = true
    generation++
    message("正在保存，请稍候")
    try {
      // A stop during disk I/O still completes the inventory write and next-position metadata.
      withContext(NonCancellable) {
        val insertion = withContext(Dispatchers.IO) { repository.insertCapture(child) }
        if (insertion == CaptureInsertResult.SLOT_OCCUPIED) {
          withContext(Dispatchers.IO) { store.append(draft.copy(warnings = draft.warnings + "此仓位已有其他素材，未覆盖库存，请核对位置。"), bitmap) }
          paused = true
          gate.failed()
          message("仓位已有其他素材，已留草稿并暂停；请修改仓位后保存")
          return@withContext
        }
        saved++
        pendingReviewId?.let { id -> withContext(Dispatchers.IO) { store.remove(id) }; reviewRevision++ }
        gate.committed(material)
        if (pendingPosition == null) { position = destination.next(); persist(position) }
        pendingReviewId = null; pendingPosition = null
        reviewFrame?.recycle(); reviewFrame = null; reviewId = null; reviewPosition = null
        pending = null; pendingImage = null; bitmap.recycle()
        overlay?.preview(null)
        if (automatic) overlay?.showSaved(child)
        message(if (insertion == CaptureInsertResult.ADDED) "已入库；等待新的精灵画面" else "仓位已有相同记录，未重复入库；等待新画面")
        if (finish && !closed) stopSelf()
      }
    } catch (error: Exception) {
      gate.failed(); paused = true
      message("保存失败，当前预览已保留："+error.message)
    } finally {
      saving = false
      if (!closed) message(LiveCaptureState.state.value.message)
    }
  }

  private fun confirmPreview(finish: Boolean = false) {
    if (saving || interacting) { message("正在处理，请稍候"); return }
    if (pending == null) { message("等待新的识别结果，仓位不会提前跳格"); return }
    scope.launch(Dispatchers.Main) { savePending(finish) }
  }
  private fun captureCurrent() {
    if (saving || interacting) return
    pending = null; pendingImage?.recycle(); pendingImage = null
    overlay?.preview(null)
    paused = false; gate.resetObservation(); generation++
    message("重新识别当前画面，确认前不会入库")
  }
  private fun nextSpecimen() { confirmPreview() }
  private fun changeMode(minimized: Boolean): Boolean {
    if (saving || interacting) { message("正在处理，请稍候再切换"); return false }
    automatic = minimized; generation++; gate.resetObservation()
    if (minimized && pending != null && !paused) scope.launch(Dispatchers.Main) { savePending(false) }
    message(if (paused) "已暂停，点继续恢复" else if (minimized) "自动识别入库已开启" else "手动核对：识别后点下一只确认入库")
    return true
  }
  private fun togglePause() {
    paused = !paused; generation++; gate.resetObservation()
    overlay?.dismissPopup()
    message(if (paused) "已暂停，当前预览与库存保留" else "继续采集，请保持精灵详情可见")
    if (!paused && automatic && pending != null) scope.launch(Dispatchers.Main) { savePending(false) }
  }
  private fun configure() {
    if (saving) { message("正在保存，请稍候"); return }
    interacting = true; generation++
    val accounts = (repository.inventory.value.map { it.account } + prefs.getStringSet("accounts", emptySet()).orEmpty()).distinct().sorted()
    overlay?.configure(position, accounts, onDone = { value ->
      position = value
      persist(position)
      message(if (pending != null) "当前预览将保存到新仓位，请核对后点下一只" else "位置已更新，等待新的精灵画面")
    }, onClose = { interacting = false; gate.resetObservation() })
  }
  private fun calibrate() {
    if (saving) { message("正在保存，请稍候"); return }
    val frame = synchronized(previewLock) { preview?.copy(Bitmap.Config.ARGB_8888, false) }
    if (frame == null) { message("还没有画面，请先返回游戏"); return }
    interacting = true; generation++
    overlay?.calibrate(frame, region, onDone = { selected ->
      region = selected; gate.resetObservation()
      prefs.edit().putFloat("left", selected.left).putFloat("top",selected.top)
        .putFloat("right",selected.right).putFloat("bottom",selected.bottom).apply()
      message("识别范围已保存；请覆盖名字、性别与完整个体值")
    }, onClose = { interacting = false })
  }
  private fun persist(next: CapturePosition) {
    prefs.edit().putString("account",next.account).putInt("box",next.box).putInt("slot",next.slot)
      .putInt("slots",next.slotsPerBox)
      .putStringSet("accounts", prefs.getStringSet("accounts",emptySet()).orEmpty() + next.account).apply()
  }
  private fun message(text: String) {
    if (closed) return
    LiveCaptureState.mutable.value = LiveCaptureStatus(true, paused, saved, text, automatic, pending != null && !saving, reviewRevision)
    overlay?.render(position, saved, text, paused, pending != null && !saving)
  }
  override fun onDestroy() {
    closed = true; generation++
    main.removeCallbacks(sample)
    overlay?.close(); overlay = null
    val old = projection; projection = null
    display?.release(); display = null
    reader?.close(); reader = null
    old?.stop()
    synchronized(previewLock) { preview?.recycle(); preview = null }
    val job = scope.coroutineContext[Job]!!
    job.invokeOnCompletion {
      if (ocrProvider.isInitialized()) runCatching { ocr.close() }
      reviewFrame?.recycle();reviewFrame=null
      cachedFrame?.recycle(); cachedFrame = null; cachedRecognition = null
      pendingImage?.recycle(); pendingImage = null; pending = null
      LiveCaptureState.mutable.value = LiveCaptureStatus(saved = saved, message = finalMessage)
    }
    scope.cancel()
    stopForeground(STOP_FOREGROUND_REMOVE)
    super.onDestroy()
  }
  companion object {
    const val START = "com.example.pokemmobreederhelper.capture.START"
    const val STOP = "com.example.pokemmobreederhelper.capture.STOP"
    private const val CHANNEL = "inventory-screen-capture"
  }
}
