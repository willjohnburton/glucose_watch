package com.wb.bgapp.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlin.random.Random

class MockGlucoseProvider(
    private val scope: CoroutineScope,
    private val intervalMs: Long = 60_000L,
) : GlucoseProvider {

    private val _readings = MutableSharedFlow<GlucoseReading>(replay = 1)
    override val readings = _readings.asSharedFlow()

    private var job: Job? = null
    private var current = 7.0
    private var momentum = 0.0

    override fun start() {
        if (job?.isActive == true) return
        job = scope.launch {
            while (true) {
                val rate = step()
                val reading = GlucoseReading(
                    mmol = current,
                    trend = GlucoseTrend.fromRateMmolPerMin(rate),
                    timestampMs = System.currentTimeMillis(),
                )
                _readings.emit(reading)
                delay(intervalMs)
            }
        }
    }

    override fun stop() {
        job?.cancel()
        job = null
    }

    private fun step(): Double {
        momentum = (momentum * 0.7) + Random.nextDouble(-0.15, 0.15)
        val next = (current + momentum).coerceIn(3.0, 15.0)
        val rate = next - current
        current = next
        return rate
    }
}
