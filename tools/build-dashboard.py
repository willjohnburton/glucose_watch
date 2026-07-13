#!/usr/bin/env python3
"""Build a self-contained glucose + insulin dashboard as a single HTML file.

Reads the CSVs produced by tools/export-glucose.py (glucose history) and
tools/export-log.sh (insulin log), computes the standard clinical summaries
(Time-in-Range, AGP percentile profile, GMI, CV) plus a recent trace with
insulin doses overlaid, and writes one offline HTML file. No servers, no CDN,
no database — the data is embedded, so it opens on macOS and iOS straight from
iCloud Drive.

Usage:
    python3 tools/build-dashboard.py \
        --glucose ~/glucose-history.csv \
        --insulin ~/insulin-log.csv \
        --out "~/Library/Mobile Documents/com~apple~CloudDocs/Health/glucose-dashboard.html"

Defaults write into iCloud Drive's Health/ folder.
"""
import argparse
import bisect
import csv
import datetime as dt
import json
import os

MMOL = 18.0  # mg/dL per mmol/L

# Standard AGP / consensus Time-in-Range bands, in mmol/L.
BANDS = [
    ("vlow", "Very Low", "< 3.0", lambda x: x < 3.0),
    ("low", "Low", "3.0 – 3.9", lambda x: 3.0 <= x < 3.9),
    ("inrange", "In Range", "3.9 – 10.0", lambda x: 3.9 <= x <= 10.0),
    ("high", "High", "10.0 – 13.9", lambda x: 10.0 < x <= 13.9),
    ("vhigh", "Very High", "> 13.9", lambda x: x > 13.9),
]


