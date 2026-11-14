package com.example.pokemmobreederhelper.ui.main

import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import com.example.pokemmobreederhelper.data.*
import com.example.pokemmobreederhelper.theme.PokeMMOBreederHelperTheme
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class ParticleControlsTest {
  @get:Rule val rule=createAndroidComposeRule<ComponentActivity>()
  @Test fun manualMultiSelectionKeepsExistingParticleAndSavesAnother() {
    var selected=listOf("bats")
    rule.setContent { PokeMMOBreederHelperTheme {
      ParticlePicker(selected,{}, { selected=it })
    } }
    rule.onNodeWithText("搜索中文或英文粒子名称").performTextInput("Sarcophagus")
    rule.onNodeWithText("闪光灵棺").performClick()
    rule.onNodeWithText("保存").performClick()
    rule.runOnIdle { assertEquals(setOf("bats","shiny_sarcophagus"),selected.toSet()) }
  }

  @Test fun editingCostumeAndParticlesPreservesExistingIvAndIdentity() {
    val material=MonsterRecord(id="local-material",species="喵喵",gender="F",ivs=listOf(31,1,2,3,4,5),particles=listOf("bats"),hasParticles=true)
    var saved: MonsterRecord?=null
    rule.setContent { PokeMMOBreederHelperTheme {
      MaterialEditor(material,"",false,{}, { saved=it }, { emptyList() })
    } }
    rule.onNodeWithTag("material-editor-fields").performScrollToNode(hasText("时装精灵"))
    rule.onNodeWithText("时装精灵").performClick()
    rule.onNodeWithText("保存素材").performClick()
    rule.runOnIdle {
      assertEquals(material.id,saved?.id)
      assertEquals(material.ivs,saved?.ivs)
      assertEquals(material.particles,saved?.particles)
      assertEquals(true,saved?.isCostume)
    }
  }
}
