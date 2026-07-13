#!/usr/bin/env bash
# Pulls Juggluco's raw glucose data off a connected Wear OS watch to the desktop,
# so tools/export-glucose.py can turn it into CSV.
#
# Juggluco stores glucose per-sensor in files/sensors/<id>/polls.dat (20-byte
# records). We copy those via `adb run-as tk.glucodata`. On this Galaxy Watch 4
# run-as works against Juggluco; if a future build blocks it, use Juggluco's own
# in-app export instead.
#
# Prereqs:
#   - adb on PATH, watch authorised (see README for wireless-debugging pairing).
#   - If several devices are attached, set ANDROID_SERIAL first, e.g.:
#       export ANDROID_SERIAL=10.0.0.48:46421
#
# Usage:
#   ./tools/pull-juggluco.sh                 # -> ~/juggluco-data
#   ./tools/pull-juggluco.sh /path/to/dest
set -euo pipefail

PKG="tk.glucodata"
DEST="${1:-$HOME/juggluco-data}"

command -v adb >/dev/null || { echo "adb not found on PATH" >&2; exit 1; }
if ! adb shell "run-as $PKG ls files >/dev/null 2>&1"; then
    echo "Cannot read $PKG data via run-as — is the watch attached/authorised?" >&2
    exit 1
fi

mkdir -p "$DEST/sensors"
# top-level config (optional, handy to keep alongside)
for f in settings.dat sensors.dat backup.dat meals.dat; do
    adb exec-out "run-as $PKG cat files/$f" > "$DEST/$f" 2>/dev/null || true
done

# each sensor's polls.dat holds the actual per-minute readings
SENSORS=$(adb shell "run-as $PKG ls files/sensors" | tr -d '\r' | grep -v '\.dat$' || true)
n=0
for s in $SENSORS; do
    mkdir -p "$DEST/sensors/$s"
    if adb exec-out "run-as $PKG cat files/sensors/$s/polls.dat" > "$DEST/sensors/$s/polls.dat" 2>/dev/null; then
        echo "pulled sensor $s"
        n=$((n+1))
    fi
done

echo "Pulled $n sensor(s) to $DEST"
echo "Next: python3 tools/export-glucose.py --out ~/glucose-history.csv"