def pct(sorted_vals, q):
    """Linear-interpolated percentile q (0..100) of a sorted list."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = (len(sorted_vals) - 1) * (q / 100.0)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def load_glucose(path):
    rows = []
    with open(os.path.expanduser(path), newline="") as f:
        for r in csv.DictReader(f):
            try:
                mmol = float(r["glucose_mmol"])
                epoch = int(r["epoch_s"])
                local = dt.datetime.strptime(r["timestamp_local"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, KeyError):
                continue
            if mmol <= 0:
                continue
            rows.append((epoch, local, mmol))
    rows.sort()
    return rows


def load_insulin(path):
    rows = []
    with open(os.path.expanduser(path), newline="") as f:
        for r in csv.DictReader(f):
            try:
                units = int(r["units"])
                ms = int(r["timestampMs"])
                local = dt.datetime.strptime(r["logged_at_local"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, KeyError):
                continue
            rows.append((ms, local, units, r["type"]))
    rows.sort()
    return rows


def dose_responses(glucose, insulin):
    """For each dose, sample glucose from -30 min to +4 h relative to the dose,
    aligned at t=0. Nearest reading within a tight tolerance; None where the
    sensor had a gap. Aggregation (median/percentiles, stratification) happens
    client-side so the filters can be interactive."""
    g_epochs = [g[0] for g in glucose]
    g_vals = [g[2] for g in glucose]

    def nearest(t, tol):
        i = bisect.bisect_left(g_epochs, t)
        best, bd = None, tol + 1
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(g_epochs):
                d = abs(g_epochs[j] - t)
                if d < bd:
                    bd, best = d, g_vals[j]
        return best if bd <= tol else None

    offsets = list(range(-30, 241, 15))  # minutes relative to the dose
    doses = []
    for ms, local, units, typ in insulin:
        t0 = ms // 1000
        g0 = nearest(t0, 600)  # need a reading within 10 min of the dose
        if g0 is None:
            continue
        resp = [nearest(t0 + o * 60, 480) for o in offsets]  # within 8 min each
        doses.append({
            "t0": t0, "u": units, "type": typ, "hour": local.hour,
            "g0": round(g0, 1),
            "r": [None if g is None else round(g, 1) for g in resp],
        })
    return {"offsets": offsets, "doses": doses}


def day_detail(glucose, insulin):
    """Per-day 24h glucose (5-min buckets) + doses, for the day explorer."""
    days = {}
    seen = set()
    for epoch, local, mmol in glucose:
        d = local.date().isoformat()
        sod = local.hour * 3600 + local.minute * 60 + local.second
        key = (d, sod // 300)
        if key in seen:
            continue
        seen.add(key)
        days.setdefault(d, {"g": [], "ins": []})["g"].append([sod, round(mmol, 1)])
    for ms, local, units, typ in insulin:
        d = local.date().isoformat()
        sod = local.hour * 3600 + local.minute * 60 + local.second
        days.setdefault(d, {"g": [], "ins": []})["ins"].append([sod, units, typ])
    for d in days:
        days[d]["g"].sort()
        days[d]["ins"].sort()
    return days


def build(glucose, insulin):
    vals = [g[2] for g in glucose]
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n
    sd = var ** 0.5
    mean_mgdl = mean * MMOL
    gmi = 3.31 + 0.02392 * mean_mgdl  # standard Glucose Management Indicator (%)

    tir = {}
    for key, _name, _range, test in BANDS:
        tir[key] = 100.0 * sum(1 for v in vals if test(v)) / n

    # AGP: 48 half-hour bins by local time-of-day.
    NBINS = 48
    binvals = [[] for _ in range(NBINS)]
    for _epoch, local, mmol in glucose:
        minute = local.hour * 60 + local.minute
        binvals[minute * NBINS // 1440].append(mmol)
    agp = []
    for b in range(NBINS):
        sv = sorted(binvals[b])
        agp.append({
            "t": b * 30,
            "p5": pct(sv, 5), "p25": pct(sv, 25), "p50": pct(sv, 50),
            "p75": pct(sv, 75), "p95": pct(sv, 95),
        })

    # Daily summaries.
    days = {}
    for _epoch, local, mmol in glucose:
        d = local.date().isoformat()
        days.setdefault(d, {"vals": [], "fast": 0, "slow": 0})["vals"].append(mmol)
    for _ms, local, units, typ in insulin:
        d = local.date().isoformat()
        rec = days.setdefault(d, {"vals": [], "fast": 0, "slow": 0})
        rec["fast" if typ == "fast" else "slow"] += units

    daily = []
    for d in sorted(days):
        rec = days[d]
        dv = rec["vals"]
        m = sum(dv) / len(dv) if dv else None
        inr = 100.0 * sum(1 for v in dv if 3.9 <= v <= 10.0) / len(dv) if dv else None
        daily.append({
            "date": d,
            "mean": round(m, 1) if m is not None else None,
            "tir": round(inr) if inr is not None else None,
            "fast": rec["fast"], "slow": rec["slow"],
            "n": len(dv), "cov": min(100, round(100.0 * len(dv) / 1440)),
        })

    # Insulin averages over days that actually logged a dose.
    dosed = [x for x in daily if x["fast"] or x["slow"]]
    avg_fast = sum(x["fast"] for x in dosed) / len(dosed) if dosed else 0
    avg_slow = sum(x["slow"] for x in dosed) / len(dosed) if dosed else 0

    # Recent 14-day trace, glucose downsampled to 5-minute buckets.
    last = glucose[-1][0]
    cutoff = last - 14 * 86400
    seen, pts = set(), []
    for epoch, _local, mmol in glucose:
        if epoch < cutoff:
            continue
        bucket = epoch // 300
        if bucket in seen:
            continue
        seen.add(bucket)
        pts.append([epoch, round(mmol, 1)])
    ins = [
        {"t": ms // 1000, "u": units, "type": typ}
        for ms, _local, units, typ in insulin
        if ms // 1000 >= cutoff
    ]

    start = glucose[0][1].date().isoformat()
    end = glucose[-1][1].date().isoformat()
    span_days = (glucose[-1][1].date() - glucose[0][1].date()).days + 1
    expected = span_days * 1440  # Libre 3 via Juggluco logs ~1 reading/minute
    return {
        "meta": {
            "start": start, "end": end, "days": span_days,
            "readings": n, "coverage": min(100, round(100.0 * n / expected)),
        },
        "stats": {
            "mean_mmol": round(mean, 1), "mean_mgdl": round(mean_mgdl),
            "gmi": round(gmi, 1), "cv": round(100 * sd / mean),
            "sd": round(sd, 1), "tir": {k: round(v, 1) for k, v in tir.items()},
            "avg_fast": round(avg_fast), "avg_slow": round(avg_slow),
            "avg_total": round(avg_fast + avg_slow),
        },
        "agp": agp,
        "daily": daily,
        "trace": {"start": cutoff, "end": last, "points": pts, "insulin": ins},
        "response": dose_responses(glucose, insulin),
        "dayDetail": day_detail(glucose, insulin),
    }


def render(data, generated):
    payload = json.dumps(data, separators=(",", ":"))
    return (
        HTML_HEAD
        + '<script id="data" type="application/json">' + payload + "</script>\n"
        + '<script>const GENERATED=' + json.dumps(generated) + ";</script>\n"
        + HTML_BODY
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glucose", default="~/glucose-history.csv")
    ap.add_argument("--insulin", default="~/insulin-log.csv")
    ap.add_argument("--out", default="~/Library/Mobile Documents/com~apple~CloudDocs/Health/glucose-dashboard.html")
    ap.add_argument("--generated", default="", help="override the generated-on stamp (default: file mtime of glucose CSV)")
    args = ap.parse_args()

    glucose = load_glucose(args.glucose)
    insulin = load_insulin(args.insulin)
    if not glucose:
        raise SystemExit("no glucose rows found in " + args.glucose)

    data = build(glucose, insulin)
    # Deterministic stamp: use the glucose CSV's modification date, not "now".
    generated = args.generated or dt.datetime.fromtimestamp(
        os.path.getmtime(os.path.expanduser(args.glucose))
    ).strftime("%Y-%m-%d %H:%M")

    out = os.path.expanduser(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(render(data, generated))
    print(f"Wrote dashboard ({data['meta']['readings']} readings, "
          f"{data['meta']['start']}..{data['meta']['end']}) to {out}")


# ---------------------------------------------------------------------------
# The page. CSS/JS are literal (no str.format) so braces need no escaping.
# Data is injected as a separate <script> tag by render().
# ---------------------------------------------------------------------------

HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Glucose Dashboard</title>
<style>
:root{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,0.10);
  --blue:#2a78d6; --blue-band:rgba(42,120,214,0.14); --blue-iqr:rgba(42,120,214,0.30);
  --fast:#4a3aa7; --slow:#1baf7a;
  --c1:#2a78d6; --c2:#eb6834; --c3:#4a3aa7;
  --vlow:#a11212; --low:#d03b3b; --inrange:#0ca30c; --high:#eda100; --vhigh:#eb6834;
}
:root[data-theme=dark],
html:root[data-theme=dark]{ color-scheme:dark; }
@media (prefers-color-scheme: dark){
  :root:not([data-theme=light]){
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,0.10);
    --blue:#3987e5; --blue-band:rgba(57,135,229,0.16); --blue-iqr:rgba(57,135,229,0.32);
    --fast:#9085e9; --slow:#199e70;
    --c1:#3987e5; --c2:#d95926; --c3:#9085e9;
    --vlow:#c0342f; --low:#e66767; --inrange:#0ca30c; --high:#d17c26; --vhigh:#c74a1e;
  }
}
:root[data-theme=dark]{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,0.10);
  --blue:#3987e5; --blue-band:rgba(57,135,229,0.16); --blue-iqr:rgba(57,135,229,0.32);
  --fast:#9085e9; --slow:#199e70;
  --vlow:#c0342f; --low:#e66767; --inrange:#0ca30c; --high:#d17c26; --vhigh:#c74a1e;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;line-height:1.45;
  -webkit-text-size-adjust:100%;padding:max(16px,env(safe-area-inset-top)) 16px 64px}
.wrap{max-width:960px;margin:0 auto}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 14px;margin:8px 0 4px}
h1{font-size:20px;margin:0;font-weight:650}
.sub{color:var(--muted);font-size:13px}
.theme{margin-left:auto;background:var(--surface);border:1px solid var(--ring);
  color:var(--ink2);border-radius:8px;padding:6px 10px;font:inherit;font-size:13px;cursor:pointer}
section{background:var(--surface);border:1px solid var(--ring);border-radius:14px;
  padding:16px;margin:14px 0}
h2{font-size:14px;margin:0 0 12px;font-weight:600;letter-spacing:.01em}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px}
.tile{background:var(--plane);border:1px solid var(--ring);border-radius:10px;padding:12px}
.tile .v{font-size:26px;font-weight:650;line-height:1.05}
.tile .u{font-size:12px;color:var(--muted);font-weight:500}
.tile .l{font-size:12px;color:var(--ink2);margin-top:4px}
.legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:12px;font-size:12px;color:var(--ink2)}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:11px;height:11px;border-radius:3px;flex:none}
figure{margin:0}
.scroll{overflow-x:auto}
svg{display:block;width:100%;height:auto;overflow:visible}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums}
.axtitle{fill:var(--ink2);font-size:11px}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:right;padding:6px 8px;border-bottom:1px solid var(--grid);white-space:nowrap}
th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:500;position:sticky;top:0;background:var(--surface)}
.tblwrap{max-height:340px;overflow:auto;border-radius:10px}
.tip{position:fixed;pointer-events:none;z-index:9;background:var(--surface);
  border:1px solid var(--ring);border-radius:8px;padding:7px 9px;font-size:12px;
  color:var(--ink);box-shadow:0 4px 16px rgba(0,0,0,.18);opacity:0;transition:opacity .08s}
.tip b{font-weight:650}
.tip .row{color:var(--ink2)}
.foot{color:var(--muted);font-size:12px;margin-top:8px}
.note{color:var(--ink2);font-size:12.5px;margin:0 0 12px}
.note em{font-style:normal;color:var(--ink);font-weight:600}
.filters{display:flex;flex-wrap:wrap;gap:14px 22px;margin:0 0 14px}
.fgroup{display:flex;flex-direction:column;gap:5px}
.flabel{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{background:var(--plane);border:1px solid var(--ring);color:var(--ink2);
  border-radius:999px;padding:5px 11px;font:inherit;font-size:12.5px;cursor:pointer;
  white-space:nowrap;-webkit-tap-highlight-color:transparent}
.chip[aria-pressed=true]{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
.respsum{display:flex;flex-wrap:wrap;gap:10px;margin-top:12px}
.respsum .card{background:var(--plane);border:1px solid var(--ring);border-radius:10px;
  padding:9px 12px;font-size:12.5px;color:var(--ink2)}
.respsum .card b{display:block;font-size:18px;color:var(--ink);font-weight:650}
.subh{font-size:13px;font-weight:600;margin:22px 0 4px;color:var(--ink)}
.daynav{display:flex;align-items:center;gap:8px;margin-bottom:12px}
.daynav select{flex:1;max-width:260px;background:var(--plane);border:1px solid var(--ring);
  color:var(--ink);border-radius:8px;padding:7px 10px;font:inherit;font-size:14px}
.daynav .chip{font-size:15px;line-height:1;padding:7px 12px}
</style>
</head>
<body>
<div class="wrap">
"""

