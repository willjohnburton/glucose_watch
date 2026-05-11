package com.wb.bgapp.ui

import android.content.Context
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.wb.bgapp.BgApplication
import com.wb.bgapp.data.AppDatabase
import com.wb.bgapp.data.GlucoseRepository
import com.wb.bgapp.data.InsulinEntry
import kotlinx.coroutines.launch

class InsulinLoggerActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            InsulinLoggerScreen(
                onConfirm = ::logUnits,
            )
        }
    }

    private fun logUnits(units: Int, type: String) {
        val reading = GlucoseRepository.latest.value
        val entry = InsulinEntry(
            units = units,
            type = type,
            timestampMs = System.currentTimeMillis(),
            glucoseMmol = reading?.mmol,
            trend = reading?.trend?.name,
        )
        val app = application as BgApplication
        app.appScope.launch {
            AppDatabase.get(this@InsulinLoggerActivity).insulinDao().insert(entry)
        }
        vibrate()
        finish()
    }

    private fun vibrate() {
        val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            (getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        }
        vibrator.vibrate(VibrationEffect.createOneShot(80, VibrationEffect.DEFAULT_AMPLITUDE))
    }
}
