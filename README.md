# Glucose Watch

A minimal Wear OS app for Samsung Galaxy Watch 4 Classic 46mm. Shows live
blood glucose from [Juggluco](https://www.juggluco.nl/) on the watch face and
provides a one-tap insulin logger. Personal tooling — no cloud, no phone
companion, no account.

## What it does

**Watch face**
- 24-hour digital time (small, top)
- Current blood glucose in mmol/L (large, centre, colour-coded)
  - green for 4.0–10.0
  - amber for 3.5–4.0 or 10.0–13.0
  - red below 3.5 or above 13.0
- Trend arrow next to the glucose (↑ ↗ → ↘ ↓)
- Battery percentage below the glucose number (red below 15%)
- "X min" since last reading at the bottom
- Small red dot if no reading received for ≥5 min
- Battery and "X min" hidden in ambient mode

**Insulin logger** (tap the glucose number on the watch face)
- Number picker, 1–50 whole units, driven by the rotating bezel
- Primary row — single tap commits both the units and the type:
  - **Fast** (amber) — bolus / mealtime insulin
  - **Slow** (blue) — basal / background insulin
- Secondary row:
  - **✕ Cancel** (gray) — close without writing anything to Room
  - **Del** (red) — delete the most recent entry (longer vibration so an
    accidental tap is noticeable; no confirmation dialog)
- Brief vibration on commit, longer pulse on delete
- Each logged entry captures: units, type, timestamp, glucose snapshot, trend

**Local storage**
- Room SQLite database on the watch (`bg.db`)
- No automatic sync; data is pulled to a desktop via an ADB-driven script

## Target

| Component | Value |
| --- | --- |
| Watch | Samsung Galaxy Watch 4 Classic 46mm (and any Wear OS 3+ round) |
| OS | Wear OS 3 / One UI Watch 4.5 |
| Glucose source | Juggluco for Wear OS (tested with 10.9.1-wear) |
| minSdk | 30 |
| targetSdk | 34 |
| Language | Kotlin 2.0 |
| UI toolkit | Jetpack Compose for Wear OS (logger), AndroidX WatchFace (face) |

## How the glucose pipeline works

A singleton `GlucoseRepository` exposes a `StateFlow<GlucoseReading?>`. The
watch face renderer and the logger UI both read from it. Three providers can
write into it; multiple can run simultaneously and the most recent value wins:

1. **`JugglucoBroadcastReceiver`** (primary on real hardware)
   - Listens for the action `com.eveningoutpost.dexdrip.BgEstimate` (xDrip+
     broadcast format — what the Wear OS build of Juggluco actually emits)
   - Also handles `glucodata.Minute` keys (the GlucoDataAuto convention) as a
     fallback for phones or other Juggluco builds
   - Registered both in the manifest and dynamically in `BgApplication`
2. **`JugglucoHttpProvider`** (fallback)
   - Polls `http://127.0.0.1:17580/api/v1/entries/current.json` every 60 s
     (Nightscout-shape JSON)
   - The Wear OS build of Juggluco doesn't currently run an HTTP server, so
     this typically fails — but it's already wired and the cleartext-to-
     localhost network security config is in place if/when Juggluco enables it
3. **`MockGlucoseProvider`** (emulator only)
   - Random walk between 3.0 and 15.0 mmol/L with realistic momentum, every
     minute
   - Activated automatically when `Build.HARDWARE` is `goldfish` or `ranchu`
     so it doesn't clobber real data on a real watch

### Switching providers

All wiring is in `BgApplication.onCreate`:

```kotlin
if (isEmulator()) {
    GlucoseRepository.bind(MockGlucoseProvider(appScope))
} else {
    GlucoseRepository.bind(JugglucoHttpProvider(appScope))
}
```

The broadcast receiver runs independently of `bind(...)` — it pushes straight
into the repository via `GlucoseRepository.submit()`. Remove the `bind` call
entirely to make the app broadcast-only.

## Project layout

```
.
├── app/
│   ├── build.gradle.kts          # KSP for Room, Compose plugin, deps
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── res/
│       │   ├── values/strings.xml
│       │   ├── xml/watch_face.xml
│       │   ├── xml/network_security_config.xml   # cleartext to 127.0.0.1
│       │   ├── drawable/                          # launcher + watch-face preview
│       │   └── mipmap-anydpi-v26/ic_launcher.xml
│       └── java/com/wb/bgapp/
│           ├── BgApplication.kt                   # provider wiring + receiver registration
│           ├── data/
│           │   ├── GlucoseReading.kt              # data class + trend enum
│           │   ├── GlucoseProvider.kt             # provider interface
│           │   ├── GlucoseRepository.kt           # singleton StateFlow holder
│           │   ├── MockGlucoseProvider.kt
│           │   ├── JugglucoBroadcastReceiver.kt   # xDrip+ + glucodata.Minute parsing
│           │   ├── JugglucoHttpProvider.kt        # Nightscout-shape HTTP polling
│           │   ├── InsulinEntry.kt                # Room entity
│           │   ├── InsulinDao.kt
│           │   └── AppDatabase.kt
│           ├── watchface/
│           │   ├── BgWatchFaceService.kt          # CanvasRenderer2 + tap listener
│           │   └── WatchFaceConfigActivity.kt     # no-op editor (required by Wear OS 3)
│           └── ui/
│               ├── InsulinLoggerActivity.kt
│               └── InsulinLoggerScreen.kt         # Compose Picker + Fast/Slow buttons
├── tools/
│   ├── build-apk.sh                # assembleDebug + copy to ~/Downloads
│   └── export-log.sh               # ADB-pull Room DB → CSV on desktop
├── gradle/libs.versions.toml       # version catalog
└── settings.gradle.kts
```

## Prerequisites

- Android Studio (any recent stable). Its bundled JBR provides Java 17, which
  is enough — there's no need to install a separate JDK.
- Android SDK with platform 34 and build-tools installed (Android Studio will
  prompt for these on first sync).
- For emulator dev: a Wear OS system image (API 30 ARM64 was used during
  development).
- For real-device dev: Galaxy Watch 4 with Developer Options enabled and
  Juggluco installed.

`local.properties` should point at your SDK:

```
sdk.dir=/Users/you/Library/Android/sdk
```

## Build

**From Android Studio:** open the project root, let Gradle sync, click Run.

**From the command line:**

```bash
# build-apk.sh handles JAVA_HOME from the Android Studio bundle on macOS,
# runs assembleDebug, and copies a timestamped APK to ~/Downloads.
./tools/build-apk.sh

# Or directly:
./gradlew :app:assembleDebug
```

Output APK lives at `app/build/outputs/apk/debug/app-debug.apk` (~29 MB —
Compose and the WatchFace library are bulky; no further size work has been
done).

## Run on the emulator

```bash
# Boot a paired Wear OS AVD
~/Library/Android/sdk/emulator/emulator -avd Wear_OS_Large_Round

# Install
./gradlew :app:installDebug

# Activate the watch face (rather than picking from the UI)
adb shell am broadcast -a com.google.android.wearable.app.DEBUG_SURFACE \
  --es operation set-watchface \
  --ecn component com.wb.bgapp.debug/com.wb.bgapp.watchface.BgWatchFaceService

# Open the insulin logger directly
adb shell am start -n com.wb.bgapp.debug/com.wb.bgapp.ui.InsulinLoggerActivity
```

`MockGlucoseProvider` will start emitting readings within a minute. To
simulate the rotary bezel in Android Studio's emulator window, open Extended
Controls (`⋯` button) → **Virtual sensors** → **Wear OS** / Rotary input.

## Deploy to the real Galaxy Watch 4

### Option A — Wear Installer 2 (no developer mode required)

1. Build an APK: `./tools/build-apk.sh` (drops a versioned file in
   `~/Downloads`).
2. Get the APK onto the paired phone (Google Drive, AirDrop, or `adb push` if
   the phone is in File-Transfer USB mode).
3. Open **Wear Installer 2** on the phone → Add APK → select the file →
   Install to watch. Takes ~30 s over Bluetooth.

### Option B — ADB over Wi-Fi (fast iteration during development)

On the watch, enable Developer Options (Settings → About watch → Software
information → tap Software version 7×), then Developer options → ADB debugging
+ Debug over Wi-Fi. The watch screen will show an IP and either a fixed port
or a "Pair new device" panel with a one-time pairing port and 6-digit code.

From the laptop (modern pairing flow):

```bash
adb pair <watch-ip>:<pairing-port>      # enter the 6-digit code
adb connect <watch-ip>:<connect-port>   # the port shown on the main screen
adb devices                              # confirm the watch appears as "device"
```

Once connected, install straight from Gradle or the APK script:

```bash
adb -s <watch-ip>:<port> install -r -d app/build/outputs/apk/debug/app-debug.apk
```

The pair/connect ports rotate when the watch's Wi-Fi setting is toggled, so
expect to re-run `adb connect` after the watch sleeps for a long time.

## Activating the watch face

Long-press the watch face on the watch → swipe through faces → pick **BG
Watch**. Or do it remotely via ADB:

```bash
adb -s <device> shell am broadcast \
  -a com.google.android.wearable.app.DEBUG_SURFACE \
  --es operation set-watchface \
  --ecn component com.wb.bgapp.debug/com.wb.bgapp.watchface.BgWatchFaceService
```

Note: Wear OS 3 requires every watch face to declare an editor activity even
when there's nothing to configure. This project ships
`WatchFaceConfigActivity` as a no-op that immediately finishes; without it the
watch face is rejected as invalid by the WCS service.

## Verifying that glucose is being received

Both providers log their progress under tags `BgReceiver` and `BgHttp`:

```bash
adb -s <device> logcat -s BgReceiver:I BgHttp:I
```

Expected output once Juggluco is broadcasting:

```
I BgReceiver: received action=com.eveningoutpost.dexdrip.BgEstimate keys=...
I BgReceiver: submit mmol=5.5 trend=Stable at=1778533787603
```

If you see the `received` line but never `submit`, the broadcast's keys
aren't recognised — check the `keys=...` list and extend
`JugglucoBroadcastReceiver`.

If you see nothing at all, Juggluco probably isn't broadcasting (toggle in
Juggluco's settings) or is being frozen by Samsung's battery management —
see Troubleshooting.

## Insulin log: exporting to your desktop

The Room DB lives at `/data/data/com.wb.bgapp.debug/databases/bg.db` on the
watch. `tools/export-log.sh` pulls it via `adb run-as` (works because debug
builds are debuggable) and dumps `insulin_entries` to CSV:

```bash
./tools/export-log.sh                  # writes ./insulin-log.csv
./tools/export-log.sh ~/Desktop/bg.csv # custom path
```

If `sqlite3` is not on PATH it falls back to dropping the raw `.db` file
beside the requested output path — open it with [DB Browser for
SQLite](https://sqlitebrowser.org/) on the desktop.

From DB v3 onward the same run also writes a `<name>-glucose.csv` beside the
insulin CSV whenever the `glucose_entries` table exists (see *Glucose history*
below).

CSV columns:

| column | meaning |
| --- | --- |
| `id` | autoincrement primary key |
| `units` | integer 1–50 |
| `type` | `fast` or `slow` |
| `logged_at_local` | human-readable local timestamp |
| `timestampMs` | ms since epoch |
| `glucose_mmol` | glucose at the moment of the tap (nullable) |
| `trend` | trend enum name (`Stable`, `Rising`, etc.; nullable) |

## Glucose history

There are two ways glucose ends up on your desktop, and you'll usually want both:
the app records everything from now on, and Juggluco holds the back-history from
before the app started recording.

### Ongoing: persisted by the app (DB v3+)

`JugglucoBroadcastReceiver` already receives every reading (~1/min); from DB v3
the app also writes each one to the `glucose_entries` table in `bg.db`, keyed by
epoch minute so repeated same-minute broadcasts collapse to one row. No sensor-
change trigger and no cloud — it just accumulates. `tools/export-log.sh` dumps it
alongside the insulin CSV:

```bash
./tools/export-log.sh ~/Desktop/bg.csv   # → bg.csv (insulin) + bg-glucose.csv
```

Glucose CSV columns: `epoch_s, logged_at_local, glucose_mmol, glucose_mgdl,
trend`.

Caveat: the broadcast receiver is registered at runtime (in `BgApplication`), so
readings are only captured while the app process is alive. Samsung's battery
management can freeze it — the same *Unrestricted* battery setting the watch face
needs (see Troubleshooting) keeps this recording too. For a gap-free record,
periodically back-fill from Juggluco (below), which stores every reading itself.

### Back-history: from Juggluco's raw files

The full minute-by-minute history predating the app's own recording lives inside
**Juggluco** (`tk.glucodata`), which runs no HTTP server on Wear OS. It keeps each
sensor's readings in `files/sensors/<id>/polls.dat` as 20-byte little-endian
records — `int32 timestamp, int32 counter, int32 glucose (mg/dL), int32 trend,
float rate`. On the Galaxy Watch 4, `adb run-as tk.glucodata` can read these
(unusual for a release app — if a future build blocks it, fall back to Juggluco's
own in-app export). Two scripts turn that into one CSV:

```bash
export ANDROID_SERIAL=10.0.0.48:<port>   # only if several devices are attached
./tools/pull-juggluco.sh                 # copies raw data → ~/juggluco-data
python3 tools/export-glucose.py          # merges all sensors → ~/glucose-history.csv
```

`export-glucose.py` dedupes overlapping sensors by timestamp and emits columns
`timestamp_local, epoch_s, glucose_mmol, glucose_mgdl, trend, rate_mgdl_min,
sensor`. The parse is validated against this app's own insulin-log snapshots
(mean error ~0.14 mmol).

## Dashboard

`tools/build-dashboard.py` turns the two CSVs into a **single self-contained
HTML file** — no server, no database, no CDN (data and charts are inlined, so it
works fully offline). It computes the standard clinical summaries a diabetes
clinic expects (Time-in-Range, an AGP percentile profile, GMI, CV) plus a recent
14-day trace with insulin doses overlaid, and a per-day table.

```bash
# refresh the CSVs first (see the two sections above), then:
python3 tools/build-dashboard.py
# → ~/Library/Mobile Documents/com~apple~CloudDocs/Health/glucose-dashboard.html
```

The **Insulin → glucose response** section is the analytical core: it lines every
dose up at the moment of injection (t=0) and plots the median glucose path over
the next 4 hours (with the 25–75% spread), filterable by dose type, the glucose
you *started* at, and time of day, in absolute or change-from-dose mode. Splitting
by starting glucose separates the two regimes — doses started high trace the real
correction response (how far/fast insulin brings you down), while doses started in
range trace meal boluses (glucose rises as food outpaces the dose). It is
exploratory, not dosing advice; the insulin log doesn't tag meal vs correction, so
starting-glucose is the proxy.

By default it writes into **iCloud Drive**, so the same file opens on macOS
(double-click) and iOS (Files app → iCloud Drive → Health → tap it). The data
never leaves your Apple account — nothing is hosted. Override paths with
`--glucose`, `--insulin`, `--out`. The page is theme-aware (light/dark) with a
manual toggle, and every chart has hover/tap tooltips.

Regenerate whenever you want fresh numbers (e.g. before a doctor's appointment);
it's a snapshot, keyed off the glucose CSV's modification date for the "generated"
stamp. The generated HTML embeds personal health data and is intentionally **not**
committed — only the generator script lives here.

## Troubleshooting

**Watch face shows `--` forever after Juggluco install.** Samsung One UI's
Freecess controller freezes background apps. Open **Settings → Apps →
Juggluco → Battery** on the watch and set it to *Unrestricted* (wording
varies; also worth removing Juggluco from any "sleeping apps" list).

**`BgReceiver received action=… no recognised glucose key`.** A new Juggluco
build introduced new extras keys. Read the `keys=...` list from the log and
extend `JugglucoBroadcastReceiver.onReceive` accordingly.

**`BgHttp fetch failed: CLEARTEXT communication to 127.0.0.1 not permitted`.**
Network security config got reverted. Confirm
`res/xml/network_security_config.xml` exists and is referenced from
`AndroidManifest.xml` via `android:networkSecurityConfig`.

**`BgHttp fetch failed: Failed to connect to /127.0.0.1:17580`.** The Wear
build of Juggluco doesn't expose an HTTP server by default. This is expected
on a Galaxy Watch 4 — broadcasts are the working path. Ignore the warnings.

**Watch face rejected at install time** (`WatchFace ... do not have a valid
editing activity`). Make sure `WatchFaceConfigActivity` is still declared in
the manifest with the `androidx.wear.watchface.editor.action.WATCH_FACE_EDITOR`
intent filter.

**`adb push` fails with "secure_mkdirs failed"** when pushing to phone
storage. Phone USB mode reverted to "Charging only" — pull down notifications
on the phone, tap the USB notification, switch back to "Transferring files".

**Wear Installer 2 reports a non-Wear APK.** False alarm if the manifest
declares `uses-feature android:name="android.hardware.type.watch"` (it does).
Confirm with `aapt dump badging app-debug.apk | grep watch`.

## Architecture notes

- The `GlucoseRepository` singleton is intentionally simple — one StateFlow,
  no caching, no persistence. Watch face restarts cleanly; the receiver
  refills the StateFlow on the next Juggluco broadcast.
- `Renderer.CanvasRenderer2` was chosen over the XML-based Watch Face Format
  because the watch face needs to read live glucose state from in-process
  Kotlin code. Watch Face Format is data-binding-only and can't pull from a
  custom data source without a complication.
- The debug build keeps `applicationIdSuffix = ".debug"` so it can coexist
  with any future signed release and so `run-as` works for the CSV export.
- `fallbackToDestructiveMigration()` is used on Room — fine for personal use
  since CSV exports are the source of truth, not the on-watch DB.
- The mock provider is gated by `Build.HARDWARE in {goldfish, ranchu}` rather
  than a `BuildConfig` flag so the same debug APK works correctly on both
  emulator (mock) and real watch (no mock).
- Battery is read via `BatteryManager.BATTERY_PROPERTY_CAPACITY` on every
  render tick rather than a `BroadcastReceiver` on `ACTION_BATTERY_CHANGED`;
  it's a single binder call and the render rate is 1 Hz, so cost is trivial
  and we avoid the lifecycle complexity of keeping a receiver alive inside the
  watch-face service.
- Delete in the logger uses `DELETE WHERE id = (SELECT MAX(id) ...)` rather
  than tracking the just-inserted row, so the delete works correctly when the
  logger is opened after a previous accidental commit.

## Known limitations

- The HTTP fallback won't work against the current Wear OS build of Juggluco.
- Only two insulin types (`fast`, `slow`). A third (e.g. correction) would
  require swapping the two-button row for a segmented control or scroll-picker.
- No on-watch log viewer. By design — analysis happens on the desktop.
- Trend arrow uses the Nightscout direction strings sent by Juggluco; if a
  reading arrives without a direction, `?` is shown.
- 28 MB APK. Could be trimmed substantially with R8 minification and dropping
  unused Compose Material components if size becomes a concern.

## Licence

Personal project; no licence chosen.
