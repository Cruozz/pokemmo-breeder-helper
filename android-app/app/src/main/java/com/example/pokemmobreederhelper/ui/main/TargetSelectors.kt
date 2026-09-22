package com.example.pokemmobreederhelper.ui.main

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp

internal data class NatureOption(val value: String, val english: String = "", val featured: Boolean = false) {
  val label get() = if (value.isEmpty()) "不指定" else if (featured) "★ $value" else value
}

// Display vocabulary only. Inheritance and matching remain in the shared planner.
internal val natureOptions = listOf(
  NatureOption(""),
  NatureOption("固执", "Adamant", true), NatureOption("内敛", "Modest", true),
  NatureOption("爽朗", "Jolly", true), NatureOption("胆小", "Timid", true),
  NatureOption("怕寂寞", "Lonely 孤独"), NatureOption("勇敢", "Brave"), NatureOption("顽皮", "Naughty"),
  NatureOption("大胆", "Bold"), NatureOption("悠闲", "Relaxed"), NatureOption("淘气", "Impish"),
  NatureOption("乐天", "Lax"), NatureOption("急躁", "Hasty"), NatureOption("天真", "Naive"),
  NatureOption("慢吞吞", "Mild"), NatureOption("冷静", "Quiet"), NatureOption("马虎", "Rash"),
  NatureOption("温和", "Calm"), NatureOption("温顺", "Gentle"), NatureOption("自大", "Sassy"),
  NatureOption("慎重", "Careful"), NatureOption("勤奋", "Hardy"), NatureOption("坦率", "Docile"),
  NatureOption("认真", "Serious"), NatureOption("害羞", "Bashful"), NatureOption("浮躁", "Quirky"),
  NatureOption("无修正", "Neutral")
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun NaturePicker(value: String, onChange: (String) -> Unit) {
  var expanded by rememberSaveable { mutableStateOf(false) }
  Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
    Text("目标性格", style = MaterialTheme.typography.labelLarge)
    OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).testTag("nature-picker")) {
      Text(value.ifEmpty { "不指定" }, Modifier.weight(1f))
      ExposedDropdownMenuDefaults.TrailingIcon(expanded)
    }
  }
  if (expanded) NatureSelectionDialog(value, { expanded = false }) {
    onChange(it)
    expanded = false
  }
}

@Composable
internal fun NatureSelectionDialog(value: String, onDismiss: () -> Unit, onChoose: (String) -> Unit) {
  var query by rememberSaveable(stateSaver = TextFieldValue.Saver) { mutableStateOf(TextFieldValue("")) }
  val needle = query.text.trim()
  val matches = natureOptions.filter { needle.isEmpty() || needle in it.label || it.english.contains(needle, ignoreCase = true) }
  val exact = natureOptions.firstOrNull {
    if (needle.isEmpty()) it.value == value
    else needle == it.value || needle == it.label || it.english.equals(needle, true)
  }
  val focus = LocalFocusManager.current
  val compactHeight = LocalConfiguration.current.screenHeightDp < 480
  fun commit(selected: String) { focus.clearFocus(); onChoose(selected) }
  AlertDialog(
    onDismissRequest = onDismiss,
    title = if (compactHeight) null else ({ Text("选择性格") }),
    text = {
      Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(
          value = query, onValueChange = { query = it }, singleLine = true,
          label = { Text("搜索性格") }, modifier = Modifier.fillMaxWidth().testTag("nature-search"),
          keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
          keyboardActions = KeyboardActions(onDone = { exact?.let { commit(it.value) } }),
        )
        LazyColumn(Modifier.fillMaxWidth().heightIn(max = 300.dp).testTag("nature-options")) {
          items(matches, key = { it.value }) { option ->
            Row(Modifier.fillMaxWidth().heightIn(min = 48.dp)
              .clickable(role = Role.RadioButton) { commit(option.value) }.padding(horizontal = 8.dp),
              verticalAlignment = Alignment.CenterVertically) {
              RadioButton(selected = value == option.value, onClick = null)
              Spacer(Modifier.width(8.dp))
              Text(option.label)
            }
          }
          if (matches.isEmpty()) item { Text("没有匹配的性格", Modifier.padding(8.dp)) }
        }
      }
    },
    confirmButton = { TextButton(onClick = { exact?.let { commit(it.value) } }, enabled = exact != null) { Text("确定") } },
    dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } },
  )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun IvSelector(label: String, value: String, onChange: (String) -> Unit, modifier: Modifier = Modifier) {
  var expanded by rememberSaveable { mutableStateOf(false) }
  Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
    Text(label, style = MaterialTheme.typography.labelMedium)
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
      OutlinedTextField(
        value = value, onValueChange = {}, readOnly = true, singleLine = true,
        trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
        modifier = Modifier.menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable)
          .fillMaxWidth().heightIn(min = 56.dp).testTag("iv-$label"),
      )
      ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        listOf("0", "X", "31").forEach { option ->
          DropdownMenuItem(text = { Text(option) }, onClick = { onChange(option); expanded = false })
        }
      }
    }
  }
}
