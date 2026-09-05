# Root cause of the One UI 8 watch NFC regression (#358 / #371)

I spent today tracing this on my own watch with adb and I think I have the mechanism.
**It is not a Juggluco bug and it cannot be fixed in the app.** Details below so others
can confirm on their own devices, plus one small logging change that would make this
diagnosable in seconds instead of hours.

## Device

- Galaxy Watch 4 Classic 46mm (SM-R890)
- One UI 8 Watch / Android 16, build `BP2A.250325.020.R890XXS2JZE1`, SDK 36
- NFC firmware `N01.10.68.F3` (NXP)
- Juggluco 10.10.0, `wear-li3-si-x-nog` flavour
- Worked on the previous OS; the watch update is the only changed variable

## Root cause

**One UI 8 removed the `android.hardware.nfc` system feature from the watch**, while
keeping every card-emulation feature so Samsung Pay still works:

```
$ adb shell pm list features | grep -i nfc
feature:android.hardware.nfc.any
feature:android.hardware.nfc.ese
feature:android.hardware.nfc.hce
feature:android.hardware.nfc.hcef
```

Note `android.hardware.nfc` itself is absent.

`NfcAdapter` caches that once at init into the static `sHasNfcFeature`, and both
reader-mode calls are gated on it (AOSP `packages/modules/Nfc`,
`framework/java/android/nfc/NfcAdapter.java`):

```java
public void enableReaderMode(Activity activity, ReaderCallback callback, int flags,
        Bundle extras) {
    synchronized (sLock) {
        if (!sHasNfcFeature) {
            throw new UnsupportedOperationException();
        }
    }
    mNfcActivityManager.enableReaderMode(activity, callback, flags, extras);
}
```

Crucially, `getDefaultAdapter()` still returns a **non-null, enabled** adapter, because it
only requires *some* NFC feature and `sHasCeFeature` is true. So `setnfc()` passes the
null-adapter check and the `isEnabled()` check, then throws at `enableReaderMode`. The
exception carries **no message**, which is why the log line looks empty of information:

```
E/MainActivity: setnfc error
E/MainActivity: mNfcAdapter.disableReaderMode error
```

That "error" is `MainActivity.setnfc()`'s `mess == null` fallback. The real exception is
`UnsupportedOperationException`.

Because the throw happens **before any binder call**, NfcService is never asked to poll,
which matches what dumpsys reports on affected watches:

```
mState=on
pollTech=0x0
mTechMask: 0
mEnableReader: false
```

The radio isn't broken and the tag never gets a chance — the request never leaves the app's
own process.

## Suggested change to Juggluco (small, and the only actionable part)

In `Common/src/main/java/tk/glucodata/MainActivity.java`, `setnfc()` logs
`error.getMessage()`, which is null here, so every affected user reports the useless string
`setnfc error`. Logging the exception class would identify this instantly:

```java
} catch(Throwable error) {
    Log.e(LOG_ID, "setnfc " + error.getClass().getName() + ": " + error.getMessage());
}
```

Even better, since it is cheaply detectable at startup:

```java
if (!getPackageManager().hasSystemFeature(PackageManager.FEATURE_NFC)) {
    // Reader mode will always throw on this device; tell the user it is the OS.
}
```

That would let Juggluco say "this watch's OS has disabled tag reading" instead of silently
failing, which is the difference between an evening and a week of debugging for the next
person.

## Workarounds tested — and why none of them are a fix

I went as far as I could in userspace. Reporting the negative results so nobody repeats them:

**1. Flipping the cached flag by reflection — works, but not enough.**
Setting `NfcAdapter.sHasNfcFeature = true` (plus populating `sTagService` from `sService`,
which init skips when the feature is absent; needs
`adb shell settings put global hidden_api_policy 1`) makes reader mode engage properly. The
request reaches the chip:

```
D/libnfc_nci: nfcManager_enableDiscovery: enter; tech_mask = 09   # NFC-A | NFC-V
D/libnfc_nci: startRfDiscovery: is start=1
D/libnfc_nci: nfaConnectionCallback: NFA_RF_DISCOVERY_STARTED_EVT: status = 0
```

Worth knowing: NfcService tears reader mode down whenever the app's UID backgrounds, which
a watch does on its own going to ambient, without pausing the activity:

```
I/NfcService: onUidToBackground: Uid 10031
D/NfcService: resetReaderModeParams: Disabling reader mode because app died or moved to background
D/libnfc_nci: nfcManager_enableDiscovery: enter; tech_mask = 00
```

Re-asserting reader mode on a ~1.5s timer keeps it alive.

**2. Raw NCI via `sendVendorNciMessage` — accepted, and still nothing.**
With `WRITE_SECURE_SETTINGS` granted over adb (its protection level includes `development`,
so `pm grant` works), `NfcAdapter.sendVendorNciMessage()` accepts non-vendor GIDs, and the
controller returns `STATUS_OK` to a discovery map that explicitly polls NFC-A and NFC-V:

```
RF_DEACTIVATE        gid=0x01 oid=0x06 -> SUCCESS   <- response [00]
RF_DISCOVER poll A+V gid=0x01 oid=0x03 -> SUCCESS   <- response [00]
```

**3. Result: no RF activation, ever.** With reader mode genuinely armed and poll discovery
accepted by the controller, holding a **contactless bank card** (NFC-A) to the watch
produces no `RF_INTF_ACTIVATED_NTF`, no notification, nothing in the NFA logs. Same for the
Libre sensor (NFC-V). The stack does everything we ask and the field is never energised.

For context, `/system/etc/libnfc-nci.conf` line 40 on this build reads
`POLLING_TECH_MASK=0x00` while `HOST_LISTEN_TECH_MASK=0x07`. That only sets the *default*
mask (reader mode passes its own, as the `tech_mask = 09` above shows), so it is not the
mechanism — but it is consistent with the same decision: **this watch has been configured
listen-only.** Card emulation in, tag reading out.

I could not get frame-level NCI logs to prove the controller declining to drive the field —
`nfc.nxp_log_level_global` and `persist.nfc.debug_enabled` are SELinux-locked to root — so
that last step is inference. But three layers above it now behave correctly and the result
is unchanged.

## Conclusion

Tag reading on One UI 8 Watch is disabled below the level any app can reach. Juggluco cannot
work around it, and neither can a replacement app. Affected users' realistic options are to
roll back the watch OS, or to run NFC activation on a phone and accept that the sensor binds
to that device for its life.

Happy to run further tests on this watch if it would help — I still have the diagnostic
build and adb set up.
