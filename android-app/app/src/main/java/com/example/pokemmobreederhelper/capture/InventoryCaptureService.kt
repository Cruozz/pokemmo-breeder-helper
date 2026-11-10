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
  val saved: Int = 0, val message: String = "")
internal object LiveCaptureState {
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
  private val ocrProvider = lazy { CaptureOcr(PlannerBridge(this)) }
  private val ocr by ocrProvider
  private var projection: MediaProjection? = null
  private var display: VirtualDisplay? = null
  private var reader: ImageReader? = null
  private var overlay: CaptureOverlay? = null
  private var preview: Bitmap? = null
  private var region: RectF? = null
  private var width = 0
  private var height = 0
  private var generation = 0L
  private var visible = true
  private var finalMessage = "采集已结束，已保存结果可回助手核对"
  private var closed = false
  private var interacting = false
  private var paused = false
  private var automatic = true
  private var requested = false
  private var hasSavedAtPosition = false
  private var saving = false
  private var queuedNext = false
  private var saved = 0
  private val batch = UUID.randomUUID().toString()
  private val gate = LiveCaptureGate()
  private var position = CapturePosition("主账号", 1, 1)
  // Virtual displays may stop producing frames on a static detail page. Sample the
  // newest buffer periodically and recheck the retained frame to establish stability.
  private val sample = object : Runnable {
    override fun run() {
      if (closed) return
      reader?.let(::frame)
      main.postDelayed(this, 650L)
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
      automatic = prefs.getBoolean("auto", true)
      region = if (prefs.contains("left")) RectF(prefs.getFloat("left",0f), prefs.getFloat("top",0f),
        prefs.getFloat("right",1f), prefs.getFloat("bottom",1f)) else null
      overlay = CaptureOverlay(this, ::captureCurrent, ::nextSpecimen, ::togglePause, ::configure, ::calibrate, ::stopSelf)
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
      message("请设置用户名和位置，回游戏打开个体值页；每只停留约 2 秒")
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
      .setContentTitle("正在采集精灵库存").setContentText("结果自动保存为待核对素材；点击停止可结束屏幕共享")
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
    preview?.recycle(); preview = null
    message("画面尺寸已调整，识别框按比例保留")
  }

  private fun frame(source: ImageReader) {
    if (closed || !visible || paused || interacting || !processing.compareAndSet(false, true)) return
    val image = runCatching { source.acquireLatestImage() }.getOrNull()
    val now = SystemClock.elapsedRealtime()
    val epoch = generation
    val bitmap = try {
      if (image == null) preview?.copy(Bitmap.Config.ARGB_8888, true)
      else {
        val plane = image.planes[0]
        val paddedWidth = plane.rowStride / plane.pixelStride
        val padded = Bitmap.createBitmap(paddedWidth, image.height, Bitmap.Config.ARGB_8888)
        padded.copyPixelsFromBuffer(plane.buffer)
        val actual = Bitmap.createBitmap(padded, 0, 0, image.width, image.height)
        if (actual !== padded) padded.recycle()
        // Mask our floating controls only when sharing the entire display.
        val bounds = overlay?.bounds()
        if (bounds != null && actual.width == overlay?.screenWidth() && actual.height == overlay?.screenHeight()) {
          Canvas(actual).drawRect(bounds, Paint().apply { color = Color.BLACK })
        }
        preview?.recycle(); preview = actual.copy(Bitmap.Config.ARGB_8888, false)
        actual
      }
    } catch (error: Exception) { message("画面读取失败：${error.message}"); null }
    finally { image?.close() }
    if (bitmap == null) { processing.set(false); return }
    val crop = region ?: RectF(0f, 0f, 1f, 1f)
    val left = (crop.left * bitmap.width).toInt().coerceIn(0, bitmap.width-1)
    val top = (crop.top * bitmap.height).toInt().coerceIn(0, bitmap.height-1)
    val right = (crop.right * bitmap.width).toInt().coerceIn(left+1, bitmap.width)
    val bottom = (crop.bottom * bitmap.height).toInt().coerceIn(top+1, bitmap.height)
    val cropped = Bitmap.createBitmap(bitmap, left, top, right-left, bottom-top)
    if (cropped !== bitmap) bitmap.recycle()
    scope.launch {
      try {
        val result = ocr.recognize(cropped)
        withContext(Dispatchers.Main) {
          if (!closed && epoch == generation && visible && !paused && !interacting) accept(result, cropped, now)
        }
      } catch (_: CancellationException) { }
      catch (error: Exception) { withContext(Dispatchers.Main) { if (!closed) { gate.failed(); message("识别失败：${error.message}") } } }
      finally { cropped.recycle(); processing.set(false) }
    }
  }

  private suspend fun accept(result: CaptureRecognition, bitmap: Bitmap, now: Long) {
    val material = result.material
    val key = LiveCaptureGate.key(material)
    if (key == null) {
      gate.observe(null, now)
      message(if (material != null) "已读到${material.species.ifBlank { "精灵" }}，等待完整六项个体值；可用“采集当前”保留部分资料" else "等待精灵详情，请打开个体值页或重新定位")
      if (requested && material != null) save(result, bitmap, "partial:${material.id}", false)
      return
    }
    if (!(automatic || requested)) { message("已识别 ${material!!.species} · ${material.ivText}，点击采集当前保存"); return }
    if (!gate.observe(key, now)) return
    save(result, bitmap, key, true)
  }

  private suspend fun save(result: CaptureRecognition, bitmap: Bitmap, key: String, stable: Boolean) {
    val material = result.material ?: return
    val destination = if (hasSavedAtPosition) position.next() else position
    val child = material.copy(account = destination.account, page = destination.box.toString(), slot = destination.slot.toString(),
      source = "mobile-live", verified = false, notes = "屏幕实时采集；位置按采集顺序填写，请核对实际仓库格位。")
    val draft = CaptureDraft(child, result.warnings, result.rawText, key, child.id + ".jpg",
      "实时采集 · ${destination.account} · 仓${destination.box} 第${destination.slot}个", batch)
    saving = true
    try {
      // Keep both the durable draft and next-position metadata consistent if stopped during I/O.
      withContext(NonCancellable) {
        withContext(Dispatchers.IO) { store.append(draft, bitmap) }
        position = destination; hasSavedAtPosition = true; requested = false; saved++
        if (stable) gate.committed(key) else { gate.next(); paused = true }
        persist(position.next())
        message("已保存 ${child.species.ifBlank { "待确认精灵" }} · ${child.ivText}；${if (stable) "可以切换下一只" else "部分资料已保存，继续前请点击下一只"}")
      }
    } catch (error: Exception) { gate.failed(); paused = true; queuedNext = false; message("保存失败，采集已暂停：${error.message}") }
    finally {
      saving = false
      if (queuedNext && !closed) { queuedNext = false; nextSpecimen() }
    }
  }

  private fun captureCurrent() {
    if (saving || interacting) { message("正在保存，请稍候再操作"); return }
    if (hasSavedAtPosition) { message("本只已保存；另一只属性相同的精灵请点“下一只”"); return }
    requested = true; paused = false; gate.next(); generation++; message("等待当前画面稳定后保存")
  }
  private fun nextSpecimen() {
    if (saving) { queuedNext = true; message("本只保存后切换下一只"); return }
    if (interacting) return
    position = position.next(); hasSavedAtPosition = false; requested = true; paused = false
    gate.next(); generation++; persist(position); message("已切到仓${position.box} 第${position.slot}个，等待游戏画面")
  }
  private fun togglePause() {
    paused = !paused; generation++; message(if (paused) "已暂停，已保存结果保留" else "继续采集，请保持精灵详情可见")
  }
  private fun configure() {
    if (saving) { message("正在保存，请稍候"); return }
    interacting = true; generation++
    overlay?.configure(position, automatic, onDone = { value, auto ->
      val changed = value != position
      position = value; automatic = auto
      if (changed) { gate.next(); hasSavedAtPosition = false }
      persist(position); message("位置已更新 · ${if (automatic) "自动采集" else "手动采集"}")
    }, onClose = { interacting = false })
  }
  private fun calibrate() {
    if (saving) { message("正在保存，请稍候"); return }
    val frame = preview?.copy(Bitmap.Config.ARGB_8888, false)
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
      .putInt("slots",next.slotsPerBox).putBoolean("auto",automatic).apply()
  }
  private fun message(text: String) {
    if (closed) return
    LiveCaptureState.mutable.value = LiveCaptureStatus(true, paused, saved, text)
    overlay?.render("${position.account} · 仓${position.box} 第${position.slot}个 · 已存 $saved", text, paused, automatic)
  }
  override fun onDestroy() {
    closed = true; generation++
    main.removeCallbacks(sample)
    overlay?.close(); overlay = null
    val old = projection; projection = null
    display?.release(); display = null
    reader?.close(); reader = null
    old?.stop()
    preview?.recycle(); preview = null
    val job = scope.coroutineContext[Job]!!
    job.invokeOnCompletion {
      if (ocrProvider.isInitialized()) runCatching { ocr.close() }
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
