# Data2G Lab

For prerequisites, installation, local validation and updating compiled weights, see [build instructions](build.md).

Data2G Lab is an optional testing and profiling tool for the existing Data2G C++ core, with a desktop CLI and an Android frontend. It supports paired-engine loopback sessions, one-way receiver measurements, fixed-recording replay, original native correctness suites and HF channel campaigns. The paired-engine workload passes actual simulated audio and verifies application bytes. No radio, audio device, Python runtime or Qt is needed on the phone. Mock-radio native suites use localhost sockets. The separate APK application ID is `org.cleverdomain.data2g.lab`.

## Documentation

- [Workloads and test suites](suites.md): every workload, all 26 native suites, channel grids and excluded coverage.
- [Run controls](controls.md): every setup field and button, defaults, limits and common configurations.
- [Build and installation](build.md): local desktop/Android builds, tests and updating weights.
- [HTML reports](html-export.md): offline exported reports and exporter validation.
- [Validation records](validation/): source identities, completed checks and raw evidence.
- [Severe-channel retry study](severe-session-retries.md): opt-in comparison of existing session retry modes.
- [Controlled session losses](controlled-session-loss.md): deterministic loss targets, signal semantics and accounting.
- [Conditional retry study](conditional-retry-study.md): actual retry exposure and recovery tradeoffs after forced losses.

## Existing infrastructure and reuse

| Existing component | Role retained |
|---|---|
| `native/tests/test_engine.cpp` | Native two-engine loopback/worker tests; the basis for this runner |
| `native/apps/data2g_replay.cpp` | One-endpoint profiling on fixed recordings, with worker mode/DD budgets |
| `native/apps/data2g_bench_rx.cpp` | Decoder-stage, listener and shifter microbenchmarks |
| `scripts/cpu_profile/speedtest.py` | Two complete stacks through resamplers and channels, including final ACKs |
| `scripts/cpu_profile/run.sh` | Live two-host/PipeWire profiling on Linux |
| `scripts/phy_session.py`, `data2g/hfchannel.py` | Reference session studies and Gaussian-scatter model |

The new parts are the native scenario driver, resource measurements, structured results and Android packaging/UI. Production DSP, generated tables and host behavior are unchanged. The common build gains an opt-out for Android device backends, defaulting to enabled.

For hardware comparisons, generated sessions explore adaptive behavior; fixed recordings with `data2g-replay` compare identical receive workloads. Keep `data2g-bench-rx` for detailed stage measurements. Do not infer one modem's requirements from two modems plus a simulator.

## Loopback cases and channel model

Each case connects LAB1 and LAB2, writes seeded random bytes both ways, checks every received prefix, drains final acknowledgements, and disconnects. Success requires both sessions closed. Outcomes distinguish connection, delivery, ACK and disconnect timeouts, corruption, cancellation and success. A difficult channel timing out is a measurement, not necessarily a defect. The default is 64 bytes each way and a 180-second simulated horizon; bounds are 65536 bytes and 600 seconds. The quick suite is clean, AWGN and MPP at the selected SNR and seed. One seed is a smoke check, not reliability evidence.

| Profile | Path separation | Gaussian Doppler spread (2 sigma) |
|---|---:|---:|
| `clean` | None | None; no noise |
| `awgn` | None | None |
| `mpg` | 0.5 ms | 0.1 Hz |
| `mpp` | 2 ms | 1 Hz |
| `mpd` | 4 ms | 2 Hz |
| `mps` (empirical) | 2 ms | 0.15 Hz |
| `flutter` | 0.5 ms | 10 Hz |
| `nvis-d` | 7 ms | 1 Hz |
| `lowlat-d` | 6 ms | 10 Hz |
| `hilat-m` | 3 ms | 10 Hz |
| `hilat-d` | 7 ms | 30 Hz |

