package com.example.pokemmobreederhelper.data

import android.content.Context
import com.example.pokemmobreederhelper.R
import org.json.JSONObject

internal data class ParticleDefinition(val id: String, val name: String, val englishName: String,
  val intrinsic: Boolean, val iconIndex: Int, val samples: List<IntArray>)

internal object ParticleCatalog {
  @Volatile private var cached: List<ParticleDefinition>? = null
  fun entries(context: Context): List<ParticleDefinition> = cached ?: synchronized(this) {
    cached ?: run {
      val array = JSONObject(context.resources.openRawResource(R.raw.particle_catalog).bufferedReader().use { it.readText() })
        .getJSONArray("particles")
      List(array.length()) { i ->
        val item = array.getJSONObject(i); val points = item.getJSONArray("samples")
        ParticleDefinition(item.getString("id"), item.getString("name"), item.getString("english_name"),
          item.getBoolean("intrinsic"), item.getInt("icon_index"), List(points.length()) { j ->
            val point = points.getJSONArray(j); IntArray(5) { point.getInt(it) }
          })
      }.also { cached = it }
    }
  }
  fun names(ids: List<String>): String = ids.joinToString("、") { id -> cached?.firstOrNull { it.id == id }?.name ?: id }
}
