#!/usr/bin/env python3
"""Freeze the dashboard into a static, script-free page.

`build-dashboard.py` emits a page whose numbers and charts are drawn by
JavaScript from an inlined dataset — 340 KB of file, of which only ~10 KB is
markup. Anywhere scripting is unavailable that renders as empty cards: correct
headings and captions, no data. iOS Quick Look (tapping an .html file in the
Files app) is the case that matters here, since that is how the dashboard gets
opened on an iPad.

So: load the page in headless Chrome, let it draw itself, then serialise the
resulting DOM and throw the scripts away. The charts are already `viewBox` SVG
with no fixed pixel widths, so they survive as responsive static images.

What is lost is interactivity. Rather than leave dead buttons on the page, the
filter chips collapse to whichever option was active — so the reader can still
see that a chart shows fast doses started above 10 — and the day picker becomes
a plain label.

Usage:
    python3 tools/freeze-dashboard.py
    python3 tools/freeze-dashboard.py --in DASH.html --out FROZEN.html --width 1180

Chrome is found via --chrome or the usual macOS install path.
"""
import argparse
import html as htmllib
import os
import re
import shutil
import subprocess
import sys
import tempfile

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Runs after the dashboard has drawn itself, and does three things.
#
# 1. Pins the theme. Chart colours are read out of CSS custom properties at draw
#    time (`cssv('--blue')` and friends), so the theme has to be set and the
#    charts redrawn, in that order, or the SVG keeps the old palette.
# 2. Rebuilds the day explorer as a pure-CSS control. Every day is rendered in
#    turn by driving the existing <select>, and each result is captured into its
#    own panel. A hidden radio per day, plus <label>s for previous/next and a
#    jump strip, then does the switching with no script at all — the same
#    technique as CSS tabs. Deliberately not :target (it hijacks the URL and
#    back button) and not :has() (needs a newer Safari than we can assume).
# 3. Pins any remaining <select> choice into an attribute, since serialisation
#    captures attributes but not properties.
FREEZE_HELPER = """
<script>
(function () {
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function pinSelects() {
    document.querySelectorAll('select').forEach(function (sel) {
      var opt = sel.options[sel.selectedIndex];
      if (opt) opt.setAttribute('selected', 'selected');
      sel.setAttribute('data-frozen-label', opt ? opt.textContent : '');
    });
  }

  function buildDays(limit) {
    var sel = document.getElementById('day-select');
    var svg = document.getElementById('day');
    var summary = document.getElementById('day-summary');
    var nav = document.querySelector('.daynav');
    if (!sel || !svg || !summary || !nav) return 0;

    var days = Array.prototype.map.call(sel.options, function (o) {
      return { value: o.value, label: o.textContent };
    });
    if (limit > 0 && days.length > limit) days = days.slice(days.length - limit);

    var panels = [], strip = [], rules = [];
    days.forEach(function (day, i) {
      // Drive the page's own handler so we capture exactly what it draws.
      sel.value = day.value;
      sel.dispatchEvent(new Event('change'));

      var prev = i > 0 ? '<label class="chip" for="fday-' + (i - 1) + '">&larr;</label>'
                       : '<span class="chip chip-off">&larr;</span>';
      var next = i < days.length - 1 ? '<label class="chip" for="fday-' + (i + 1) + '">&rarr;</label>'
                                     : '<span class="chip chip-off">&rarr;</span>';
      panels.push(
        '<div class="fday-panel fday-panel-' + i + '">' +
          '<div class="daynav">' + prev +
            '<span class="frozen-day">' + esc(day.label) + '</span>' + next +
          '</div>' +
          '<div class="respsum">' + summary.innerHTML + '</div>' +
          svg.outerHTML +
        '</div>'
      );
      strip.push('<label class="fday-tab fday-tab-' + i + '" for="fday-' + i + '">' +
                 esc(day.label) + '</label>');
      rules.push('#fday-' + i + ':checked ~ .fday-panels .fday-panel-' + i +
                 '{display:block}');
      rules.push('#fday-' + i + ':checked ~ .fday-strip .fday-tab-' + i +
                 '{background:var(--blue);color:#fff;border-color:var(--blue)}');
    });

    var last = days.length - 1;
    var inputs = days.map(function (_, i) {
      return '<input class="fday-radio" type="radio" name="fday" id="fday-' + i + '"' +
             (i === last ? ' checked' : '') + '>';
    }).join('');

    var style = document.createElement('style');
    style.id = 'frozen-days-style';
    style.textContent = rules.join('\\n');
    document.head.appendChild(style);

    var host = document.createElement('div');
    host.className = 'fday-switch';
    host.innerHTML = inputs +
      '<div class="fday-strip">' + strip.join('') + '</div>' +
      '<div class="fday-panels">' + panels.join('') + '</div>';

    // The original nav and chart are now represented inside every panel.
    nav.parentNode.insertBefore(host, nav);
    nav.remove();
    summary.remove();
    svg.remove();
    return days.length;
  }

  function run() {
    var root = document.documentElement;
    var theme = root.getAttribute('data-freeze-theme');
    if (theme && theme !== 'auto') {
      root.setAttribute('data-theme', theme);
      // Redraw so the baked-in SVG colours match the theme we just set.
      if (typeof renderAll === 'function') renderAll();
    }
    var n = 0;
    try { n = buildDays(+(root.getAttribute('data-freeze-days') || 0)); }
    catch (e) { root.setAttribute('data-freeze-error', String(e && e.message || e)); }
    pinSelects();
    root.setAttribute('data-frozen-days', String(n));
    root.setAttribute('data-frozen', '1');
  }

  if (document.readyState === 'complete') setTimeout(run, 0);
  else window.addEventListener('load', function () { setTimeout(run, 0); });
})();
</script>
"""