The severe profiles follow the four named upstream ITU presets; the simulator is not certified and does not represent the full ITU-R F.1487 catalog. `mpg/mpp/mpd` reuse reference presets; the four named severe profiles match upstream `hfchannel.ITU_PRESETS`. Legacy `nvis`/`hilat` names remain aliases for `nvis-d`/`hilat-d` in the public CPM study grid and CLI. Two independent equal-power Rayleigh paths evolve continuously, including silence. Fading is shared reciprocally; each receiver has independent noise. No oracle channel, timing or frequency information is given to either receiver.

Spectral shaping and expectation normalization follow the existing `hfchannel._gaussian_taps`. The specified SplitMix64/Box-Muller draws differ from NumPy defaults. `check_channel.py` supplies identical draws to the Python reference and compares taps, delayed burst audio, power scaling and frequency shift with floating-point tolerances. Native session RNG behavior remains C++ library dependent, as in the core.

Each burst is normalized to unit **active mean transmitted power** before fading, using the reference active-power definition. Fixed white noise corresponds to the selected SNR in 2500 Hz, including silence. Fades are never normalized away. This differs from `cpu_profile/speedtest.py`'s PEP-referenced SNR in 3000 Hz; results cannot be pooled without matched models and normalization.

Both engines take 100 ms blocks on one sample clock with a symmetric one-block transport delay. Complete bursts use the existing `tx_burst` hook for the reference FFT analytic-signal transform, avoiding blockwise Hilbert artifacts; delayed tails are retained. Operation uses synchronous engines and a sample clock. The CLI is unpaced by default; `--paced` waits for that clock to catch up with wall time. Android profiling defaults to paced. Decoder elapsed time does not alter protocol events or cause simulated audio drops. The production DD wall-time budget is retained and recorded, so sufficiently slow hardware can still produce different outcomes.

## Desktop

```sh
cmake -S native/lab -B native/build-lab -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build native/build-lab --target data2g-lab test_lab --parallel 6
ctest --test-dir native/build-lab --output-on-failure
python native/lab/check_channel.py native/build-lab/data2g-lab
native/build-lab/data2g-lab --channel mpp --snr 12 --seed 1 --threads 1 \
  --bytes 64 --horizon 180 --output native/build-lab/mpp.json
```

Only the parity script needs the normal NumPy/SciPy environment. Windows uses the generator's configuration-specific executable path. Resource adapters support Windows and POSIX; initial validation is macOS ARM64 and Android ARM64. Configure `DATA2G_LAB_REVISION` with a revision/worktree fingerprint for pinned results; the default `unknown` is not a pinned build.

`--paced` records late simulated block ends and maximum lateness. This helps identify when the workload cannot maintain its requested cadence; it does not measure live audio queue drops or worker reply deadlines.

JSON goes to stdout and optionally `--output FILE`; progress goes to stderr. Exit codes: 0 complete or burst measurement, 1 incomplete/cancelled, 2 configuration/runtime error. Run additional seeds/SNRs separately and retain failed trials too.

`--record-dir NEW_DIRECTORY` writes the **existing** Recorder format under `a/` and `b/`, refusing an existing directory. Reuse it directly:

```sh
cmake --build native/build-lab --target data2g-replay --parallel 6
native/build-lab/native/data2g-replay NEW_DIRECTORY/a --call LAB1 --threads 1
```

## Android

Requires an installed SDK platform 35, build-tools 35+, NDK, CMake/make, Python 3 and JDK 17. SDK tools package the APK directly; no Qt, Gradle, hosted CI are needed.

```sh
python3 tools/build_android_lab.py --sdk /path/to/Android/sdk --java-home /path/to/jdk
adb -s DEVICE_SERIAL install --no-incremental -r native/build-android-lab-arm64-v8a/data2g-lab.apk
```

The script only installs with explicit `--install DEVICE_SERIAL`. The APK uses the repository's existing public debug key and is debuggable for local result retrieval; it is not a release artifact.

Open **Data2G Android Lab** and choose a workload. Pool size defaults to **Use modem default**, displaying the core's actual default (4 on the 8-core Redmi). Uncheck it to override with 1–32. Both requested and effective sizes are recorded; original native suites may deliberately change their own pool size. FFT threading is separate.

The complete catalog is in [Workloads and test suites](suites.md). The [Run controls](controls.md) reference lists every setup field and action.

