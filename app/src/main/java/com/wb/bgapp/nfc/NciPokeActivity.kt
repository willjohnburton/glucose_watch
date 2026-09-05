package com.wb.bgapp.nfc

import android.app.Activity
import android.nfc.NfcAdapter
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.WindowManager
import java.lang.reflect.Modifier

/**
 * Last userspace avenue past `POLLING_TECH_MASK=0x00` in /system/etc/libnfc-nci.conf.
 *
 * That config tells the controller to poll for no tag technologies at all, and /system is
 * read-only with no root. But NfcAdapter.sendVendorNciMessage() hands raw NCI frames to the
 * chip, so we can try issuing RF_DISCOVER ourselves with NFC-A and NFC-V poll entries,
 * bypassing the config the stack was built from.
 *
 * The documented catch: gid "needs to be one of the vendor reserved GIDs", and RF Management
 * is 0x01. If NfcService enforces that, this route is closed.
 *
 *   adb shell pm grant com.wb.bgapp.debug android.permission.WRITE_SECURE_SETTINGS
 *   adb shell am start -n com.wb.bgapp.debug/com.wb.bgapp.nfc.NciPokeActivity
 *   adb logcat -s NCIPOKE
 */
class NciPokeActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val adapter = NfcAdapter.getDefaultAdapter(this)
        if (adapter == null) {
            log("no adapter")
            return
        }
        flipFeatureFlag()

        registerNciCallback(adapter)

        val send = try {
            NfcAdapter::class.java.getMethod(
                "sendVendorNciMessage",
                Int::class.javaPrimitiveType,
                Int::class.javaPrimitiveType,
                Int::class.javaPrimitiveType,
                ByteArray::class.java
            )
        } catch (t: Throwable) {
            log("sendVendorNciMessage absent: ${t.javaClass.simpleName}")
            return
        }
        log("sendVendorNciMessage found")

        fun nci(label: String, gid: Int, oid: Int, payload: ByteArray) {
            val result = try {
                val status = send.invoke(adapter, MESSAGE_TYPE_COMMAND, gid, oid, payload) as Int
                statusName(status)
            } catch (t: Throwable) {
                val cause = t.cause ?: t
                "${cause.javaClass.simpleName}: ${cause.message ?: "no message"}"
            }
            log("$label gid=0x%02x oid=0x%02x -> %s".format(gid, oid, result))
        }

        // Keep the watch awake: NfcService reconfigures discovery whenever it stirs.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        // Sanity check: a vendor-reserved GID, to see whether the API works for us at all.
        nci("VENDOR PROPRIETARY", 0x0F, 0x00, byteArrayOf())

        // Re-assert poll discovery on a cycle, since the stack will configure over us.
        val poll = object : Runnable {
            override fun run() {
                // RF_DEACTIVATE_CMD to idle, so the controller accepts a new discovery map.
                nci("RF_DEACTIVATE", RF_MANAGEMENT_GID, 0x06, byteArrayOf(0x00))
                // RF_DISCOVER_CMD: poll NFC-A and poll NFC-V, both at frequency 1.
                nci(
                    "RF_DISCOVER poll A+V", RF_MANAGEMENT_GID, 0x03,
                    byteArrayOf(0x02, 0x00, 0x01, 0x06, 0x01)
                )
                handler.postDelayed(this, RE_POLL_MS)
            }
        }
        handler.post(poll)
    }

    private val handler = Handler(Looper.getMainLooper())

    /**
     * "SUCCESS" from sendVendorNciMessage only means the frame reached the HAL. The
     * controller's own status byte comes back through this callback, which is gated on the
     * same permission we just granted.
     */
    private fun registerNciCallback(adapter: NfcAdapter) {
        try {
            val cbClass = Class.forName("android.nfc.NfcAdapter\$NfcVendorNciCallback")
            val proxy = java.lang.reflect.Proxy.newProxyInstance(
                cbClass.classLoader, arrayOf(cbClass)
            ) { _, method, args ->
                when (method.name) {
                    "onVendorNciResponse", "onVendorNciNotification" -> {
                        val gid = args?.getOrNull(0) as? Int ?: -1
                        val oid = args?.getOrNull(1) as? Int ?: -1
                        val payload = args?.getOrNull(2) as? ByteArray ?: ByteArray(0)
                        val hex = payload.joinToString(" ") { "%02x".format(it) }
                        log("<- ${method.name} gid=0x%02x oid=0x%02x [%s]".format(gid, oid, hex))
                        null
                    }
                    "toString" -> "NciProxy"
                    "hashCode" -> System.identityHashCode(this)
                    "equals" -> args?.getOrNull(0) === this
                    else -> null
                }
            }
            NfcAdapter::class.java
                .getMethod(
                    "registerNfcVendorNciCallback",
                    java.util.concurrent.Executor::class.java,
                    cbClass
                )
                .invoke(adapter, java.util.concurrent.Executor { it.run() }, proxy)
            log("vendor NCI callback registered")
        } catch (t: Throwable) {
            val cause = t.cause ?: t
            log("callback registration failed: ${cause.javaClass.simpleName} ${cause.message ?: ""}")
        }
    }

    /** Same client-side gate the probe defeats; most NfcAdapter calls check it. */
    private fun flipFeatureFlag() {
        try {
            for (f in NfcAdapter::class.java.declaredFields) {
                if (!Modifier.isStatic(f.modifiers)) continue
                if (f.type != java.lang.Boolean.TYPE) continue
                if (!f.name.equals("sHasNfcFeature", ignoreCase = true)) continue
                f.isAccessible = true
                f.setBoolean(null, true)
                log("sHasNfcFeature -> true")
            }
        } catch (t: Throwable) {
            log("flip failed: ${t.javaClass.simpleName}")
        }
    }

    private fun statusName(status: Int) = when (status) {
        0 -> "SUCCESS"
        1 -> "REJECTED"
        2 -> "MESSAGE_CORRUPTED"
        3 -> "FAILED"
        else -> "unknown($status)"
    }

    private fun log(line: String) = Log.i(TAG, line)

    private companion object {
        const val TAG = "NCIPOKE"
        const val MESSAGE_TYPE_COMMAND = 1
        const val RF_MANAGEMENT_GID = 0x01
        const val RE_POLL_MS = 3000L
    }
}