FROZEN_CSS = """
<style id="frozen-style">
  /* Most of the page no longer responds to input; stop it looking as though
     it might. The day switcher below is the exception — it really works. */
  .theme { display: none !important; }
  .chip { cursor: default !important; }
  .frozen-day { font-weight: 600; }
  .frozen-note {
    margin: 0 0 18px; padding: 10px 14px; border-radius: 10px;
    background: rgba(127, 127, 127, .10);
    border: 1px solid rgba(127, 127, 127, .22);
    font-size: 13px; line-height: 1.5;
  }

  /* Pure-CSS day switcher: a hidden radio per day, <label>s to check them. */
  .fday-radio { position: absolute; left: -9999px; width: 1px; height: 1px; }
  .fday-panel { display: none; }
  .fday-panel .daynav { display: flex; gap: 10px; align-items: center; margin-bottom: 10px; }
  .fday-panel label.chip { cursor: pointer !important; user-select: none; }
  .chip-off { opacity: .35; }
  /* Wrap rather than scroll. Nothing can auto-scroll a strip without script,
     so a scrolling row would routinely hide the day that is selected. */
  .fday-strip {
    display: flex; flex-wrap: wrap; gap: 6px; padding: 2px 0 14px;
  }
  .fday-tab {
    flex: 0 0 auto; cursor: pointer; user-select: none; white-space: nowrap;
    font-size: 12px; padding: 5px 10px; border-radius: 999px;
    border: 1px solid var(--ring); background: var(--surface); color: var(--muted);
  }
  /* Comfortable tap targets on a touch screen. */
  @media (pointer: coarse) {
    .fday-tab { padding: 8px 13px; font-size: 13px; }
    .fday-panel label.chip { padding: 8px 14px; }
  }
</style>
"""


def dump_dom(src, width, chrome, budget_ms, theme, days):
    """Render src in headless Chrome and return the post-JavaScript DOM."""
    with open(src, encoding="utf-8") as fh:
        page = fh.read()

    # The helper reads its settings off <html> rather than being templated, so
    # the script stays a fixed string and there is nothing to escape.
    opts = f' data-freeze-theme="{theme}" data-freeze-days="{days}"'
    if re.search(r"<html\b", page):
        page = re.sub(r"<html\b", "<html" + opts, page, count=1)
    else:
        sys.exit("No <html> element found in the source dashboard.")

    if "</body>" in page:
        page = page.replace("</body>", FREEZE_HELPER + "</body>", 1)
    else:
        page += FREEZE_HELPER

    tmpdir = tempfile.mkdtemp(prefix="freeze-dash-")
    try:
        staged = os.path.join(tmpdir, "staged.html")
        with open(staged, "w", encoding="utf-8") as fh:
            fh.write(page)
        proc = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             f"--window-size={width},2000",
             f"--virtual-time-budget={budget_ms}",
             "--dump-dom", "file://" + staged],
            capture_output=True, text=True, timeout=180,
        )
        if not proc.stdout.strip():
            sys.exit(f"Chrome produced no DOM.\n{proc.stderr[-2000:]}")
        return proc.stdout
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def collapse_filters(page):
    """Keep only the pressed chip in each group; drop the rest."""
    def one_group(m):
        block = m.group(0)
        chips = re.findall(r'<button class="chip"[^>]*>.*?</button>', block, re.S)
        pressed = [c for c in chips if 'aria-pressed="true"' in c]
        # An unpressed group means the state never got set — leave it be rather
        # than silently blanking the group.
        if not pressed or len(pressed) == len(chips):
            return block
        for chip in chips:
            if chip not in pressed:
                block = block.replace(chip, "", 1)
        return block

    return re.sub(r'<div class="chips">.*?</div>', one_group, page, flags=re.S)


