#!/usr/bin/env python3
"""Merge 15-minute NFC history into the 1-minute glucose CSV, gap-filling only.

`export-nfc-history.py` recovers Juggluco's 15-minute `data.dat` history. Most
of it overlaps periods the 1-minute BLE stream already covers, and appending it
wholesale would count those periods twice — skewing time-in-range, GMI and CV
towards whatever was happening while the sensor happened to be scanned.

So a 15-minute reading is kept only when no 1-minute reading exists within
`--window` seconds of it (default 420s = ±7 minutes, half a slot either side).
What survives is real gap-fill: hours the stream missed entirely.

Usage:
    python3 tools/export-nfc-history.py ~/juggluco-data --out ~/glucose-nfc15.csv
    python3 tools/merge-nfc-history.py --nfc ~/glucose-nfc15.csv

Rewrites the glucose CSV in place (after a .bak) unless --out is given.
"""
import argparse
import bisect
import csv
import os
import shutil
import sys

COLUMNS = ["timestamp_local", "epoch_s", "glucose_mmol", "glucose_mgdl",
           "trend", "rate_mgdl_min", "sensor"]


def load(path):
    with open(os.path.expanduser(path), newline="") as fh:
        return list(csv.DictReader(fh))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--glucose", default="~/glucose-history.csv")
    ap.add_argument("--nfc", default="~/glucose-nfc15.csv")
    ap.add_argument("--out", help="write here instead of rewriting --glucose in place")
    ap.add_argument("--window", type=int, default=420,
                    help="seconds; drop an NFC reading with a stream reading this close")
    args = ap.parse_args()

    stream = load(args.glucose)
    nfc = load(args.nfc)
    have = sorted(int(r["epoch_s"]) for r in stream)

    kept = []
    for row in nfc:
        ts = int(row["epoch_s"])
        i = bisect.bisect_left(have, ts - args.window)
        if i < len(have) and have[i] <= ts + args.window:
            continue
        kept.append(row)

    merged = stream + kept
    merged.sort(key=lambda r: int(r["epoch_s"]))

    dest = os.path.expanduser(args.out or args.glucose)
    if not args.out and os.path.exists(dest):
        shutil.copy2(dest, dest + ".bak")
    with open(dest, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(merged)

    hours = len(kept) * 15 / 60
    print(f"Merged {len(kept)} gap-filling 15-minute readings (~{hours:.1f} h) "
          f"into {len(stream)} stream readings -> {len(merged)} total", file=sys.stderr)
    print(f"Wrote {dest}", file=sys.stderr)


if __name__ == "__main__":
    main()
