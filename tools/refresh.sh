#!/usr/bin/env bash
# One-shot refresh: reconnect to the watch over WiFi, pull glucose + insulin,
# and rebuild the iCloud dashboard — the whole pipeline in one command.
#
# Usage:
#   ./tools/refresh.sh                  # prompts for the watch IP:port
#   ./tools/refresh.sh 10.0.0.48:46421  # non-interactive
#
# The IP:port is on the watch: Settings > Developer options > Wireless debugging
# (the main screen, not the pairing one — the port changes every session).
# Pairing is one-time; if connect fails, re-pair from the "Pair device with
# pairing code" screen:  adb pair <ip>:<pairing-port>
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
command -v adb >/dev/null || { echo "adb not found on PATH" >&2; exit 1; }

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
    read -r -p "Watch IP:port (from the Wireless debugging screen): " TARGET
fi
[[ "$TARGET" == *:* ]] || { echo "Expected IP:port, e.g. 10.0.0.48:46421" >&2; exit 1; }

echo "==> Connecting to $TARGET ..."
adb connect "$TARGET" >/dev/null 2>&1 || true
state="$(adb -s "$TARGET" get-state 2>/dev/null || true)"
if [[ "$state" != "device" ]]; then
    cat >&2 <<EOF
Could not reach $TARGET (state: ${state:-none}).
On the watch: turn WiFi on, open Settings > Developer options > Wireless
debugging, read the current IP:port shown there, and retry. If it still fails,
re-pair once from the "Pair device with pairing code" screen:
  adb pair <ip>:<pairing-port>
EOF
    exit 1
fi
export ANDROID_SERIAL="$TARGET"
echo "    connected."

echo "==> Pulling glucose history from Juggluco ..."
"$HERE/pull-juggluco.sh"
python3 "$HERE/export-glucose.py"

echo "==> Exporting insulin log ..."
"$HERE/export-log.sh" ~/insulin-log.csv

echo "==> Rebuilding dashboard ..."
python3 "$HERE/build-dashboard.py"

echo
echo "Done — dashboard refreshed and syncing to iCloud (Mac + iPhone)."