Campaigns expose 1–1000 seeds per point, first seed, starting case index and an optional case limit. Preview the count before starting a long run. Session horizon, payload and pacing remain configurable; HF grids use a 4.5 Hz CFO. CPM diagnostics and the original test/tools run at their own speed; a paced session is still synchronous simulation, not live audio qualification. The native CPM campaign ports the normal receiver and paired supplied timing/CFO/header arm on identical audio. Other Python research arms and pytest suites are not embedded. A failed reception is a measurement, not a unit-test failure. Seven Qt/station/Hamlib-dependent suites are listed as unavailable in the app's coverage dialog, rather than silently skipped.

Keep the app visible: leaving cancels between native steps/slots, and a current decode may take time to return. Rotation retains the activity. There is no background service or automatic radio startup.

**Console** shows the active workload, case number, selected mode, named channel, delay/Doppler spread, SNR and seed. Session output logs actual TX/RX modes as adaptation changes them; burst diagnostics report acquisition and decode phases. Original native test/tool output is streamed with line buffering. The console retains 150 lines and batches UI refreshes; complete native program logs are saved per case (8 MiB cap, truncation reported).

**Results & graphs** restores the last report and opens historical runs, individual cases, older JSON reports, or an exported campaign ZIP through Files. The dashboard retains only three recent attempts. **Browse all cases** pages through the full index. Schema 3 stores a `campaign-TIMESTAMP/` directory containing `manifest.json`, append-only `index.jsonl`, individual case/attempt JSON files, original program logs, retained input recordings, and resource segments. Export saves the complete directory as ZIP without loading all trials into memory. Each ZIP includes a self-contained **report.html** with graphs and all case summaries, including when an older imported ZIP is re-exported. Extract the ZIP and open the HTML in a browser. See [offline HTML reports](html-export.md) for details and local validation. Imported ZIPs are read without extraction.

**Resume this campaign** recovers the index, preserves prior attempts and retries a cancelled case. A new profiling segment starts at wall time zero; exports retain previous segments. The viewer shows the most recent segment. Changing native source/weights requires a new run: the source identity is HEAD plus a fingerprint covering the native core (including generated weights), tests/tools and harness. New trained weights can be built into a replacement APK without changing the harness. Existing results stay tied to the payload that produced them. Harness validation with current weights is not qualification of the future retrained model.

For an ADB smoke check (always select a specific device):

```sh
adb -s DEVICE_SERIAL shell am start -n org.cleverdomain.data2g.lab/.MainActivity \
  --ez auto true --es workload quick --es snr 12 --ei bytes 64 --ei horizon 180 \
  --ei threads 0 --ez paced true --ez profiling true --ei repeats 1
```

Other `workload` values: `custom`, `hf_sessions`, `hf_extreme`, `cpm_floor`, `native_all`, `native_one`, `listen`, `replay`, `burst`. `--ei first N` and `--ei limit N` select a subset. `native_one` accepts `--es native_suite test_arq_link`. Recordings are imported in the UI. `--ez auto true --ez resume true` resumes the last local campaign. Launch a fresh activity for automation only when there is no user run to interrupt. On MIUI devices that block USB installs, push the APK to Downloads and install/update it through Files.

The desktop CLI exposes the same case plan as JSONL:

```sh
native/build-lab/data2g-lab --list-campaign cpm_floor --trials 100 --seed 50000
native/build-lab/data2g-lab --cpm-burst --fixed-mode fsk8r50-r1/3 \
  --channel hilat --snr -4 --seed 50000 --threads 0
```

To build/run the original hardware-free native suites locally:

```sh
cmake -S native/lab -B native/build-lab -DDATA2G_LAB_NATIVE_SUITES=ON
cmake --build native/build-lab --parallel 6
ctest --test-dir native/build-lab --output-on-failure
python native/lab/check_campaign.py native/build-lab/data2g-lab
```

Only the reference comparison scripts need NumPy/SciPy. All builds and validation are local; GitHub-hosted CI remains disabled.

## Timeline profiling and graphs

