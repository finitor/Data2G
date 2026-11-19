# Viewer and timeline validation — 18 November 2026

APK build 2 (`0.5.1-lab2`), installed on the Redmi 10C through Files. Source identity: `72ca439a064a7414ab8c8b4d0d045fe217be91be+da0f08ccd785b203`. APK SHA-256: `0735fff1b16aae0595ed6e77d56cc8f781e87d9a39d5e2cefc1fba67eb5b9552`.

- Local macOS ARM64 native tests passed, including minimum wall-clock pacing and cancellation during paced waiting.
- The Android quick suite completed clean, AWGN and MPP exchanges, with exact 64-byte messages each way, final acknowledgements and disconnects.
- All three cases recorded `wall_clock_paced`; each case's wall duration was at least its simulated duration.
- The profiling record contains 151 samples spanning 39.31 actual seconds, and six ordered case boundary markers.
- Timestamps and process CPU counters are monotonic. Every CPU percentage was checked against the exported counter delta and actual elapsed time (100% = one occupied CPU core).
- RSS/PSS readings, cached PSS ages, battery temperature and Android thermal severity were validated. Battery readings ranged from 25.9 to 26.0 °C; observed thermal severity was 0.
- The on-device results viewer, CPU graph and memory graph were inspected visually. Thermal chart inputs were validated from the exported samples; automated touch injection is disabled by the phone, so lower-graph interaction was not automated.
- Schema-1 report compatibility is implemented, including an explanation for missing timelines. New schema-2 reports include samples and markers. Document-picker import/export interaction was not automated.
- APK compilation/signature, native include/layering checks and whitespace checks passed. No GitHub-hosted CI ran.

Raw evidence: [redmi-10c-paced-timeline-2026-11-18.json](redmi-10c-paced-timeline-2026-11-18.json).

The observer spent 1931.9 ms of accumulated wall time reading counters (including blocking/waiting). This is not a measurement of observer CPU overhead. Process resource totals include both modems, channel simulation, UI and observer. Sampled memory can miss short peaks. A short run with thermal severity 0 does not qualify sustained thermal behavior or live audio deadlines.

The APK still runs the two-endpoint workload. Single-endpoint replay, receiver microbenchmarks and Python protocol stress drivers are not yet integrated as selectable app workloads.