def freeze_day_picker(page):
    """Replace the <select> with the day it was showing."""
    def one_select(m):
        block = m.group(0)
        label = re.search(r'data-frozen-label="([^"]*)"', block)
        if not label:
            chosen = re.search(r'<option[^>]*selected[^>]*>([^<]*)', block)
            label_text = chosen.group(1) if chosen else ""
        else:
            label_text = label.group(1)
        if not label_text:
            return block
        return f'<span class="frozen-day">{htmllib.escape(label_text)}</span>'

    return re.sub(r'<select\b.*?</select>', one_select, page, flags=re.S)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    health = "~/Library/Mobile Documents/com~apple~CloudDocs/Health"
    ap.add_argument("--in", dest="src", default=f"{health}/glucose-dashboard.html")
    ap.add_argument("--out", default=f"{health}/glucose-dashboard-static.html")
    ap.add_argument("--width", type=int, default=1180,
                    help="viewport width used while rendering (default: iPad landscape)")
    ap.add_argument("--theme", choices=("light", "dark", "auto"), default="light",
                    help="bake in a theme; 'auto' follows the viewer's system setting, "
                         "but note chart colours are fixed at whatever was current "
                         "when they were drawn")
    ap.add_argument("--days", type=int, default=0,
                    help="keep only the last N days in the day explorer (0 = all)")
    ap.add_argument("--chrome", default=CHROME)
    ap.add_argument("--virtual-time", type=int, default=20000,
                    help="milliseconds of virtual time to let the page draw")
    args = ap.parse_args()

    src = os.path.expanduser(args.src)
    out = os.path.expanduser(args.out)
    if not os.path.exists(src):
        sys.exit(f"No dashboard at {src} — run build-dashboard.py first.")
    if not os.path.exists(args.chrome):
        sys.exit(f"Chrome not found at {args.chrome} (pass --chrome).")

    page = dump_dom(src, args.width, args.chrome, args.virtual_time,
                    args.theme, max(0, args.days))
    if 'data-frozen="1"' not in page:
        print("warning: freeze helper did not run; the page may not have finished "
              "drawing. Try a larger --virtual-time.", file=sys.stderr)
    err = re.search(r'data-freeze-error="([^"]*)"', page)
    if err:
        print(f"warning: day switcher failed to build: {err.group(1)}", file=sys.stderr)
    n_days = re.search(r'data-frozen-days="(\d+)"', page)
    n_days = int(n_days.group(1)) if n_days else 0

    drawn = page.count("<path")
    page = re.sub(r"<script\b.*?</script>", "", page, flags=re.S)
    page = collapse_filters(page)
    page = freeze_day_picker(page)

    switcher = (f" The day explorer still works — tap a date or the arrows to move "
                f"through all {n_days} days." if n_days else "")
    note = ('<p class="frozen-note">Static snapshot — the charts are fixed at the '
            'settings shown, so the filter buttons do not respond.' + switcher +
            ' Open <strong>glucose-dashboard.html</strong> for the fully '
            'interactive version.</p>')
    if "<h1" in page:
        page = re.sub(r"(</header>|</h1>)", r"\1" + note, page, count=1)
    else:
        page = page.replace("<body>", "<body>" + note, 1)
    page = page.replace("</head>", FROZEN_CSS + "</head>", 1)

    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)

    print(f"Wrote {out}", file=sys.stderr)
    print(f"  {os.path.getsize(out) / 1024:.0f} KB, {page.count('<script')} scripts, "
          f"{page.count('<svg')} charts, {drawn} drawn paths, "
          f"theme={args.theme}, {n_days} switchable days", file=sys.stderr)


if __name__ == "__main__":
    main()