The Android app samples process CPU time and current RSS approximately once every 250 ms on a separate observer thread. CPU percentage is the change in process CPU milliseconds divided by elapsed monotonic wall time: **100% means one occupied CPU core** and values may exceed 100%. All app threads and the active native child count, including workers, UI and the observer. Child CPU uses same-UID `/proc` counters, with final native CPU/RSS accounting where available. This is not system-wide CPU utilization or a single-endpoint modem measurement.

PSS/private-dirty memory is sampled about once per second because it is more expensive. Reused observations retain their age. The thermal charts show **battery temperature** and Android's 0–6 **thermal severity**, neither of which is a CPU temperature sensor. Battery readings may update slowly. Unavailable readings are null and create gaps; they are not replaced by zero.

The single memory graph shows **Lab (estimate)** and **Available** as percentages of the phone's total usable RAM. Its caption reports the latest shares, usable/available GB, and Android's low-memory threshold. PSS is used for the lab when available; RSS is an explicitly approximate fallback. Available memory includes reclaimable cache and is not a promise that one allocation of that size will succeed. Historical reports can show lab share when total RAM was recorded, but no historical availability is invented. Raw RSS/PSS and byte counters remain in exports. Displayed GB/MB in this caption are decimal; older detailed MiB values use 1,048,576 bytes per MiB.

Graphs use actual elapsed seconds, with scenario boundaries and tappable sample inspection. Memory, CPU, battery temperature and thermal state use separate labeled plots. Sampling wall cost, actual timestamps, raw counters and cached-reading ages are exported. The observer keeps at most 12000 samples and 2000 markers for the viewer and explicitly reports truncation. An append-only resource JSONL journal retains all samples and markers on disk. Live graph updates are limited to about once per second. Profiling can be disabled for a comparison without the periodic sampler; drawing and sampling otherwise add to resource use.

Choose **Wall-clock paced profiling** for representative duty cycle and **Unpaced loopbacks** for maximum-speed experiments. Repetitions (1–1000) repeat each selected case, incrementing its seed. This supports longer observation, but a short graph alone cannot qualify sustained heat or thermal throttling. Cancellation saves partial results and samples.

Sessions show a continuous **30-second trailing goodput** indicator and per-direction delivered/acknowledged graphs. Counters count unique verified application bytes; retransmissions do not increase goodput. The clock is simulated channel time, so unpaced processing speed does not inflate the radio rate. Warmup uses elapsed channel time below 30 seconds; stalls decay to zero. Whole-session delivery average counts both directions and includes setup/teardown. Tests, replay and single bursts do not report application goodput. Resource graphs use monotonic wall time instead.

API semantics: [process CPU time](https://developer.android.com/reference/android/os/Process#getElapsedCpuTime()), [process memory](https://developer.android.com/reference/android/os/Debug#getMemoryInfo(android.os.Debug.MemoryInfo)), [thermal severity](https://developer.android.com/reference/android/os/PowerManager#getCurrentThermalStatus()), and [battery temperature](https://developer.android.com/reference/android/os/BatteryManager#EXTRA_TEMPERATURE).

## Metrics and limits

Records include source identity, compiler, pool/DD configuration, seeds, model, byte/ACK/disconnect outcomes and events. Channel wall time, each engine's accumulated wall time and p95/max step time, total wall/process CPU time and simulated elapsed time are separate. Engine steps include TX, acquisition, sessions and decoding; they are not isolated decoder timings.

This does not qualify real-time deadlines, USB audio, CAT/PTT, RF behavior, clock drift, interference or live-audio interruptions. A synchronous step exceeding 100 ms alone does not prove a worker-mode deadline failure. Thermal status is sampled, not a sustained throttling qualification.

Future work: paced worker/backlog qualification and richer thermal-soak summaries. Keep fixed replay separate from adaptive session outcomes and processing measurements separate from goodput.

## Source and review

This optional diagnostic tool is based on upstream Data2G v0.5.2. Start at [this guide](README.md), then [build locally](build.md). No performance superiority claim or request for upstream adoption is implied. Historical evidence is retained in [validation records](validation/); its source identities and limitations belong to those original runs.
