package com.wb.bgapp.nfc

import android.app.Activity
import android.content.pm.PackageManager
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.util.Log
import java.lang.reflect.Modifier
import android.view.Gravity
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/**
 * Diagnostic for the One UI 8 / Android 16 reader-mode regression on the SM-R890.
 *
 * Hypothesis: the watch update dropped the `android.hardware.nfc` system feature but
 * kept `android.hardware.nfc.hce` (Samsung Pay). NfcAdapter caches that as the static
 * `sHasNfcFeature`, and enableReaderMode()/disableReaderMode() throw a bare
 * UnsupportedOperationException on it *before* any binder call — which is why dumpsys
 * shows pollTech=0x0. The check is client-side, in our own process.
 *
 * This probe reports the flag state, then flips it by reflection and retries. It only
 * ever *detects* tags: it sends no commands, so an unactivated sensor stays unactivated.
 *
 *   adb shell settings put global hidden_api_policy 1
 *   adb shell am start -n com.wb.bgapp.debug/com.wb.bgapp.nfc.NfcProbeActivity
 *   adb logcat -s NFCPROBE
 */
class NfcProbeActivity : Activity(), NfcAdapter.ReaderCallback {

    private lateinit var out: TextView
    private lateinit var banner: TextView
    private var adapter: NfcAdapter? = null
    private val handler = Handler(Looper.getMainLooper())
    private var arms = 0

