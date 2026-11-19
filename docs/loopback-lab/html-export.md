# Offline HTML report in campaign exports

Every campaign ZIP includes **report.html**. Extract the ZIP and open this
file in a browser; no server, network access, chart CDN or external fonts
are required. Re-exporting an imported older campaign ZIP also adds the
report. The original JSON, timelines, journals, recordings and logs remain
in the archive.

The report includes run/device/build settings, outcome counts, a searchable
case table, all resource preview segments, and case details. Hover or touch
a graph to see values and the active case. For example, the final lab3
campaign's roughly 725% CPU peak identifies `test_pool`, which deliberately
tests eight threads despite the run's default pool setting of four.

Memory uses a single graph: Lab (estimate) and Available, both as shares
of total usable phone RAM. CPU retains the 100% = one-core convention.
Resource plots use wall time within each segment. Session goodput plots
use simulated channel time, with separate delivered and ACK progress rates.

All case summaries are embedded, with a 50-row paginated table. Detailed
previews for the latest three attempts are embedded too. To inspect another
case's goodput graphs or log excerpt, use **Load a case JSON** and choose its
file from the extracted archive. Raw JSON and full program-log links are
also provided. A case declaring a different native payload is rejected.

Export streams case summaries rather than accumulating every full result
in the Android app's memory. Resource graphs use the saved, bounded preview
snapshots; full older samples remain in the JSONL journals. HTML export does
not run the modem, change the recorded source identity or retrain weights.

## Local validation

The Android exporter check uses a frozen phone report as a fixture, plus
synthetic cases for pagination, multiple resource segments, script-like
strings, empty runs and upgrading older ZIPs. It verifies raw archive entries
are preserved. It needs ADB and the SDK/JDK described in the
[build instructions](../loopback-lab-build.md), but no APK installation:

```sh
python3 tools/check_android_html_export.py --serial SERIAL \
  --java-home /path/to/jdk17
```

Then check the offline HTML in a fresh local Chrome profile:

```sh
python3 tools/check_lab_html_browser.py \
  native/build-loopback/html-export-check/real.zip \
  native/build-loopback/html-export-check/fixture.zip
python3 tools/check_lab_html_browser.py \
  native/build-loopback/html-export-check/real.zip \
  native/build-loopback/html-export-check/fixture.zip \
  --mobile --output native/build-loopback/html-browser-mobile
```

`--chrome /path/to/chrome` overrides the default macOS Chrome path. Browser
checks exercise graph rendering, CPU case identification, search, pagination,
segment selection, local JSON loading, goodput, literal-string escaping and
layout. The narrow-screen check constrains content to 390 pixels because
macOS desktop Chrome enforces a wider minimum viewport. It is a browser
layout check, not an Android browser/device qualification.

The exporter was also run against the actual saved final 26-suite phone
campaign: all 26 summaries, all 650 preview samples and original raw files
were preserved. The generated report and synthetic fixtures passed desktop
and narrow-screen Chrome checks. No hosted CI or new modem performance
measurements were used for this export-only change.
