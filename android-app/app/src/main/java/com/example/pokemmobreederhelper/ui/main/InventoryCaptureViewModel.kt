package com.example.pokemmobreederhelper.ui.main

import android.app.Application
import android.graphics.Bitmap
import android.net.Uri
import com.example.pokemmobreederhelper.capture.LiveCaptureState
import kotlinx.coroutines.flow.collect
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.example.pokemmobreederhelper.data.*
import java.util.UUID
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

internal data class CaptureUiState(
  val drafts: List<CaptureDraft> = emptyList(),
  val busy: Boolean = false,
  val liveActive: Boolean = false,
  val processed: Int = 0,
  val total: Int = 0,
  val skipped: Int = 0,
  val grouped: Int = 0,
  val failures: Int = 0,
  val message: String = "",
  val error: String = "",
)

internal class InventoryCaptureViewModel(application: Application) : AndroidViewModel(application) {
  private val store = CaptureStore(application)
  private val initial = store.load()
  private val _state = MutableStateFlow(CaptureUiState(drafts = initial, error = store.loadError))
  val state = _state.asStateFlow()
  private val lock = Mutex()
  private var scanJob: Job? = null
  private val scanner by lazy { InventoryMediaScanner(application, PlannerBridge(application)) }

  init {
    viewModelScope.launch {
      LiveCaptureState.state.collect { live ->
        lock.withLock {
          if (!_state.value.busy) {
            val drafts = withContext(Dispatchers.IO) { store.load() }
            _state.update { it.copy(liveActive = live.running, drafts = drafts, error = store.loadError) }
          }
        }
      }
    }
  }

  fun imagePath(draft: CaptureDraft): String = store.imageFile(draft.imageName).absolutePath

  private suspend fun change(transform: (List<CaptureDraft>) -> List<CaptureDraft>) = lock.withLock {
    val next = transform(_state.value.drafts)
    if (next != _state.value.drafts) {
      withContext(Dispatchers.IO + NonCancellable) { store.save(next) }
      _state.update { it.copy(drafts = next) }
    }
  }

  fun scan(uris: List<Uri>, video: Boolean) {
    if (_state.value.busy || _state.value.liveActive || uris.isEmpty() || store.loadError.isNotBlank()) return
    if (_state.value.drafts.size >= CaptureLimits.MAX_DRAFTS) {
      _state.update { it.copy(error = "待核对列表已满，请先核对或忽略部分草稿。") }; return
    }
    _state.update { it.copy(busy = true, processed = 0, total = 0, skipped = 0, grouped = 0,
      failures = 0, error = "", message = "正在读取媒体，识别在本机进行…") }
    scanJob = viewModelScope.launch {
      val batch = UUID.randomUUID().toString()
      var previousId: String? = null
      try {
        withContext(Dispatchers.IO) { scanner }.scan(uris, video) { recognition, bitmap, label, ms, done, total, error ->
          currentCoroutineContext().ensureActive()
          val material = recognition?.material
          if (material != null && bitmap != null) {
            val draft = CaptureDraft(material, recognition.warnings, recognition.rawText, recognition.fingerprint,
              material.id + ".jpg", label, batch, ms, ms)
            lock.withLock {
              val current = _state.value.drafts
              val previous = current.lastOrNull { it.material.id == previousId }
              val merge = previous?.canGroup(draft) == true
              require(merge || current.size < CaptureLimits.MAX_DRAFTS) { "已保留前 200 条草稿，请核对后分批继续导入。" }
              val next = if (merge) current.map { if (it.material.id == previousId)
                it.copy(lastMs = ms, frameCount = it.frameCount + 1) else it } else current + draft
              withContext(Dispatchers.IO + NonCancellable) {
                if (!merge) store.saveImage(draft.imageName, bitmap)
                store.save(next)
              }
              previousId = if (merge) previousId else draft.material.id
              _state.update { it.copy(drafts = next, grouped = it.grouped + if (merge) 1 else 0) }
            }
          } else {
            previousId = null // A gap or transition starts a new specimen candidate.
          }
          _state.update { it.copy(processed = done, total = total,
            skipped = it.skipped + if (material == null && error == null) 1 else 0,
            failures = it.failures + if (error != null) 1 else 0,
            error = error ?: it.error, message = "正在识别：" + label) }
        }
        _state.update { it.copy(message = "识别完成，请逐只核对后入库。") }
      } catch (_: CancellationException) {
        _state.update { it.copy(message = "已停止识别，已生成的草稿已保留。") }
      } catch (error: Exception) {
        _state.update { it.copy(error = error.message ?: "无法读取媒体，请尝试截图或 MP4 录屏。",
          message = "已生成的草稿已保留，可更换文件后继续。") }
      } finally { _state.update { it.copy(busy = false) } }
    }
  }

  fun cancel() { scanJob?.cancel() }

  fun discard(id: String) = mutate { items -> items.filterNot { it.material.id == id } }
  fun clearDrafts() = mutate { emptyList() }
  fun copyDraft(id: String) = mutate { items ->
    require(items.size < CaptureLimits.MAX_DRAFTS) { "待核对列表已满。" }
    val draft = items.firstOrNull { it.material.id == id } ?: return@mutate items
    items + draft.copy(material = draft.material.copy(id = UUID.randomUUID().toString()), frameCount = 1,
      sourceLabel = draft.sourceLabel + "（手动复制）")
  }

  /** Inventory is committed first; stable UUIDs prevent duplicates if the process dies between writes. */
  fun pruneSaved(ids: Set<String>) {
    if (_state.value.busy || _state.value.liveActive || _state.value.drafts.none { it.material.id in ids }) return
    mutate { items -> items.filterNot { it.material.id in ids } }
  }

  private fun mutate(transform: (List<CaptureDraft>) -> List<CaptureDraft>) {
    if (_state.value.busy || _state.value.liveActive || store.loadError.isNotBlank()) return
    viewModelScope.launch {
      try { change(transform) }
      catch (error: Exception) { _state.update { it.copy(error = error.message ?: "草稿保存失败。") } }
    }
  }
}
