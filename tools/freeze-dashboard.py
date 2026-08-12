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

# Runs after the dashboard has drawn itself. A <select>'s current choice lives
# in a DOM property, which serialisation does not capture — copy it into the
# attribute so it survives the dump.
FREEZE_HELPER = """
<script>
(function () {
  function pin() {
    document.querySelectorAll('select').forEach(function (sel) {
      var opt = sel.options[sel.selectedIndex];
      if (opt) opt.setAttribute('selected', 'selected');
      sel.setAttribute('data-frozen-label', opt ? opt.textContent : '');
    });
    document.documentElement.setAttribute('data-frozen', '1');
  }
  if (document.readyState === 'complete') setTimeout(pin, 0);
  else window.addEventListener('load', function () { setTimeout(pin, 0); });
})();
</script>
"""

FROZEN_CSS = """
<style id="frozen-style">
  /* The page no longer responds to input; stop it looking as though it might. */
  .theme, #day-prev, #day-next { display: none !important; }
  .chip { cursor: default !important; }
  .daynav { align-items: baseline; }
  .frozen-day { font-weight: 600; }
  .frozen-note {
    margin: 0 0 18px; padding: 10px 14px; border-radius: 10px;
    background: rgba(127, 127, 127, .10);
    border: 1px solid rgba(127, 127, 127, .22);
    font-size: 13px; line-height: 1.5;
  }
</style>
"""


def dump_dom(src, width, chrome, budget_ms):
    """Render src in headless Chrome and return the post-JavaScript DOM."""
    with open(src, encoding="utf-8") as fh:
        page = fh.read()
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
    ap.add_argument("--chrome", default=CHROME)
    ap.add_argument("--virtual-time", type=int, default=8000,
                    help="milliseconds of virtual time to let the page draw")
    args = ap.parse_args()

    src = os.path.expanduser(args.src)
    out = os.path.expanduser(args.out)
    if not os.path.exists(src):
        sys.exit(f"No dashboard at {src} — run build-dashboard.py first.")
    if not os.path.exists(args.chrome):
        sys.exit(f"Chrome not found at {args.chrome} (pass --chrome).")

    page = dump_dom(src, args.width, args.chrome, args.virtual_time)
    if 'data-frozen="1"' not in page:
        print("warning: freeze helper did not run; the page may not have finished "
              "drawing. Try a larger --virtual-time.", file=sys.stderr)

    drawn = page.count("<path")
    page = re.sub(r"<script\b.*?</script>", "", page, flags=re.S)
    page = collapse_filters(page)
    page = freeze_day_picker(page)

    note = ('<p class="frozen-note">Static snapshot — charts are fixed at the '
            'settings shown and the controls do not respond. Open '
            '<strong>glucose-dashboard.html</strong> for the interactive version.</p>')
    if "<h1" in page:
        page = re.sub(r"(</header>|</h1>)", r"\1" + note, page, count=1)
    else:
        page = page.replace("<body>", "<body>" + note, 1)
    page = page.replace("</head>", FROZEN_CSS + "</head>", 1)

    with open(out, "w", encoding="utf-8") as fh:
        fh.write(page)

    print(f"Wrote {out}", file=sys.stderr)
    print(f"  {os.path.getsize(out) / 1024:.0f} KB, no scripts, "
          f"{page.count('<svg')} charts, {drawn} drawn paths", file=sys.stderr)


if __name__ == "__main__":
    main()
