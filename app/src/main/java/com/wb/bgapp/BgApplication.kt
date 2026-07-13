package com.wb.bgapp

import android.app.Application
import android.content.Context
import android.content.IntentFilter
import android.os.Build
import com.wb.bgapp.data.AppDatabase
import com.wb.bgapp.data.GlucoseRepository
import com.wb.bgapp.data.JugglucoBroadcastReceiver
import com.wb.bgapp.data.JugglucoHttpProvider
import com.wb.bgapp.data.MockGlucoseProvider
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class BgApplication : Application() {

    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)

    override fun onCreate() {
        super.onCreate()
        instance = this

        GlucoseRepository.attachStore(AppDatabase.get(this).glucoseDao())

        if (isEmulator()) {
            GlucoseRepository.bind(MockGlucoseProvider(appScope))
        } else {
            GlucoseRepository.bind(JugglucoHttpProvider(appScope))
        }

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

    private fun isEmulator(): Boolean =
        Build.HARDWARE in setOf("goldfish", "ranchu") || Build.PRODUCT.startsWith("sdk_")

    companion object {
        lateinit var instance: BgApplication
            private set
    }
}