HTML_BODY = r"""
<header>
  <h1>Glucose Dashboard</h1>
  <span class="sub" id="range"></span>
  <button class="theme" id="theme" aria-label="Toggle theme">Theme</button>
</header>

<section>
  <h2>Overview</h2>
  <div class="tiles" id="tiles"></div>
</section>

<section>
  <h2>Time in Range</h2>
  <figure><svg id="tir" viewBox="0 0 900 96" preserveAspectRatio="none" role="img" aria-label="Time in range stacked bar"></svg></figure>
  <div class="legend" id="tir-legend"></div>
</section>

<section>
  <h2>Ambulatory Glucose Profile (AGP)</h2>
  <p class="note">Every day's readings folded onto one 24-hour clock. The line is the median; the dark band is the middle 50% (25–75th percentile), the light band the 5–95th. The green zone is the 3.9–10.0 target range.</p>
  <figure class="scroll"><svg id="agp" role="img" aria-label="Ambulatory glucose profile"></svg></figure>
</section>

<section>
  <h2>Insulin &rarr; glucose response</h2>
  <p class="note">Every dose lined up at the moment of injection (0 h), showing the typical glucose path over the next 4 hours &mdash; median line, with the 25&ndash;75% spread shaded. Split by the glucose you <em>started</em> at: doses started high are usually corrections; doses started in range are usually meals (expect a rise).</p>
  <div class="filters" id="resp-filters"></div>
  <figure class="scroll"><svg id="resp" role="img" aria-label="Post-dose glucose response"></svg></figure>
  <div class="legend" id="resp-legend"></div>
  <div id="resp-summary" class="respsum"></div>
  <h3 class="subh">Drop per unit &middot; 3 h after dose</h3>
  <p class="note">Each point is one dose: units given vs. how far glucose fell by 3 h (start &minus; 3 h). The line is the best fit through the filtered doses &mdash; its slope is your effective mmol/L per unit. Filter to <em>High &gt;10</em> to isolate corrections.</p>
  <figure class="scroll"><svg id="scatter" role="img" aria-label="Units vs glucose drop"></svg></figure>
  <div id="scatter-summary" class="respsum"></div>
</section>

<section>
  <h2>Overnight &amp; dawn</h2>
  <p class="note">Midnight&ndash;8am glucose folded across every night: median line, 25&ndash;75% band, target zone. The dawn cards show the median rise from 3am to wake.</p>
  <figure class="scroll"><svg id="overnight" role="img" aria-label="Overnight glucose profile"></svg></figure>
  <div id="overnight-summary" class="respsum"></div>
</section>

<section>
  <h2>Day explorer</h2>
  <div class="daynav">
    <button class="chip" id="day-prev" aria-label="Previous day">&larr;</button>
    <select id="day-select" aria-label="Pick a day"></select>
    <button class="chip" id="day-next" aria-label="Next day">&rarr;</button>
  </div>
  <div id="day-summary" class="respsum"></div>
  <figure class="scroll"><svg id="day" role="img" aria-label="Single day glucose and doses"></svg></figure>
</section>

<section>
  <h2>Last 14 days</h2>
  <p class="note">Glucose trace with insulin doses marked below. Hover or tap for values.</p>
  <figure class="scroll"><svg id="trace" role="img" aria-label="Recent glucose trace with insulin doses"></svg></figure>
  <div class="legend">
    <span><span class="sw" style="background:var(--blue)"></span>Glucose</span>
    <span><span class="sw" style="background:var(--fast)"></span>Fast (bolus)</span>
    <span><span class="sw" style="background:var(--slow)"></span>Slow (basal)</span>
  </div>
</section>

<section>
  <h2>Daily detail</h2>
  <div class="tblwrap"><table id="daily"><thead><tr>
    <th>Date</th><th>Mean</th><th>TIR</th><th>Fast U</th><th>Slow U</th><th>Data</th>
  </tr></thead><tbody></tbody></table></div>
  <p class="foot" id="stamp"></p>
</section>
</div>
<div class="tip" id="tip"></div>

<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const SVGNS = 'http://www.w3.org/2000/svg';
const el = (n, a) => { const e = document.createElementNS(SVGNS, n); for (const k in (a||{})) e.setAttribute(k, a[k]); return e; };
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmtDate = iso => new Date(iso + 'T00:00:00').toLocaleDateString(undefined, {month:'short', day:'numeric'});

// ---- Theme toggle (persist in localStorage) ----
const root = document.documentElement;
try { const t = localStorage.getItem('bg-theme'); if (t) root.setAttribute('data-theme', t); } catch(e){}
document.getElementById('theme').onclick = () => {
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const cur = root.getAttribute('data-theme') || (dark ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  try { localStorage.setItem('bg-theme', next); } catch(e){}
  renderAll();
};

// ---- Header + tiles ----
document.getElementById('range').textContent =
  fmtDate(DATA.meta.start) + ' – ' + fmtDate(DATA.meta.end) + ' · ' + DATA.meta.days + ' days';
document.getElementById('stamp').textContent =
  'Generated ' + GENERATED + ' · ' + DATA.meta.readings.toLocaleString() + ' readings · '
  + DATA.meta.coverage + '% sensor coverage';

const s = DATA.stats;
const tiles = [
  {v: s.mean_mmol, u: 'mmol/L', l: 'Mean glucose (' + s.mean_mgdl + ' mg/dL)'},
  {v: s.gmi, u: '%', l: 'GMI (est. A1c)'},
  {v: Math.round(s.tir.inrange), u: '%', l: 'Time in range 3.9–10'},
  {v: s.cv, u: '%', l: 'Variability (CV)'},
  {v: s.avg_total, u: 'U/day', l: s.avg_fast + ' fast · ' + s.avg_slow + ' slow'},
];
document.getElementById('tiles').innerHTML = tiles.map(t =>
  '<div class="tile"><div class="v">' + t.v + ' <span class="u">' + t.u + '</span></div>'
  + '<div class="l">' + t.l + '</div></div>').join('');

// ---- Shared tooltip ----
const tip = document.getElementById('tip');
function showTip(evt, html){
  tip.innerHTML = html; tip.style.opacity = 1;
  const pad = 12, w = tip.offsetWidth, h = tip.offsetHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + w > innerWidth) x = evt.clientX - w - pad;
  if (y + h > innerHeight) y = evt.clientY - h - pad;
  tip.style.left = x + 'px'; tip.style.top = y + 'px';
}
const hideTip = () => { tip.style.opacity = 0; };

const BANDS = [
  ['vlow','Very Low','<3.0','--vlow'], ['low','Low','3.0–3.9','--low'],
  ['inrange','In Range','3.9–10.0','--inrange'], ['high','High','10.0–13.9','--high'],
  ['vhigh','Very High','>13.9','--vhigh'],
];

// ---- Time in Range stacked bar ----
function renderTIR(){
  const svg = document.getElementById('tir');
  svg.innerHTML = '';
  const W = 900, H = 96, gap = 2;
  let x = 0;
  BANDS.forEach(([k,name,rng,cvar]) => {
    const p = s.tir[k];
    const w = Math.max(0, (p/100)*W - gap);
    if (w <= 0) { return; }
    const g = el('g');
    const r = el('rect', {x, y:0, width:w, height:H, rx:4, fill:cssv(cvar)});
    g.appendChild(r);
    if (w > 46){
      const t1 = el('text', {x:x+w/2, y:H/2-2, 'text-anchor':'middle',
        'dominant-baseline':'middle', fill:'#fff', 'font-size':16, 'font-weight':650});
      t1.textContent = (p>=1? Math.round(p): p.toFixed(1)) + '%';
      g.appendChild(t1);
      const t2 = el('text', {x:x+w/2, y:H/2+16, 'text-anchor':'middle',
        'dominant-baseline':'middle', fill:'#fff', 'font-size':11, opacity:.9});
      t2.textContent = name;
      g.appendChild(t2);
    }
    r.addEventListener('pointermove', e => showTip(e,
      '<b>' + name + '</b> (' + rng + ' mmol/L)<div class="row">' + p.toFixed(1) + '% of time</div>'));
    r.addEventListener('pointerleave', hideTip);
    svg.appendChild(g);
    x += w + gap;
  });
  // legend / table-equivalent for the segments too small to label
  document.getElementById('tir-legend').innerHTML = BANDS.map(([k,name,rng,cvar]) =>
    '<span><span class="sw" style="background:' + cssv(cvar) + '"></span>'
    + name + ' <b style="color:var(--ink)">' + s.tir[k].toFixed(1) + '%</b> '
    + '<span style="color:var(--muted)">' + rng + '</span></span>').join('');
}

// ---- AGP ----
function renderAGP(){
  const svg = document.getElementById('agp');
  svg.innerHTML = '';
  const W = 900, H = 300, mL = 40, mR = 12, mT = 12, mB = 28;
  const iw = W - mL - mR, ih = H - mT - mB;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  const yMax = 21, yMin = 2;
  const X = t => mL + (t/1440)*iw;
  const Y = v => mT + (1 - (Math.min(yMax,Math.max(yMin,v))-yMin)/(yMax-yMin))*ih;

  // target range shading 3.9-10
  svg.appendChild(el('rect', {x:mL, y:Y(10), width:iw, height:Y(3.9)-Y(10),
    fill:cssv('--inrange'), opacity:0.10}));
  [3.9,10].forEach(v => svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v),
    stroke:cssv('--inrange'), 'stroke-width':1, 'stroke-dasharray':'4 4', opacity:.55})));

  // y grid + ticks
  [2,5,8,11,14,17,20].forEach(v => {
    svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v), stroke:cssv('--grid'), 'stroke-width':1}));
    const t = el('text', {x:mL-8, y:Y(v), 'text-anchor':'end', 'dominant-baseline':'middle'});
    t.setAttribute('class','tick'); t.textContent = v; svg.appendChild(t);
  });
  // x ticks every 3h
  for (let h=0; h<=24; h+=3){
    const t = el('text', {x:X(h*60), y:H-8, 'text-anchor':'middle'});
    t.setAttribute('class','tick'); t.textContent = (h<10?'0':'')+h+':00'; svg.appendChild(t);
  }

  const A = DATA.agp.filter(d => d.p50 != null);
  const area = (lo, hi) => {
    let d = 'M' + X(A[0].t) + ' ' + Y(A[0][hi]);
    A.forEach(p => d += ' L' + X(p.t) + ' ' + Y(p[hi]));
    for (let i=A.length-1;i>=0;i--) d += ' L' + X(A[i].t) + ' ' + Y(A[i][lo]);
    return d + ' Z';
  };
  svg.appendChild(el('path', {d:area('p5','p95'), fill:cssv('--blue'), opacity:.14}));
  svg.appendChild(el('path', {d:area('p25','p75'), fill:cssv('--blue'), opacity:.30}));
  let dl = 'M' + X(A[0].t) + ' ' + Y(A[0].p50);
  A.forEach(p => dl += ' L' + X(p.t) + ' ' + Y(p.p50));
  svg.appendChild(el('path', {d:dl, fill:'none', stroke:cssv('--blue'), 'stroke-width':2.5,
    'stroke-linejoin':'round'}));

  // hover crosshair
  const cross = el('line', {y1:mT, y2:mT+ih, stroke:cssv('--axis'), 'stroke-width':1, opacity:0});
  const dot = el('circle', {r:4, fill:cssv('--blue'), stroke:cssv('--surface'), 'stroke-width':2, opacity:0});
  svg.appendChild(cross); svg.appendChild(dot);
  const hit = el('rect', {x:mL, y:mT, width:iw, height:ih, fill:'transparent'});
  hit.style.cursor = 'crosshair';
  hit.addEventListener('pointermove', e => {
    const r = svg.getBoundingClientRect();
    const t = ((e.clientX - r.left)/r.width*W - mL)/iw*1440;
    let best = A[0];
    for (const p of A) if (Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
    cross.setAttribute('x1', X(best.t)); cross.setAttribute('x2', X(best.t));
    cross.setAttribute('opacity', 1);
    dot.setAttribute('cx', X(best.t)); dot.setAttribute('cy', Y(best.p50)); dot.setAttribute('opacity', 1);
    const hh = Math.floor(best.t/60), mm = best.t%60;
    showTip(e, '<b>' + (hh<10?'0':'')+hh + ':' + (mm<10?'0':'')+mm + '</b>'
      + '<div class="row">Median ' + best.p50.toFixed(1) + '</div>'
      + '<div class="row">IQR ' + best.p25.toFixed(1) + '–' + best.p75.toFixed(1) + '</div>'
      + '<div class="row">5–95% ' + best.p5.toFixed(1) + '–' + best.p95.toFixed(1) + '</div>');
  });
  hit.addEventListener('pointerleave', () => { hideTip(); cross.setAttribute('opacity',0); dot.setAttribute('opacity',0); });
  svg.appendChild(hit);

  const yt = el('text', {x:12, y:mT+ih/2, 'text-anchor':'middle',
    transform:'rotate(-90 12 ' + (mT+ih/2) + ')'});
  yt.setAttribute('class','axtitle'); yt.textContent = 'mmol/L'; svg.appendChild(yt);
}

// ---- Recent trace ----
function renderTrace(){
  const svg = document.getElementById('trace');
  svg.innerHTML = '';
  const P = DATA.trace.points;
  const days = 14;
  const W = Math.max(900, days*70), H = 320, mL = 40, mR = 12, mT = 12, mB = 40;
  const iw = W - mL - mR, ih = H - mT - mB;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  svg.style.minWidth = W + 'px';
  const t0 = DATA.trace.start, t1 = DATA.trace.end;
  const yMax = 21, yMin = 2;
  const X = t => mL + (t - t0)/(t1 - t0)*iw;
  const Y = v => mT + (1 - (Math.min(yMax,Math.max(yMin,v))-yMin)/(yMax-yMin))*ih;

  svg.appendChild(el('rect', {x:mL, y:Y(10), width:iw, height:Y(3.9)-Y(10),
    fill:cssv('--inrange'), opacity:0.10}));
  [3.9,10].forEach(v => svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v),
    stroke:cssv('--inrange'), 'stroke-width':1, 'stroke-dasharray':'4 4', opacity:.5})));
  [2,6,10,14,18].forEach(v => {
    svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v), stroke:cssv('--grid'), 'stroke-width':1}));
    const t = el('text', {x:mL-8, y:Y(v), 'text-anchor':'end', 'dominant-baseline':'middle'});
    t.setAttribute('class','tick'); t.textContent = v; svg.appendChild(t);
  });
  // day gridlines + labels at local midnight
  const startDay = new Date(t0*1000); startDay.setHours(24,0,0,0);
  for (let d = new Date(startDay); d.getTime()/1000 <= t1; d.setDate(d.getDate()+1)){
    const x = X(d.getTime()/1000);
    svg.appendChild(el('line', {x1:x, y1:mT, x2:x, y2:mT+ih, stroke:cssv('--grid'), 'stroke-width':1}));
    const t = el('text', {x:x, y:H-22, 'text-anchor':'middle'});
    t.setAttribute('class','tick');
    t.textContent = d.toLocaleDateString(undefined,{month:'short',day:'numeric'});
    svg.appendChild(t);
  }
  // glucose line: break across gaps > 30 min
  let d = '', prev = null;
  P.forEach(([t,v]) => { d += (prev===null || t-prev>1800 ? ' M':' L') + X(t) + ' ' + Y(v); prev = t; });
  svg.appendChild(el('path', {d, fill:'none', stroke:cssv('--blue'), 'stroke-width':1.6,
    'stroke-linejoin':'round', 'stroke-linecap':'round'}));

  // insulin lollipops along the bottom
  const baseY = mT + ih;
  DATA.trace.insulin.forEach(ins => {
    const x = X(ins.t);
    if (x < mL || x > mL+iw) return;
    const c = ins.type === 'fast' ? cssv('--fast') : cssv('--slow');
    const h = Math.min(46, 8 + ins.u*2.2);
    svg.appendChild(el('line', {x1:x, y1:baseY, x2:x, y2:baseY-h, stroke:c, 'stroke-width':2}));
    const dot = el('circle', {cx:x, cy:baseY-h, r:4.5, fill:c, stroke:cssv('--surface'), 'stroke-width':1.5});
    dot.addEventListener('pointermove', e => showTip(e,
      '<b>' + ins.u + 'U ' + (ins.type==='fast'?'fast':'slow') + '</b><div class="row">'
      + new Date(ins.t*1000).toLocaleString(undefined,{weekday:'short',hour:'2-digit',minute:'2-digit'}) + '</div>'));
    dot.addEventListener('pointerleave', hideTip);
    svg.appendChild(dot);
  });

  // hover crosshair for glucose
  const cross = el('line', {y1:mT, y2:mT+ih, stroke:cssv('--axis'), 'stroke-width':1, opacity:0});
  const gdot = el('circle', {r:4, fill:cssv('--blue'), stroke:cssv('--surface'), 'stroke-width':2, opacity:0});
  svg.appendChild(cross); svg.appendChild(gdot);
  const hit = el('rect', {x:mL, y:mT, width:iw, height:ih, fill:'transparent'});
  hit.style.cursor = 'crosshair';
  hit.addEventListener('pointermove', e => {
    const r = svg.getBoundingClientRect();
    const t = t0 + (e.clientX - r.left)/r.width*W - mL >= 0
      ? t0 + ((e.clientX - r.left)/r.width*W - mL)/iw*(t1-t0) : t0;
    let lo=0, hi=P.length-1;
    while (lo<hi){ const m=(lo+hi)>>1; if (P[m][0]<t) lo=m+1; else hi=m; }
    const p = P[lo]; if (!p) return;
    cross.setAttribute('x1', X(p[0])); cross.setAttribute('x2', X(p[0])); cross.setAttribute('opacity',1);
    gdot.setAttribute('cx', X(p[0])); gdot.setAttribute('cy', Y(p[1])); gdot.setAttribute('opacity',1);
    showTip(e, '<b>' + p[1].toFixed(1) + ' mmol/L</b><div class="row">'
      + new Date(p[0]*1000).toLocaleString(undefined,{weekday:'short',hour:'2-digit',minute:'2-digit'}) + '</div>');
  });
  hit.addEventListener('pointerleave', () => { hideTip(); cross.setAttribute('opacity',0); gdot.setAttribute('opacity',0); });
  svg.appendChild(hit);
}

// ---- Daily table ----
function renderTable(){
  const tb = document.querySelector('#daily tbody');
  tb.innerHTML = DATA.daily.slice().reverse().map(d =>
    '<tr><td>' + fmtDate(d.date) + '</td>'
    + '<td>' + (d.mean!=null? d.mean.toFixed(1):'–') + '</td>'
    + '<td>' + (d.tir!=null? d.tir + '%':'–') + '</td>'
    + '<td>' + (d.fast||'–') + '</td>'
    + '<td>' + (d.slow||'–') + '</td>'
    + '<td style="color:var(--muted)">' + d.cov + '%</td></tr>').join('');
}

// ---- Insulin -> glucose response ----
const respState = {type:'fast', start:'all', tod:'all', mode:'abs', split:'off'};
const RESP_FILTERS = [
  {key:'type',  label:'Dose',       opts:[['fast','Fast'],['slow','Slow'],['all','All']]},
  {key:'start', label:'Started at', opts:[['all','All'],['high','High >10'],['in','In range'],['low','Low <3.9']]},
  {key:'tod',   label:'Time',       opts:[['all','All'],['day','Day 6–22'],['night','Night 22–6']]},
  {key:'mode',  label:'Show',       opts:[['abs','Glucose'],['delta','Change']]},
  {key:'split', label:'Split',      opts:[['off','Off'],['size','By dose size']]},
];
const SIZE_BUCKETS = [
  {lab:'1–3 U', test:u => u <= 3, cv:'--c1'},
  {lab:'4–6 U', test:u => u >= 4 && u <= 6, cv:'--c2'},
  {lab:'7+ U',  test:u => u >= 7, cv:'--c3'},
];
function medianCurve(sub, delta){
  return DATA.response.offsets.map((o,i) => {
    const vals = [];
    sub.forEach(d => { const g = d.r[i]; if (g != null) vals.push(delta ? +(g - d.g0).toFixed(1) : g); });
    return {o, n: vals.length, p25: quant(vals,0.25), p50: quant(vals,0.5), p75: quant(vals,0.75)};
  }).filter(s => s.p50 != null);
}
function quant(arr, q){
  if (!arr.length) return null;
  const a = arr.slice().sort((x,y)=>x-y);
  const idx = (a.length-1)*q, lo = Math.floor(idx), hi = Math.min(lo+1, a.length-1);
  return a[lo] + (a[hi]-a[lo])*(idx-lo);
}
function respSubset(){
  return DATA.response.doses.filter(d => {
    if (respState.type !== 'all' && d.type !== respState.type) return false;
    if (respState.start === 'high' && !(d.g0 > 10)) return false;
    if (respState.start === 'in'   && !(d.g0 >= 3.9 && d.g0 <= 10)) return false;
    if (respState.start === 'low'  && !(d.g0 < 3.9)) return false;
    if (respState.tod === 'day'   && !(d.hour >= 6 && d.hour < 22)) return false;
    if (respState.tod === 'night' &&  (d.hour >= 6 && d.hour < 22)) return false;
    return true;
  });
}
function buildRespFilters(){
  const host = document.getElementById('resp-filters');
  host.innerHTML = RESP_FILTERS.map(f =>
    '<div class="fgroup"><span class="flabel">' + f.label + '</span><div class="chips">'
    + f.opts.map(([v,lab]) =>
        '<button class="chip" data-k="' + f.key + '" data-v="' + v + '">' + lab + '</button>').join('')
    + '</div></div>').join('');
  host.querySelectorAll('.chip').forEach(c => {
    c.onclick = () => { respState[c.dataset.k] = c.dataset.v; renderResponse(); };
  });
}
function renderResponse(){
  document.querySelectorAll('#resp-filters .chip').forEach(c =>
    c.setAttribute('aria-pressed', respState[c.dataset.k] === c.dataset.v));

  const subset = respSubset();
  const delta = respState.mode === 'delta';
  const split = respState.split === 'size';

  let curves;
  if (split){
    curves = SIZE_BUCKETS.map(b => {
      const sub = subset.filter(d => b.test(d.u));
      return {label:b.lab, color:cssv(b.cv), sub, series:medianCurve(sub, delta)};
    }).filter(c => c.series.length);
  } else {
    curves = [{label:null, color:cssv('--blue'), sub:subset, series:medianCurve(subset, delta)}];
  }

  const svg = document.getElementById('resp');
  svg.innerHTML = '';
  const W = 900, H = 300, mL = 44, mR = 12, mT = 12, mB = 30;
  const iw = W - mL - mR, ih = H - mT - mB;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  const oMin = -30, oMax = 240;
  const X = o => mL + (o - oMin)/(oMax - oMin)*iw;

  const allS = curves.flatMap(c => c.series);
  if (!allS.length){
    const t = el('text', {x:W/2, y:H/2, 'text-anchor':'middle', fill:cssv('--muted'), 'font-size':13});
    t.textContent = 'No doses match these filters'; svg.appendChild(t);
    document.getElementById('resp-summary').innerHTML = '';
    document.getElementById('resp-legend').innerHTML = ''; return;
  }
  let yMin, yMax;
  if (delta){
    let lo = 0, hi = 0;
    allS.forEach(s => { lo = Math.min(lo, s.p25); hi = Math.max(hi, s.p75); });
    const pad = Math.max(1, (hi-lo)*0.1); yMin = lo-pad; yMax = hi+pad;
  } else { yMin = 2; yMax = 21; }
  const Y = v => mT + (1 - (Math.min(yMax,Math.max(yMin,v))-yMin)/(yMax-yMin))*ih;

  if (!delta){
    svg.appendChild(el('rect', {x:mL, y:Y(10), width:iw, height:Y(3.9)-Y(10), fill:cssv('--inrange'), opacity:0.10}));
    [3.9,10].forEach(v => svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v),
      stroke:cssv('--inrange'), 'stroke-width':1, 'stroke-dasharray':'4 4', opacity:.5})));
  } else {
    svg.appendChild(el('line', {x1:mL, y1:Y(0), x2:mL+iw, y2:Y(0), stroke:cssv('--axis'), 'stroke-width':1.5}));
  }
  const yticks = delta
    ? (() => { const out=[]; const step = (yMax-yMin)>12?4:2; for (let v=Math.ceil(yMin/step)*step; v<=yMax; v+=step) out.push(v); return out; })()
    : [2,5,8,11,14,17,20];
  yticks.forEach(v => {
    svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v), stroke:cssv('--grid'), 'stroke-width':1}));
    const t = el('text', {x:mL-8, y:Y(v), 'text-anchor':'end', 'dominant-baseline':'middle'});
    t.setAttribute('class','tick'); t.textContent = (delta && v>0?'+':'') + v; svg.appendChild(t);
  });
  for (let m=0; m<=240; m+=60){
    svg.appendChild(el('line', {x1:X(m), y1:mT, x2:X(m), y2:mT+ih, stroke:cssv('--grid'), 'stroke-width':1}));
    const t = el('text', {x:X(m), y:H-8, 'text-anchor':'middle'});
    t.setAttribute('class','tick'); t.textContent = (m/60) + 'h'; svg.appendChild(t);
  }
  svg.appendChild(el('line', {x1:X(0), y1:mT, x2:X(0), y2:mT+ih, stroke:cssv('--fast'), 'stroke-width':1.5, 'stroke-dasharray':'3 3'}));
  const dl0 = el('text', {x:X(0), y:mT+10, 'text-anchor':'middle', fill:cssv('--fast'), 'font-size':10, 'font-weight':600});
  dl0.textContent = 'dose'; svg.appendChild(dl0);

  const linePath = ser => { let d='M'+X(ser[0].o)+' '+Y(ser[0].p50); ser.forEach(s=>d+=' L'+X(s.o)+' '+Y(s.p50)); return d; };
  curves.forEach(c => {
    if (!split){
      let band = 'M' + X(c.series[0].o) + ' ' + Y(c.series[0].p75);
      c.series.forEach(s => band += ' L' + X(s.o) + ' ' + Y(s.p75));
      for (let i=c.series.length-1;i>=0;i--) band += ' L' + X(c.series[i].o) + ' ' + Y(c.series[i].p25);
      svg.appendChild(el('path', {d:band+' Z', fill:c.color, opacity:.24}));
    }
    svg.appendChild(el('path', {d:linePath(c.series), fill:'none', stroke:c.color,
      'stroke-width':2.5, 'stroke-linejoin':'round'}));
  });

  // hover
  const cross = el('line', {y1:mT, y2:mT+ih, stroke:cssv('--axis'), 'stroke-width':1, opacity:0});
  svg.appendChild(cross);
  const hit = el('rect', {x:mL, y:mT, width:iw, height:ih, fill:'transparent'});
  hit.style.cursor = 'crosshair';
  hit.addEventListener('pointermove', e => {
    const r = svg.getBoundingClientRect();
    const o = oMin + ((e.clientX-r.left)/r.width*W - mL)/iw*(oMax-oMin);
    const ref = curves[0].series;
    let best = ref[0]; for (const s of ref) if (Math.abs(s.o-o) < Math.abs(best.o-o)) best = s;
    cross.setAttribute('x1', X(best.o)); cross.setAttribute('x2', X(best.o)); cross.setAttribute('opacity',1);
    const hr = (best.o>=0?'+':'') + (best.o/60).toFixed(best.o%60?2:0) + ' h';
    let rows;
    if (split){
      rows = curves.map(c => { const s=c.series.find(x=>x.o===best.o);
        return s? '<div class="row">'+c.label+': '+(delta&&s.p50>0?'+':'')+s.p50.toFixed(1)+'</div>':''; }).join('');
    } else {
      rows = '<div class="row">Median '+(delta&&best.p50>0?'+':'')+best.p50.toFixed(1)+' mmol/L</div>'
        + '<div class="row">Middle 50%: '+best.p25.toFixed(1)+' to '+best.p75.toFixed(1)+'</div>'
        + '<div class="row">'+best.n+' doses w/ data</div>';
    }
    showTip(e, '<b>'+hr+'</b>'+rows);
  });
  hit.addEventListener('pointerleave', () => { hideTip(); cross.setAttribute('opacity',0); });
  svg.appendChild(hit);
  const yt = el('text', {x:13, y:mT+ih/2, 'text-anchor':'middle', transform:'rotate(-90 13 ' + (mT+ih/2) + ')'});
  yt.setAttribute('class','axtitle'); yt.textContent = delta ? 'change from dose (mmol/L)' : 'mmol/L'; svg.appendChild(yt);

  document.getElementById('resp-legend').innerHTML = split
    ? curves.map(c => '<span><span class="sw" style="background:'+c.color+'"></span>'
        + c.label + ' <span style="color:var(--muted)">n=' + c.sub.length + '</span></span>').join('')
    : '';

  const ser = curves[0].series;
  const at = m => ser.find(s => s.o === m);
  const g0med = quant(subset.map(d => d.g0), 0.5);
  const chgTxt = s => s == null ? '–' : (delta ? (s.p50>0?'+':'') + s.p50.toFixed(1) : s.p50.toFixed(1));
  const cards = split ? [['Doses', subset.length+''], ['Median start', g0med==null?'–':g0med.toFixed(1)]]
    : [['Doses', subset.length+''], ['Median start', g0med==null?'–':g0med.toFixed(1)+' mmol/L'],
       [delta?'Change @2h':'Median @2h', chgTxt(at(120))], [delta?'Change @3h':'Median @3h', chgTxt(at(180))]];
  document.getElementById('resp-summary').innerHTML = cards.map(([l,v]) =>
    '<div class="card"><b>' + v + '</b>' + l + '</div>').join('');

  renderScatter(subset);
}

// ---- Correction-factor scatter: units vs drop by +3h ----
function renderScatter(subset){
  const i180 = DATA.response.offsets.indexOf(180);
  const pts = [];
  subset.forEach(d => { const g = d.r[i180]; if (g != null) pts.push({u:d.u, drop:+(d.g0 - g).toFixed(1)}); });
  const svg = document.getElementById('scatter');
  svg.innerHTML = '';
  const W = 900, H = 260, mL = 44, mR = 12, mT = 14, mB = 34;
  const iw = W - mL - mR, ih = H - mT - mB;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  if (pts.length < 3){
    const t = el('text', {x:W/2, y:H/2, 'text-anchor':'middle', fill:cssv('--muted'), 'font-size':13});
    t.textContent = 'Not enough doses with a +3 h reading'; svg.appendChild(t);
    document.getElementById('scatter-summary').innerHTML = ''; return;
  }
  // cap x at the 90th pct of units so a few big outliers don't crush the cluster
  const us = pts.map(p => p.u).sort((a,b)=>a-b);
  const p90 = us[Math.floor((us.length-1)*0.9)];
  const uMax = Math.max(10, Math.min(us[us.length-1], p90 + 2));
  const shown = pts.filter(p => p.u <= uMax);
  const off = pts.length - shown.length;
  let dLo = Math.min(0, ...shown.map(p => p.drop)), dHi = Math.max(0, ...shown.map(p => p.drop));
  const dp = Math.max(1,(dHi-dLo)*0.08); dLo -= dp; dHi += dp;
  const X = u => mL + u/uMax*iw;
  const Y = v => mT + (1 - (v-dLo)/(dHi-dLo))*ih;

  // zero line
  svg.appendChild(el('line', {x1:mL, y1:Y(0), x2:mL+iw, y2:Y(0), stroke:cssv('--axis'), 'stroke-width':1.5}));
  // y ticks
  const step = (dHi-dLo)>12?4:2;
  for (let v=Math.ceil(dLo/step)*step; v<=dHi; v+=step){
    svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v), stroke:cssv('--grid'), 'stroke-width':1}));
    const t = el('text', {x:mL-8, y:Y(v), 'text-anchor':'end', 'dominant-baseline':'middle'});
    t.setAttribute('class','tick'); t.textContent = (v>0?'+':'')+v; svg.appendChild(t);
  }
  for (let u=0; u<=uMax; u+=Math.ceil(uMax/8)){
    const t = el('text', {x:X(u), y:H-10, 'text-anchor':'middle'});
    t.setAttribute('class','tick'); t.textContent = u; svg.appendChild(t);
  }
  // least-squares fit over the shown (non-outlier) doses
  const n = shown.length, sx = shown.reduce((a,p)=>a+p.u,0), sy = shown.reduce((a,p)=>a+p.drop,0);
  const sxx = shown.reduce((a,p)=>a+p.u*p.u,0), sxy = shown.reduce((a,p)=>a+p.u*p.drop,0);
  const syy = shown.reduce((a,p)=>a+p.drop*p.drop,0);
  const denom = n*sxx - sx*sx;
  const b = denom ? (n*sxy - sx*sy)/denom : 0;
  const a = (sy - b*sx)/n;
  const r = Math.sqrt(Math.max(0,(n*sxy-sx*sy)*(n*sxy-sx*sy)/(denom*(n*syy-sy*sy)||1)));
  // points (deterministic jitter so integer units don't stack)
  shown.forEach((p,idx) => {
    const jx = ((idx*37)%11 - 5)*0.03;
    svg.appendChild(el('circle', {cx:X(p.u+jx), cy:Y(p.drop), r:3.4, fill:cssv('--blue'),
      opacity:.5, stroke:cssv('--surface'), 'stroke-width':.5}));
  });
  if (off > 0){
    const t = el('text', {x:mL+iw, y:mT+2, 'text-anchor':'end', fill:cssv('--muted'), 'font-size':10.5});
    t.textContent = off + ' dose' + (off>1?'s':'') + ' > ' + uMax + ' U off-scale';
    svg.appendChild(t);
  }
  // fit line
  svg.appendChild(el('line', {x1:X(0), y1:Y(a), x2:X(uMax), y2:Y(a+b*uMax),
    stroke:cssv('--fast'), 'stroke-width':2.5}));
  const yt = el('text', {x:13, y:mT+ih/2, 'text-anchor':'middle', transform:'rotate(-90 13 ' + (mT+ih/2) + ')'});
  yt.setAttribute('class','axtitle'); yt.textContent = 'drop by 3 h (mmol/L)'; svg.appendChild(yt);
  const xt = el('text', {x:mL+iw/2, y:H-1, 'text-anchor':'middle'});
  xt.setAttribute('class','axtitle'); xt.textContent = 'dose (units)'; svg.appendChild(xt);

  document.getElementById('scatter-summary').innerHTML = [
    ['Doses fitted', n+''],
    ['Drop / unit', b.toFixed(2) + ' mmol/U'],
    ['Fit r', r.toFixed(2)],
  ].map(([l,v]) => '<div class="card"><b>' + v + '</b>' + l + '</div>').join('');
}

// ---- Overnight & dawn (reuses the AGP percentile bins, 00:00–09:00) ----
function renderOvernight(){
  const A = DATA.agp.filter(d => d.t <= 540 && d.p50 != null);
  const svg = document.getElementById('overnight');
  svg.innerHTML = '';
  const W = 900, H = 260, mL = 44, mR = 12, mT = 12, mB = 28;
  const iw = W - mL - mR, ih = H - mT - mB;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  const tMax = 540, yMin = 2, yMax = 18;
  const X = t => mL + t/tMax*iw;
  const Y = v => mT + (1 - (Math.min(yMax,Math.max(yMin,v))-yMin)/(yMax-yMin))*ih;

  svg.appendChild(el('rect', {x:mL, y:Y(10), width:iw, height:Y(3.9)-Y(10), fill:cssv('--inrange'), opacity:0.10}));
  [3.9,10].forEach(v => svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v),
    stroke:cssv('--inrange'), 'stroke-width':1, 'stroke-dasharray':'4 4', opacity:.5})));
  [2,6,10,14,18].forEach(v => {
    svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v), stroke:cssv('--grid'), 'stroke-width':1}));
    const t = el('text', {x:mL-8, y:Y(v), 'text-anchor':'end', 'dominant-baseline':'middle'});
    t.setAttribute('class','tick'); t.textContent = v; svg.appendChild(t);
  });
  for (let h=0; h<=9; h+=3){
    const t = el('text', {x:X(h*60), y:H-8, 'text-anchor':'middle'});
    t.setAttribute('class','tick'); t.textContent = (h<10?'0':'')+h+':00'; svg.appendChild(t);
  }
  let band = 'M' + X(A[0].t) + ' ' + Y(A[0].p75);
  A.forEach(p => band += ' L' + X(p.t) + ' ' + Y(p.p75));
  for (let i=A.length-1;i>=0;i--) band += ' L' + X(A[i].t) + ' ' + Y(A[i].p25);
  svg.appendChild(el('path', {d:band+' Z', fill:cssv('--blue'), opacity:.24}));
  let dm = 'M' + X(A[0].t) + ' ' + Y(A[0].p50);
  A.forEach(p => dm += ' L' + X(p.t) + ' ' + Y(p.p50));
  svg.appendChild(el('path', {d:dm, fill:'none', stroke:cssv('--blue'), 'stroke-width':2.5, 'stroke-linejoin':'round'}));

  const cross = el('line', {y1:mT, y2:mT+ih, stroke:cssv('--axis'), 'stroke-width':1, opacity:0});
  svg.appendChild(cross);
  const hit = el('rect', {x:mL, y:mT, width:iw, height:ih, fill:'transparent'});
  hit.style.cursor = 'crosshair';
  hit.addEventListener('pointermove', e => {
    const r = svg.getBoundingClientRect();
    const t = ((e.clientX-r.left)/r.width*W - mL)/iw*tMax;
    let best = A[0]; for (const p of A) if (Math.abs(p.t-t) < Math.abs(best.t-t)) best = p;
    cross.setAttribute('x1', X(best.t)); cross.setAttribute('x2', X(best.t)); cross.setAttribute('opacity',1);
    const hh = Math.floor(best.t/60), mm = best.t%60;
    showTip(e, '<b>'+(hh<10?'0':'')+hh+':'+(mm<10?'0':'')+mm+'</b>'
      + '<div class="row">Median '+best.p50.toFixed(1)+'</div>'
      + '<div class="row">IQR '+best.p25.toFixed(1)+'–'+best.p75.toFixed(1)+'</div>');
  });
  hit.addEventListener('pointerleave', () => { hideTip(); cross.setAttribute('opacity',0); });
  svg.appendChild(hit);

  const at = m => A.find(d => d.t === m);
  const a3 = at(180), a7 = at(420);
  const rise = (a3 && a7) ? (a7.p50 - a3.p50) : null;
  document.getElementById('overnight-summary').innerHTML = [
    ['Median 3am', a3? a3.p50.toFixed(1)+' mmol/L':'–'],
    ['Median 7am', a7? a7.p50.toFixed(1)+' mmol/L':'–'],
    ['Dawn rise 3→7am', rise==null?'–':(rise>0?'+':'')+rise.toFixed(1)+' mmol/L'],
  ].map(([l,v]) => '<div class="card"><b>' + v + '</b>' + l + '</div>').join('');
}

// ---- Day explorer ----
const DAY_DATES = Object.keys(DATA.dayDetail).sort();
let dayIdx = DAY_DATES.length - 1;
function buildDaySelector(){
  const sel = document.getElementById('day-select');
  sel.innerHTML = DAY_DATES.map((d,i) =>
    '<option value="'+i+'">' + new Date(d+'T00:00:00').toLocaleDateString(undefined,
      {weekday:'short', month:'short', day:'numeric'}) + '</option>').join('');
  sel.value = dayIdx;
  sel.onchange = () => { dayIdx = +sel.value; renderDay(); };
  document.getElementById('day-prev').onclick = () => { if (dayIdx>0){ dayIdx--; sel.value=dayIdx; renderDay(); } };
  document.getElementById('day-next').onclick = () => { if (dayIdx<DAY_DATES.length-1){ dayIdx++; sel.value=dayIdx; renderDay(); } };
}
function renderDay(){
  const date = DAY_DATES[dayIdx];
  const rec = DATA.dayDetail[date];
  const svg = document.getElementById('day');
  svg.innerHTML = '';
  const W = 900, H = 300, mL = 40, mR = 12, mT = 14, mB = 40;
  const iw = W - mL - mR, ih = H - mT - mB;
  svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
  const yMin = 2, yMax = 21, DAY = 86400;
  const X = s => mL + s/DAY*iw;
  const Y = v => mT + (1 - (Math.min(yMax,Math.max(yMin,v))-yMin)/(yMax-yMin))*ih;

  svg.appendChild(el('rect', {x:mL, y:Y(10), width:iw, height:Y(3.9)-Y(10), fill:cssv('--inrange'), opacity:0.10}));
  [3.9,10].forEach(v => svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v),
    stroke:cssv('--inrange'), 'stroke-width':1, 'stroke-dasharray':'4 4', opacity:.5})));
  [2,6,10,14,18].forEach(v => {
    svg.appendChild(el('line', {x1:mL, y1:Y(v), x2:mL+iw, y2:Y(v), stroke:cssv('--grid'), 'stroke-width':1}));
    const t = el('text', {x:mL-8, y:Y(v), 'text-anchor':'end', 'dominant-baseline':'middle'});
    t.setAttribute('class','tick'); t.textContent = v; svg.appendChild(t);
  });
  for (let h=0; h<=24; h+=3){
    const x = X(h*3600);
    svg.appendChild(el('line', {x1:x, y1:mT, x2:x, y2:mT+ih, stroke:cssv('--grid'), 'stroke-width':1}));
    const t = el('text', {x:x, y:H-22, 'text-anchor':'middle'});
    t.setAttribute('class','tick'); t.textContent = (h<10?'0':'')+h+':00'; svg.appendChild(t);
  }
  // glucose line, break gaps > 30 min
  let d = '', prev = null;
  rec.g.forEach(([s,v]) => { d += (prev===null || s-prev>1800 ? ' M':' L') + X(s) + ' ' + Y(v); prev = s; });
  if (d) svg.appendChild(el('path', {d, fill:'none', stroke:cssv('--blue'), 'stroke-width':1.8,
    'stroke-linejoin':'round', 'stroke-linecap':'round'}));
  // doses
  const baseY = mT + ih;
  rec.ins.forEach(([s,u,typ]) => {
    const x = X(s), c = typ==='fast'? cssv('--fast'):cssv('--slow');
    const h = Math.min(52, 10 + u*2.4);
    svg.appendChild(el('line', {x1:x, y1:baseY, x2:x, y2:baseY-h, stroke:c, 'stroke-width':2}));
    svg.appendChild(el('circle', {cx:x, cy:baseY-h, r:5, fill:c, stroke:cssv('--surface'), 'stroke-width':1.5}));
    const lab = el('text', {x:x, y:baseY-h-7, 'text-anchor':'middle', fill:c, 'font-size':11, 'font-weight':650});
    lab.textContent = u; svg.appendChild(lab);
  });

  const gv = rec.g.map(p => p[1]);
  const mean = gv.length ? gv.reduce((a,b)=>a+b,0)/gv.length : null;
  const tir = gv.length ? 100*gv.filter(v=>v>=3.9&&v<=10).length/gv.length : null;
  const fast = rec.ins.filter(i=>i[2]==='fast').reduce((a,i)=>a+i[1],0);
  const slow = rec.ins.filter(i=>i[2]!=='fast').reduce((a,i)=>a+i[1],0);
  document.getElementById('day-summary').innerHTML = [
    ['Mean', mean==null?'–':mean.toFixed(1)+' mmol/L'],
    ['In range', tir==null?'–':Math.round(tir)+'%'],
    ['Fast', fast+' U'], ['Slow', slow+' U'],
  ].map(([l,v]) => '<div class="card"><b>' + v + '</b>' + l + '</div>').join('');
}

function renderAll(){ renderTIR(); renderAGP(); renderResponse(); renderOvernight(); renderDay(); renderTrace(); }
buildRespFilters();
buildDaySelector();
renderAll();
renderTable();
addEventListener('resize', () => { /* SVGs are responsive via viewBox */ });
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
