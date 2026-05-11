#!/usr/bin/env bash
# Pulls the insulin log from a connected Wear OS watch/emulator to CSV.
#
# Prereqs:
#   - adb on PATH and a device authorised (USB or WiFi pairing).
#   - The debug build of the app installed (release builds disable run-as).
#
# Usage:
#   ./tools/export-log.sh                  # writes ./insulin-log.csv
#   ./tools/export-log.sh /tmp/foo.csv     # writes the given path
#
set -euo pipefail

PKG="com.wb.bgapp.debug"
OUT="${1:-./insulin-log.csv}"
TMP_DB="$(mktemp -t bg.db.XXXXXX)"

cleanup() { rm -f "$TMP_DB"; }
trap cleanup EXIT

if ! command -v adb >/dev/null; then
    echo "adb not found on PATH" >&2
    exit 1
fi

if ! adb shell "run-as $PKG ls databases/bg.db" >/dev/null 2>&1; then
    echo "Could not read databases/bg.db — is the debug build installed and the device authorised?" >&2
    exit 1
fi

adb exec-out "run-as $PKG cat databases/bg.db" > "$TMP_DB"

SQLITE="$(command -v sqlite3 || true)"
if [[ -z "$SQLITE" ]]; then
    echo "sqlite3 not found — copying raw .db file to ${OUT%.csv}.db instead" >&2
    cp "$TMP_DB" "${OUT%.csv}.db"
    exit 0
fi

"$SQLITE" "$TMP_DB" <<SQL > "$OUT"
.mode csv
.headers on
SELECT
  id,
  units,
  type,
  datetime(timestampMs/1000, 'unixepoch', 'localtime') AS logged_at_local,
  timestampMs,
  ROUND(glucoseMmol, 2) AS glucose_mmol,
  trend
FROM insulin_entries
ORDER BY timestampMs;
SQL

ROWS=$(wc -l < "$OUT" | tr -d ' ')
ROWS=$((ROWS - 1))  # minus header
echo "Wrote ${ROWS} entries to $OUT"
