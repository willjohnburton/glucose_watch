#!/usr/bin/env python3
"""Recover 15-minute glucose history from Juggluco's `data.dat` files.

`polls.dat` holds the 1-minute BLE stream and is what `export-glucose.py` reads.
When a sensor never establishes its BLE link (e.g. it was activated by a device
that wasn't listening), `polls.dat` stays zero-filled but `data.dat` still gets
written from NFC scans: the Libre sensor keeps roughly eight hours of 15-minute
history in its own memory and hands it over on every scan.

`data.dat` is a flat array of 12-byte little-endian records:

    uint32 timestamp (epoch seconds, on a 15-minute grid)
    uint16 counter   (sensor minute counter: 15, 30, 45, ...)
    uint16 raw       (non-zero only during the first hour of warmup)
    uint16 glucose   (tenths of mg/dL; zero until warmup completes)
    uint16 flags     (0x4000 once the sensor is streaming normally)

The first record starts at offset 12. Slots that were never filled are zeros.

The tenths-of-mg/dL reading was validated against a sensor that had both files
populated, matching `polls.dat` within a few mg/dL (the residual is the offset
between the 15-minute slot and the nearest 1-minute sample).

Usage:
    python3 tools/export-nfc-history.py [juggluco-dir] [--out FILE]

Defaults to ~/juggluco-data and prints to stdout. Emits the same columns as
`export-glucose.py` so the two can be concatenated; the `sensor` column is
suffixed `-nfc15` so 15-minute NFC data stays distinguishable from the
1-minute stream.
"""
import argparse
import datetime
import glob
import os
import struct
import sys

RECORD = 12
FIRST_RECORD_OFFSET = 12


def read_data_dat(path):
    """Yield (epoch_s, glucose_mgdl) for every populated record."""
    with open(path, "rb") as fh:
        blob = fh.read()
    for off in range(FIRST_RECORD_OFFSET, len(blob) - RECORD + 1, RECORD):
        ts, _counter, _raw, glucose, _flags = struct.unpack(
            "<IHHHH", blob[off:off + RECORD]
        )
        # Unwritten slots are zero; so is every record during warmup.
        if ts == 0 or glucose == 0:
            continue
        yield ts, glucose / 10.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", nargs="?", default=os.path.expanduser("~/juggluco-data"),
                    help="pulled Juggluco directory (default: ~/juggluco-data)")
    ap.add_argument("--out", help="write CSV here instead of stdout")
    args = ap.parse_args()

    rows = []
    for sensor_dir in sorted(glob.glob(os.path.join(args.dir, "sensors", "*"))):
        data_dat = os.path.join(sensor_dir, "data.dat")
        if not os.path.exists(data_dat):
            continue
        sensor = os.path.basename(sensor_dir) + "-nfc15"
        for ts, mgdl in read_data_dat(data_dat):
            rows.append((ts, mgdl, sensor))

    rows.sort()
    # A sensor can be scanned repeatedly; the same 15-minute slot then appears
    # once per scan. Keep one row per (timestamp, sensor).
    deduped, seen = [], set()
    for ts, mgdl, sensor in rows:
        if (ts, sensor) in seen:
            continue
        seen.add((ts, sensor))
        deduped.append((ts, mgdl, sensor))

    out = open(args.out, "w") if args.out else sys.stdout
    try:
        print("timestamp_local,epoch_s,glucose_mmol,glucose_mgdl,trend,rate_mgdl_min,sensor",
              file=out)
        for ts, mgdl, sensor in deduped:
            local = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            print(f"{local},{ts},{mgdl / 18.0:.2f},{mgdl:.0f},,,{sensor}", file=out)
    finally:
        if args.out:
            out.close()

    if deduped:
        span = (f"{datetime.datetime.fromtimestamp(deduped[0][0]):%Y-%m-%d}"
                f" .. {datetime.datetime.fromtimestamp(deduped[-1][0]):%Y-%m-%d}")
    else:
        span = "none"
    print(f"Recovered {len(deduped)} 15-minute readings ({span})", file=sys.stderr)


if __name__ == "__main__":
    main()
