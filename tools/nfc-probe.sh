#!/usr/bin/env bash
# Tests the One UI 8 reader-mode regression on the watch.
#
# Builds + installs the debug APK, records the NFC system features, relaxes
# hidden-API enforcement (needed for the reflection bypass), launches
# NfcProbeActivity and tails its log.
#
# Usage:
#   ./tools/nfc-probe.sh <ip:port>
#
# The probe only detects tags — it sends no commands, so holding an
# unactivated sensor to the watch will NOT activate or disturb it.
set -euo pipefail

cd "$(dirname "$0")/.."

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    read -r -p "Watch wireless-debugging ip:port: " TARGET
fi

if [[ -z "${JAVA_HOME:-}" && -d "/Applications/Android Studio.app/Contents/jbr/Contents/Home" ]]; then
    export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
fi

adb connect "$TARGET"
export ANDROID_SERIAL="$TARGET"

echo
echo "=== NFC system features ==="
adb shell pm list features | grep -i nfc || echo "(no nfc features reported at all)"

echo
echo "=== build + install ==="
./gradlew :app:assembleDebug -q
adb install -r app/build/outputs/apk/debug/app-debug.apk

# The bypass reflects on non-SDK fields of android.nfc.NfcAdapter.
adb shell settings put global hidden_api_policy 1

echo
echo "=== probe ==="
adb logcat -c
adb shell am start -n com.wb.bgapp.debug/com.wb.bgapp.nfc.NfcProbeActivity >/dev/null
sleep 3
adb shell dumpsys nfc | grep -iE "polltech|mtechmask|menablereader" || true
echo
echo "Ctrl-C when done. Hold the sensor to the watch if it says BYPASS OK."
adb logcat -s NFCPROBE
