package com.example.pokemmobreederhelper.ui.main

import android.content.Context
import android.os.SystemClock
import android.util.Log
import androidx.test.core.app.ApplicationProvider
import com.example.pokemmobreederhelper.data.*
import kotlinx.serialization.encodeToString
import org.junit.Assert.*
import org.junit.Test

class LargeInventoryTest {
  @Test fun nineHundredMaterialsProduceTheSameLucarioRoute() {
    val inventory = List(900) { index ->
      val stats = MutableList<Int?>(6) { null }
      stats[index % 6] = 31
      if (index % 3 != 0) stats[(index / 6 + index + 1) % 6] = 31
      val species = listOf("路卡利欧", "长毛狗", "晃晃斑", "小拉达", "咕咕", "百变怪")[index % 6]
      MonsterRecord(id = "benchmark-$index", species = species,
        gender = if (species == "百变怪") "N" else if (index % 4 < 2) "F" else "M", ivs = stats)
    }
    val bridge = PlannerBridge(ApplicationProvider.getApplicationContext<Context>())
    val started = SystemClock.elapsedRealtime()
    val response = bridge.generatePlan(AppJson.codec.encodeToString(inventory),
      PlanRequest("路卡利欧", nature = "固执", ivs = listOf("31", "31", "31", "X", "31", "31")))
    Log.i("PlannerBenchmark", "lucario-900 elapsedMs=${SystemClock.elapsedRealtime() - started}")
    assertTrue(response.error, response.ok)
    assertEquals(8, response.plan!!.steps.size)
    // Verified against the released 0.2.37 bridge and the current core with this same synthetic box.
    val digest = java.security.MessageDigest.getInstance("SHA-256")
      .digest(response.report.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
    assertEquals("4f1f312aebb945c1ae9081d7f3df2f94cb10062ff855e7b344baf83225363b75", digest)
  }
}
