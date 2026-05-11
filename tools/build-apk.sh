#!/usr/bin/env bash
# Builds the debug APK and copies it to ~/Downloads with a versioned name.
# Pick that file up on your phone (Drive / AirDrop / USB) and feed it to
# Wear Installer 2 to push to the watch.
#
# Usage:
#   ./tools/build-apk.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${JAVA_HOME:-}" && -d "/Applications/Android Studio.app/Contents/jbr/Contents/Home" ]]; then
    export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
fi

./gradlew :app:assembleDebug

SRC="app/build/outputs/apk/debug/app-debug.apk"
VERSION=$(grep '^[[:space:]]*versionName' app/build.gradle.kts | head -1 | sed -E 's/.*"([^"]+)".*/\1/')
STAMP=$(date +%Y%m%d-%H%M)
DEST="${HOME}/Downloads/bg-app-v${VERSION}-${STAMP}.apk"

cp "$SRC" "$DEST"
echo
echo "APK copied to: $DEST"
echo "  size: $(du -h "$DEST" | cut -f1)"
echo
echo "Next: get it onto your phone (Drive, AirDrop, USB cable to the phone),"
echo "then in Wear Installer 2 → Add APK → select this file → Send to watch."
