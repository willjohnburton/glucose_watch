package com.wb.bgapp.data

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class JugglucoBroadcastReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val mgdl = intent.extras?.let { extras ->
            when {
                extras.containsKey("mgdl") -> extras.getInt("mgdl").toDouble()
                extras.containsKey("glucose") -> extras.getFloat("glucose").toDouble()
                extras.containsKey("sgv") -> extras.getDouble("sgv")
                else -> null
            }
        } ?: return

        val timeMs = intent.getLongExtra("time", System.currentTimeMillis())
            .let { if (it <= 0) System.currentTimeMillis() else it }

        val ratePerMin = if (intent.hasExtra("rate")) {
            intent.getFloatExtra("rate", Float.NaN).takeIf { !it.isNaN() }
        } else null

        val mmol = mgdl / 18.0
        val trend = GlucoseTrend.fromJugglucoRate(ratePerMin)
        GlucoseRepository.submit(GlucoseReading(mmol, trend, timeMs))
    }
}
