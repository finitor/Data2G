# Run controls

Start on **Run**, choose a **Workload**, review the settings below, and use **Preview case count** before **Run workload**. The [suite reference](suites.md) explains each workload and its endpoint/resource scope.

## Setup fields

| Control | Default / range | Effect |
|---|---|---|
| Workload | Selected loopback case | Chooses sessions, a campaign, native suites, listening, replay or burst benchmarking |
| Channel (selected case only) | Clean | Channel for a selected loopback; campaigns have their own grids |
| Mode (selected loopback case) | Adaptive | Upstream gear shifter, or one of the six fixed CPM policies; campaign modes are predefined |
| Native suite | First catalog entry | Suite used by Selected native suite; All 26 native suites uses the whole catalog |
| Wall-clock paced / Unpaced loopbacks | Wall-clock paced | Paces session simulation to its audio clock, or runs it as fast as possible; other workloads retain their original execution speed |
| SNR in 2500 Hz | 12 dB; −30 to +60 | Selected/quick loopback SNR; unused for clean and overridden by campaign grids |
| First seed | 1; nonnegative | Starting native simulation seed; repeated sessions/campaign trials increment it |
| Application bytes each direction | 64; 1–65,536 | Payload target in each direction for paired-engine sessions |
| Session horizon / replay or listening seconds | 180; 1–600 | Simulated session cutoff, replay input-duration limit or listening duration; does not set the runtime of original native suites |
| Use modem default | Checked | Resolves the core's current pool default and displays it; four threads on the Redmi 10C |
| Pool thread override | 1–32 when enabled | Uncheck Use modem default to enter an explicit size; one requests a one-thread pool |
| Seeds per HF grid point / repetitions | 1; 1–1,000 | Seeds at each campaign point, or repetitions of the selected workload/suite group |
| First case index | 0 | Zero-based position in the full generated plan |
| Case limit | 0 | Zero means all remaining cases; a positive number limits the selection after the starting index |
| Record CPU, memory and thermal timelines | Checked | Enables periodic app/child profiling and graphs; native result counters are still recorded when it is disabled |

Only applicable settings affect a workload. SNR, payload and channel selections do not change a native unit suite. Some original suites intentionally select their own pool sizes; FFT threads are also separate from the modem pool. Native child processes have a 900-second outer watchdog in addition to any original test watchdog.

Pacing applies to session simulation. The receiver diagnostics, native suites and existing replay/benchmark tools are not converted into paced sessions by this setting. Resource graphs use wall time; moving goodput uses simulated channel time.

## Setup actions

| Action | What it does |
|---|---|
| View suite coverage and exclusions | Opens the catalog of packaged and unavailable native suites |
| Import recording (.f16) or burst (.d2gb) | Copies an input into app storage and records its SHA-256 |
| Preview case count | Shows selected cases, full-plan size and resolved pool setting |
| Run workload | Starts a new saved run using the current configuration |
| Cancel run | Stops between native steps/slots and saves partial results; a current decode can take time to return |

Replay expects an 8 kHz mono little-endian float16 `audio_in.f16` recording in the existing recorder format. Burst benchmarking expects an existing `.d2gb` fixture. Import does not convert arbitrary WAV/MP3 recordings into these formats.

Keep the app visible during a run. Leaving it cancels the active case and saves progress. Resume retries that interrupted case rather than advancing past it.

## Navigation and saved reports

| Control | What it does |
|---|---|
| Run | Opens workload setup |
| Results & graphs | Opens the report viewer and resource timelines |
| Console | Shows current test/mode/channel/SNR/seed context and live native output |
| Open saved run | Opens a historical local run |
| Open JSON or campaign ZIP from Files | Imports a report for viewing |
| Resume this campaign | Uses the saved plan and next-case index; a changed native payload requires a new run |
| Browse all cases | Pages through the complete case index and opens individual results |
| Export report / complete campaign ZIP | Saves a campaign ZIP containing raw records, logs, resource segments and `report.html`; a standalone imported JSON report exports as JSON |

The dashboard shows only the latest three attempts. **Browse all cases** accesses the full archive. In a ZIP export, extract the files and open **report.html** for an offline summary, graphs and searchable case table; see [HTML reports](html-export.md).

## Common selections

| Goal | Configuration |
|---|---|
| Quick end-to-end smoke | Quick loopback suite; one repetition; first case 0; limit 0 → three cases |
| Run every native suite | All 26 native suites; one repetition; first case 0; limit 0 → 26 suites |
| Run one native suite | Selected native suite, then choose its name → one suite per repetition |
| Sample a large campaign | Choose the campaign, set seeds per point, then set a small positive case limit and preview the count |
| Run the full public CPM campaign | Full CPM receiver campaign; 100 seeds per point; first case 0; limit 0 → 55,800 cases |
| Compare one receiver across devices | Replay the same recording, or benchmark the same `.d2gb`, with matching pool settings |

A one-case run is expected for Selected loopback case, Selected native suite and the individual replay/benchmark workloads. To exercise the whole native catalog, choose **All 26 native suites**.
