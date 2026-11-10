package com.example.pokemmobreederhelper.capture

import android.content.Context
import android.graphics.Typeface
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.widget.LinearLayout
import android.widget.TextView
import com.example.pokemmobreederhelper.data.MonsterRecord

/** Shared rendering for the manual preview and the transient automatic result. */
internal class CaptureResultView(context: Context, private val includeMoves: Boolean = false) : LinearLayout(context) {
  private val title = TextView(context).apply { setTextColor(CaptureColors.ink); setTypeface(typeface, Typeface.BOLD) }
  private val values = TextView(context).apply { setTextColor(CaptureColors.ink) }
  private val moves = TextView(context).apply { setTextColor(CaptureColors.muted); visibility = GONE }
  init {
    orientation = VERTICAL
    addView(title, LayoutParams(-1, -2)); addView(values, LayoutParams(-1, -2)); addView(moves, LayoutParams(-1, -2))
    importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES
  }
  fun font(size: Float) { title.textSize = size; values.textSize = (size - 1).coerceAtLeast(8f); moves.textSize = values.textSize }
  fun show(material: MonsterRecord) {
    val label = when (material.gender) { "M" -> "公"; "F" -> "母"; "N" -> "无性别"; else -> "性别待确认" }
    val color = when (material.gender) { "M" -> CaptureColors.male; "F" -> CaptureColors.female; else -> CaptureColors.muted }
    val heading = SpannableStringBuilder().append(material.species.ifBlank { "名称待确认" }).append("  ")
    val start = heading.length
    heading.append(label).setSpan(ForegroundColorSpan(color), start, heading.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    heading.append(" · ").append(material.nature.ifBlank { "性格待确认" })
    title.text = heading
    val stats = listOf("HP", "攻", "防", "特攻", "特防", "速")
    val line = SpannableStringBuilder()
    stats.forEachIndexed { index, name ->
      if (index > 0) line.append(if (index == 3) "\n" else "   ")
      line.append(name).append(" ")
      val value = material.ivs.getOrNull(index)
      val from = line.length
      line.append(value?.toString() ?: "?")
      if (value == 31) line.setSpan(ForegroundColorSpan(CaptureColors.perfect), from, line.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    }
    values.text = line
    moves.text = "技能：" + material.moves.joinToString(" · ")
    moves.visibility = if(includeMoves && material.moves.isNotEmpty()) VISIBLE else GONE
    contentDescription = heading.toString() + " · " + line.toString() + if(moves.visibility == VISIBLE) " · " + moves.text else ""
  }
}
