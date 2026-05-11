package com.wb.bgapp.ui

import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.rotary.onRotaryScrollEvent
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.MaterialTheme
import androidx.wear.compose.material.Picker
import androidx.wear.compose.material.Scaffold
import androidx.wear.compose.material.Text
import androidx.wear.compose.material.rememberPickerState
import com.wb.bgapp.data.GlucoseRepository
import com.wb.bgapp.data.InsulinEntry
import kotlinx.coroutines.launch

private val FastColour = Color(0xFFFFA000)
private val SlowColour = Color(0xFF42A5F5)

@Composable
fun InsulinLoggerScreen(onConfirm: (Int, String) -> Unit) {
    val state = rememberPickerState(initialNumberOfOptions = 50, initiallySelectedOption = 0)
    val reading by GlucoseRepository.latest.collectAsStateWithLifecycle()
    val focusRequester = remember { FocusRequester() }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) { focusRequester.requestFocus() }

    Scaffold {
        Column(
            modifier = Modifier.fillMaxSize().padding(8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.SpaceEvenly,
        ) {
            Text(
                text = reading?.let { String.format("%.1f mmol/L %s", it.mmol, it.trend.symbol) } ?: "--",
                fontSize = 12.sp,
                color = MaterialTheme.colors.onBackground,
            )

            Box(
                modifier = Modifier.fillMaxWidth().height(80.dp),
                contentAlignment = Alignment.Center,
            ) {
                Picker(
                    state = state,
                    contentDescription = "Insulin units",
                    modifier = Modifier
                        .fillMaxWidth()
                        .onRotaryScrollEvent { event ->
                            scope.launch {
                                val target = (state.selectedOption + if (event.verticalScrollPixels > 0) 1 else -1)
                                    .coerceIn(0, state.numberOfOptions - 1)
                                state.scrollToOption(target)
                            }
                            true
                        }
                        .focusRequester(focusRequester)
                        .focusable(),
                ) { index ->
                    Text(
                        text = "${index + 1}",
                        fontSize = 32.sp,
                        fontWeight = FontWeight.Bold,
                        textAlign = TextAlign.Center,
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterHorizontally),
            ) {
                Button(
                    onClick = { onConfirm(state.selectedOption + 1, InsulinEntry.TYPE_FAST) },
                    colors = ButtonDefaults.buttonColors(backgroundColor = FastColour),
                ) {
                    Text("Fast", fontWeight = FontWeight.Bold)
                }
                Button(
                    onClick = { onConfirm(state.selectedOption + 1, InsulinEntry.TYPE_SLOW) },
                    colors = ButtonDefaults.buttonColors(backgroundColor = SlowColour),
                ) {
                    Text("Slow", fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}
