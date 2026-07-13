#!/usr/bin/env python3
"""Export full glucose history from Juggluco's per-sensor polls.dat files to CSV.

Juggluco (tk.glucodata) stores each reading as a 20-byte little-endian record in
files/sensors/<sensorId>/polls.dat:

    int32  timestamp   Unix epoch seconds
    int32  counter     sensor minute counter (unused here)
    int32  glucose     mg/dL
    int32  trend       Libre trend code 1..5
    float  rate        rate-of-change (mg/dL per minute-ish)

Validated against the app's own insulin-log glucose snapshots: readings match
to the mg/dL. Run tools/pull-juggluco.sh first to copy the files off the watch,
or point --dir at a local copy of the sensors directory.

Usage:
    python3 tools/export-glucose.py [--dir ~/juggluco-data/sensors] [--out ~/glucose-history.csv]
"""
import argparse, csv, glob, os, struct, datetime

REC = 20
TREND = {1: "FallingFast", 2: "Falling", 3: "Stable", 4: "Rising", 5: "RisingFast"}


def parse_polls(path):
    d = open(path, "rb").read()
    out = []
    for off in range(0, len(d) - REC + 1, REC):
        ts, _cnt, gl, trend, rate = struct.unpack_from("<iiiif", d, off)
        # skip empty slots and implausible values
        if ts <= 0 or gl < 20 or gl > 600:
            continue
        out.append((ts, gl, trend, rate, os.path.basename(os.path.dirname(path))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.expanduser("~/juggluco-data/sensors"))
    ap.add_argument("--out", default=os.path.expanduser("~/glucose-history.csv"))
    args = ap.parse_args()

    rows = []
    for p in sorted(glob.glob(os.path.join(args.dir, "*", "polls.dat"))):
        rows.extend(parse_polls(p))

    # dedupe by timestamp (sensors can overlap during warm-up); keep first seen
    seen = {}
    for ts, gl, trend, rate, sensor in rows:
        if ts not in seen:
            seen[ts] = (gl, trend, rate, sensor)
    merged = sorted(seen.items())

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp_local", "epoch_s", "glucose_mmol", "glucose_mgdl", "trend", "rate_mgdl_min", "sensor"])
        for ts, (gl, trend, rate, sensor) in merged:
            local = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([local, ts, round(gl / 18.0, 2), gl, TREND.get(trend, trend), round(rate, 3), sensor])

    if merged:
        span = f"{datetime.datetime.fromtimestamp(merged[0][0]):%Y-%m-%d} .. {datetime.datetime.fromtimestamp(merged[-1][0]):%Y-%m-%d}"
    else:
        span = "no data"
    print(f"Wrote {len(merged)} readings ({span}) to {args.out}")


if __name__ == "__main__":
    main()
