package com.wb.bgapp.data

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

private const val TAG = "BgReceiver"

private const val XDRIP_BG = "com.eveningoutpost.dexdrip.Extras.BgEstimate"
private const val XDRIP_TIME = "com.eveningoutpost.dexdrip.Extras.Time"
private const val XDRIP_SLOPE_NAME = "com.eveningoutpost.dexdrip.Extras.BgSlopeName"
private const val XDRIP_SLOPE = "com.eveningoutpost.dexdrip.Extras.BgSlope"

class JugglucoBroadcastReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val extras = intent.extras
        Log.i(TAG, "received action=${intent.action} keys=${extras?.keySet()?.joinToString()}")
        if (extras == null) return

        val mgdl: Double = when {
            extras.containsKey(XDRIP_BG) -> extras.getDouble(XDRIP_BG)
            extras.containsKey("mgdl") -> extras.getInt("mgdl").toDouble()
            extras.containsKey("glucose") -> extras.getFloat("glucose").toDouble()
            extras.containsKey("sgv") -> extras.getDouble("sgv")
            else -> {
                Log.w(TAG, "no recognised glucose key in broadcast")
                return
            }
        }

        val timeMs: Long = when {
            extras.containsKey(XDRIP_TIME) -> extras.getLong(XDRIP_TIME)
            extras.containsKey("time") -> extras.getLong("time")
            else -> System.currentTimeMillis()
        }.let { if (it <= 0) System.currentTimeMillis() else it }

        val trend = when {
            extras.containsKey(XDRIP_SLOPE_NAME) ->
                GlucoseTrend.fromNightscoutDirection(extras.getString(XDRIP_SLOPE_NAME))
            extras.containsKey(XDRIP_SLOPE) ->
                GlucoseTrend.fromRateMmolPerMin(extras.getDouble(XDRIP_SLOPE) / 18.0)
            extras.containsKey("rate") ->
                GlucoseTrend.fromJugglucoRate(extras.getFloat("rate"))
            else -> GlucoseTrend.Unknown
        }

        val mmol = mgdl / 18.0
        Log.i(TAG, "submit mmol=${"%.1f".format(mmol)} trend=$trend at=$timeMs")
        GlucoseRepository.submit(GlucoseReading(mmol, trend, timeMs))
    }
}
