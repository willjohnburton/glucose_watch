package com.wb.bgapp.data

import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import java.util.concurrent.TimeUnit

private const val TAG = "BgHttp"

class JugglucoHttpProvider(
    private val scope: CoroutineScope,
    private val url: String = "http://127.0.0.1:17580/api/v1/entries/current.json",
    private val pollIntervalMs: Long = 60_000L,
) : GlucoseProvider {

    private val client = OkHttpClient.Builder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(3, TimeUnit.SECONDS)
        .build()

    private val _readings = MutableSharedFlow<GlucoseReading>(replay = 1)
    override val readings = _readings.asSharedFlow()

    private var job: Job? = null

    override fun start() {
        if (job?.isActive == true) return
        job = scope.launch {
            while (true) {
                fetchOnce()?.let { _readings.emit(it) }
                delay(pollIntervalMs)
            }
        }
    }

    override fun stop() {
        job?.cancel()
        job = null
    }

    private suspend fun fetchOnce(): GlucoseReading? = withContext(Dispatchers.IO) {
        runCatching {
            val req = Request.Builder().url(url).build()
            client.newCall(req).execute().use { resp ->
                if (!resp.isSuccessful) {
                    Log.w(TAG, "http ${resp.code} from $url")
                    return@use null
                }
                val body = resp.body?.string() ?: return@use null
                val arr = JSONArray(body)
                if (arr.length() == 0) {
                    Log.w(TAG, "empty entries array from $url")
                    return@use null
                }
                val obj = arr.getJSONObject(0)
                val mgdl = obj.optDouble("sgv", Double.NaN)
                if (mgdl.isNaN()) {
                    Log.w(TAG, "no sgv in $obj")
                    return@use null
                }
                val timeMs = obj.optLong("date", System.currentTimeMillis())
                val direction = obj.optString("direction").takeIf { it.isNotEmpty() }
                Log.i(TAG, "sgv=$mgdl dir=$direction time=$timeMs")
                GlucoseReading(
                    mmol = mgdl / 18.0,
                    trend = GlucoseTrend.fromNightscoutDirection(direction),
                    timestampMs = timeMs,
                )
            }
        }.onFailure { Log.w(TAG, "fetch failed: ${it.message}") }.getOrNull()
    }
}
