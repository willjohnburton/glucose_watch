package com.wb.bgapp.data

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

object GlucoseRepository {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val _latest = MutableStateFlow<GlucoseReading?>(null)
    val latest: StateFlow<GlucoseReading?> = _latest.asStateFlow()

    private var provider: GlucoseProvider? = null

    // Set once from BgApplication.onCreate. Keeps this object free of any
    // Context/Android dependency while still persisting every reading.
    @Volatile private var store: GlucoseDao? = null

    fun attachStore(dao: GlucoseDao) {
        store = dao
    }

    fun bind(provider: GlucoseProvider) {
        this.provider?.stop()
        this.provider = provider
        scope.launch {
            provider.readings.collect { submit(it) }
        }
        provider.start()
    }

    fun submit(reading: GlucoseReading) {
        _latest.value = reading
        val dao = store ?: return
        scope.launch {
            dao.upsert(
                GlucoseEntry(
                    minuteEpoch = reading.timestampMs / 60_000,
                    mmol = reading.mmol,
                    trend = reading.trend.name,
                )
            )
        }
    }
}
