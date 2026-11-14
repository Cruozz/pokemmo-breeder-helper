package com.example.pokemmobreederhelper.data

import android.content.Context
import android.graphics.Bitmap
import android.util.AtomicFile
import androidx.core.graphics.scale
import java.io.File
import kotlinx.serialization.encodeToString

/** Review drafts are separate from inventory and survive process death. */
class CaptureStore(context: Context) {
  private val directory = File(context.filesDir, "capture-drafts").apply { mkdirs() }
  private val index = AtomicFile(File(directory, "drafts.json"))
  var loadError: String = ""
    private set

  fun load(): List<CaptureDraft> = synchronized(writeLock) { try {
    if (!index.baseFile.exists() && !File(directory, "drafts.json.bak").exists()) emptyList()
    else index.openRead().bufferedReader().use { AppJson.codec.decodeFromString(it.readText()) }
  } catch (error: Exception) {
    loadError = "采集草稿无法读取，原文件已保留：${error.message}"
    emptyList()
  } }

  fun imageFile(name: String): File {
    require(name.matches(Regex("[a-fA-F0-9-]+\\.jpg"))) { "无效的预览文件名。" }
    return File(directory, name)
  }

  fun saveImage(name: String, bitmap: Bitmap) {
    check(loadError.isBlank()) { loadError }
    val scale = minOf(1.0, 1600.0 / maxOf(bitmap.width, bitmap.height))
    val preview = if (scale < 1.0) bitmap.scale(
      (bitmap.width * scale).toInt().coerceAtLeast(1), (bitmap.height * scale).toInt().coerceAtLeast(1)) else bitmap
    try {
      imageFile(name).outputStream().use { check(preview.compress(Bitmap.CompressFormat.JPEG, 88, it)) { "无法保存预览。" } }
    } finally { if (preview !== bitmap) preview.recycle() }
  }

  /** Service appends to the on-disk list, so a resumed Activity cannot overwrite new drafts. */
  fun append(draft: CaptureDraft, bitmap: Bitmap) = synchronized(writeLock) {
    val current = load()
    check(loadError.isBlank()) { loadError }
    require(current.size < CaptureLimits.MAX_DRAFTS) { "待核对列表已满（200 只），请先结束采集并核对。" }
    require(current.none { it.material.id == draft.material.id }) { "这条采集已保存。" }
    saveImage(draft.imageName, bitmap)
    save(current + draft)
  }

  companion object { private val writeLock = Any() }

  fun remove(id: String) = synchronized(writeLock) { save(load().filterNot { it.material.id == id }) }

  fun save(drafts: List<CaptureDraft>) = synchronized(writeLock) {
    check(loadError.isBlank()) { loadError }
    val stream = index.startWrite()
    try {
      stream.write(AppJson.codec.encodeToString(drafts).toByteArray(Charsets.UTF_8))
      index.finishWrite(stream)
    } catch (error: Throwable) {
      index.failWrite(stream)
      throw error
    }
    val used = drafts.map { it.imageName }.toSet()
    directory.listFiles()?.filter { it.extension == "jpg" && it.name !in used }?.forEach { it.delete() }
  }
}
