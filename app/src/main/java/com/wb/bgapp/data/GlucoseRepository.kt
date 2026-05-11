package com.wb.bgapp.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

object GlucoseRepository {
    private val scope = CoroutineScope(SupervisorJob())
    private val _latest = MutableStateFlow<GlucoseReading?>(null)
    val latest: StateFlow<GlucoseReading?> = _latest.asStateFlow()

    private var provider: GlucoseProvider? = null

    fun bind(provider: GlucoseProvider) {
        this.provider?.stop()
        this.provider = provider
        scope.launch {
            provider.readings.collect { _latest.value = it }
        }
        provider.start()
    }

    fun submit(reading: GlucoseReading) {
        _latest.value = reading
    }
}
