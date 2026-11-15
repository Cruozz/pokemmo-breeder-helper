package com.example.pokemmobreederhelper.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import kotlinx.serialization.encodeToString
import org.junit.Test

class InventoryJsonTest {
  @Test
  fun desktopJson_isAcceptedAndPositionIsConverted() {
    val raw =
      """[
        {
          "id": "one",
          "species": "索罗亚",
          "gender": "F",
          "nature": "固执",
          "ivs": [31,31,31,null,31,31],
          "egg_groups": ["陆上"],
          "account": "主账号",
          "page": "5",
          "slot": "13",
          "verified": true,
          "desktop_future_field": "ignored"
        }
      ]""".trimIndent()

    val item = AppJson.decodeInventory(raw).single()
    assertEquals("索罗亚", item.species)
    assertEquals("5-2,3", item.positionLabel)
    assertEquals(5, item.perfectIvCount)
    assertEquals("31/31/31/X/31/31", item.ivText)
  }

  @Test
  fun missingId_isGeneratedWithoutDroppingMaterial() {
    val items = AppJson.decodeInventory("""[{"species":"百变怪","ivs":[31]}]""")
    assertEquals(1, items.size)
    assertTrue(items.single().id.isNotBlank())
    assertEquals(6, items.single().ivs.size)
  }

  @Test
  fun unreviewedDesktopBatch_preservesOptionalFieldsAcrossExport() {
    val raw = """[{"id":"batch","species":"伊布","gender":"F","ivs":[31,null,null,null,null,null],"verified":false,"usable_unreviewed":true,"unreviewed_fields":["nature","has_particles","is_costume"]}]"""
    val item = AppJson.decodeInventory(raw).single()
    assertFalse(item.verified)
    assertTrue(item.usableUnreviewed)
    assertEquals("", item.nature)
    assertEquals(listOf("nature", "has_particles", "is_costume"), item.unreviewedFields)
    val restored = AppJson.decodeInventory(AppJson.codec.encodeToString(listOf(item))).single()
    assertEquals(item, restored)
  }
}