    private val readerFlags =
        NfcAdapter.FLAG_READER_NFC_V or
            NfcAdapter.FLAG_READER_NFC_A or
            NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK or
            NfcAdapter.FLAG_READER_NO_PLATFORM_SOUNDS

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        banner = TextView(this).apply {
            textSize = 22f
            gravity = Gravity.CENTER
            text = "starting"
        }
        out = TextView(this).apply {
            textSize = 11f
            gravity = Gravity.START
        }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 40, 24, 40)
            addView(banner)
            addView(out)
        }
        setContentView(ScrollView(this).apply { addView(column) })

        say("== NFC PROBE ==")
        val pm = packageManager
        say("feature nfc      = ${pm.hasSystemFeature(PackageManager.FEATURE_NFC)}")
        say("feature nfc.hce  = ${pm.hasSystemFeature(PackageManager.FEATURE_NFC_HOST_CARD_EMULATION)}")

        adapter = try {
            NfcAdapter.getDefaultAdapter(this)
        } catch (t: Throwable) {
            say("getDefaultAdapter threw ${t.javaClass.simpleName}")
            null
        }
        say("adapter          = ${if (adapter == null) "null" else "present"}")
        say("adapter.isEnabled= ${adapter?.isEnabled}")

        // The watch sleeps in seconds; reader mode dies with the activity's resumed state.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        flipFeatureFlag()
    }

    override fun onResume() {
        super.onResume()
        handler.removeCallbacks(reArm)
        handler.post(reArm)
    }

    /** Wear steals focus readily; re-arm whenever we get it back. */
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) arm()
    }

    private fun arm() {
        val a = adapter ?: return say("no adapter; stopping")
        val error = tryEnable(a)
        arms++
        if (error == null) {
            status("ARMED\ntap sensor")
            // Log sparsely: this runs every RE_ARM_MS.
            if (arms % 20 == 1) Log.i(TAG, "armed (attempt $arms)")
        } else {
            status("FAILED")
            say("threw ${error.javaClass.simpleName} msg=${error.message ?: "null"}")
        }
    }

    /**
     * NfcService tears reader mode down the moment our UID drops to background — which the
     * watch does on its own when it goes ambient, without ever pausing us. Re-assert it on
     * a timer so the poll is live again within a second of the wrist coming back up.
     */
    private val reArm = object : Runnable {
        override fun run() {
            arm()
            handler.postDelayed(this, RE_ARM_MS)
        }
    }

    override fun onPause() {
        super.onPause()
        // Deliberately leave reader mode alone: the system drops it for us when our UID
        // backgrounds, and tearing it down here would fight the re-arm loop.
        handler.removeCallbacks(reArm)
    }

    /** Returns null on success, or the throwable it failed with. */
    private fun tryEnable(a: NfcAdapter): Throwable? = try {
        a.enableReaderMode(this, this, readerFlags, Bundle().apply {
            putInt(NfcAdapter.EXTRA_READER_PRESENCE_CHECK_DELAY, 250)
        })
        null
    } catch (t: Throwable) {
        t
    }

    /** Samsung's framework-nfc.jar differs from AOSP, so print what is actually there. */
    private fun dumpAdapterFields() {
        say("-- NfcAdapter fields --")
        for (f in NfcAdapter::class.java.declaredFields) {
            val isStatic = Modifier.isStatic(f.modifiers)
            val value = if (isStatic) {
                try {
                    f.isAccessible = true
                    val v = f.get(null)
                    if (v == null) "null" else if (v is Boolean || v is Int) "$v" else "obj"
                } catch (t: Throwable) {
                    "?"
                }
            } else "(inst)"
            say("  ${if (isStatic) "S" else " "} ${f.type.simpleName} ${f.name} = $value")
        }
    }

    /**
     * Flips every static boolean that looks like an NFC feature gate, and makes sure the
     * tag-service handle is populated. Needs hidden_api_policy=1.
     */
    private fun flipFeatureFlag(): Boolean {
        return try {
            val cls = NfcAdapter::class.java
            var flipped = 0
            for (f in cls.declaredFields) {
                if (!Modifier.isStatic(f.modifiers)) continue
                if (f.type != java.lang.Boolean.TYPE) continue
                val n = f.name.lowercase()
                val gate = ("nfc" in n || "feature" in n) &&
                    ("has" in n || "is" in n || "support" in n || "feature" in n)
                if (!gate) continue
                f.isAccessible = true
                if (!f.getBoolean(null)) {
                    f.setBoolean(null, true)
                    say("flipped ${f.name} -> true")
                    flipped++
                }
            }
            if (flipped == 0) say("no feature-gate boolean found to flip")

            // sTagService is only fetched at init when the feature is present, so it is null.
            val tagField = cls.getDeclaredField("sTagService").apply { isAccessible = true }
            if (tagField.get(null) == null) {
                val service = cls.getDeclaredField("sService")
                    .apply { isAccessible = true }.get(null)
                if (service == null) {
                    say("sService is null — cannot build tag interface")
                    return false
                }
                tagField.set(null, service.javaClass.getMethod("getNfcTagInterface").invoke(service))
            }
            say("sTagService: ${if (tagField.get(null) == null) "null" else "acquired"}")
            true
        } catch (t: Throwable) {
            say("reflection failed: ${t.javaClass.simpleName} ${t.message ?: ""}")
            false
        }
    }

    /** Tag detection only — no transceive, so an unactivated sensor is left untouched. */
    override fun onTagDiscovered(tag: Tag) {
        val uid = tag.id.joinToString("") { "%02x".format(it) }
        say("TAG $uid")
        tag.techList.forEach { say("  $it") }
        // The watch may not be readable at the moment of the tap — buzz instead.
        vibrate()
        status("TAG SEEN\n$uid")
    }

    private fun vibrate() {
        try {
            val v = getSystemService(Vibrator::class.java) ?: return
            v.vibrate(VibrationEffect.createOneShot(400, VibrationEffect.DEFAULT_AMPLITUDE))
        } catch (t: Throwable) {
            Log.w(TAG, "vibrate: ${t.javaClass.simpleName}")
        }
    }

    /** Big banner readable at a glance, so the watch reports its own state. */
    private fun status(text: String) {
        runOnUiThread { banner.text = text }
    }

    private fun say(line: String) {
        Log.i(TAG, line)
        runOnUiThread { out.append(line + "\n") }
    }

    private companion object {
        const val TAG = "NFCPROBE"
        const val RE_ARM_MS = 1500L
    }
}
