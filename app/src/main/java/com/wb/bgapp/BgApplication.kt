package com.wb.bgapp

import android.app.Application
import android.content.Context
import android.content.IntentFilter
import android.os.Build
import com.wb.bgapp.data.GlucoseRepository
import com.wb.bgapp.data.JugglucoBroadcastReceiver
import com.wb.bgapp.data.MockGlucoseProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class BgApplication : Application() {

    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        instance = this

        // Dev: simulate readings every minute. Swap for JugglucoHttpProvider(appScope)
        // to poll Juggluco's local web server, or remove entirely and rely solely on
        // the broadcast receiver below.
        GlucoseRepository.bind(MockGlucoseProvider(appScope))

        val filter = IntentFilter().apply {
            addAction("glucodata.Minute")
            addAction("com.eveningoutpost.dexdrip.BgEstimate")
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(JugglucoBroadcastReceiver(), filter, Context.RECEIVER_EXPORTED)
        } else {
            registerReceiver(JugglucoBroadcastReceiver(), filter)
        }
    }

    companion object {
        lateinit var instance: BgApplication
            private set
    }
}
