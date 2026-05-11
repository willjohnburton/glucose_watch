package com.wb.bgapp.data

import kotlinx.coroutines.flow.Flow

interface GlucoseProvider {
    val readings: Flow<GlucoseReading>
    fun start()
    fun stop()
}
