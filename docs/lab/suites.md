# Workloads and test suites

The Android app's **Workload** selector chooses the kind of run. A case is one invocation of that workload; a native suite contains multiple checks and may exercise several endpoint configurations. See [Run controls](controls.md) for settings, limits and examples.

## Workload selector

| App selection | What it runs | Cases with one repetition/seed per point |
|---|---|---:|
| Selected loopback case | Two modem engines exchanging verified application bytes through the selected channel; adaptive or fixed CPM policy | 1 |
| Quick loopback suite | Clean, AWGN and MPP paired-engine sessions | 3 |
| Full HF session matrix | Adaptive plus all six fixed CPM policies × ten channels × eight SNR points | 560 |
| Extreme HF session matrix | The same seven policies × four upstream severe ITU profiles × eight SNR points | 224 |
| Full CPM receiver campaign | One-way bursts across all six CPM modes and the public study's seven-channel SNR grid; normal receiver paired with supplied timing/CFO/header diagnostics | 558 |
| All 26 native suites | Every hardware-free C++ suite listed below, each in its own process | 26 |
| Selected native suite | One choice from the Native suite selector | 1 |
| Single receiver listening benchmark | Existing `data2g-bench-rx --listen`, processing generated noise | 1 |
| Single endpoint recording replay | Existing `data2g-replay --worker`, listening as LAB1 on an imported recording | 1 |
| Recorded burst benchmark | Existing `data2g-bench-rx`, reporting decoder-stage measurements for an imported burst | 1 |

Repetitions multiply these counts. For HF campaigns, the repetition value is the number of seeds at each grid point: 100 seeds in the CPM receiver campaign means 55,800 cases. Starting-case and case-limit controls select a subset. **Preview case count** shows the actual selection before starting.

## Channels and campaign grids

| Channel | Second-path delay | Gaussian Doppler spread (2 sigma) | Where used |
|---|---:|---:|---|
| `clean` | None | None; no noise | Selected and quick loopbacks |
| `awgn` | None | None | Selected, quick and full campaigns |
| `mpg` | 0.5 ms | 0.1 Hz | Selected, full HF and CPM campaigns |
| `mpp` | 2 ms | 1 Hz | Selected, quick, full HF and CPM campaigns |
| `mpd` | 4 ms | 2 Hz | Selected, full HF and CPM campaigns |
| `mps` | 2 ms | 0.15 Hz | Selected and full HF sessions; empirical preset |
| `flutter` | 0.5 ms | 10 Hz | Selected, full HF and CPM campaigns |
| `nvis-d` | 7 ms | 1 Hz | Selected, full HF and extreme sessions |
| `lowlat-d` | 6 ms | 10 Hz | Selected, full HF and extreme sessions |
| `hilat-m` | 3 ms | 10 Hz | Selected, full HF and extreme sessions |
| `hilat-d` | 7 ms | 30 Hz | Selected, full HF and extreme sessions |

The public CPM study grid retains its historical `nvis` and `hilat` names, which are aliases for `nvis-d` and `hilat-d`. Its seven channels are AWGN, MPG, MPP, MPD, flutter, NVIS and high latitude. The four named severe presets match upstream `hfchannel.ITU_PRESETS`; this is not simulator certification or the complete ITU catalog.

HF session matrices use SNRs −16, −12, −8, −4, 0, +4, +8 and +12 dB, referred to 2500 Hz, with a 4.5 Hz CFO. The CPM receiver campaign uses the public `cpm_floor_study.py:e2e_grid`: nine AWGN points and fourteen fading points per mode/channel. Native and NumPy random generators differ; seeds identify native paired trials rather than identical Python waveforms.

The fixed CPM choices are `fsk16r25-r1/3`, `fsk16r25-r1/2`, `fsk8r50-r1/3`, `fsk8r50-r1/2`, `fsk32r62-r1/3` and `fsk32r62-r1/2`. Adaptive sessions use the upstream gear shifter and can select other supported modem modes.

## The 26 native suites

These are the original C++ tests from `native/tests`, with their assertions preserved. The APK's **View suite coverage and exclusions** button shows the catalog generated from the actual build.

| Suite | Main coverage |
|---|---|
| [test_arq](../../native/tests/test_arq.cpp) | ARQ frames, mode metadata and policy behavior |
| [test_arq_link](../../native/tests/test_arq_link.cpp) | Paired protocol endpoints and loss/retry stress without the audio waveform |
| [test_arq_phy](../../native/tests/test_arq_phy.cpp) | Physical-layer burst production and reception |
| [test_audio](../../native/tests/test_audio.cpp) | Audio buffers, filters, threading and file/pipe behavior |
| [test_codes](../../native/tests/test_codes.cpp) | Coding interfaces and round trips |
| [test_constellation](../../native/tests/test_constellation.cpp) | Constellation operations |
| [test_cpm](../../native/tests/test_cpm.cpp) | CPM waveform and receiver operations |
| [test_cwid](../../native/tests/test_cwid.cpp) | CW identification |
| [test_engine](../../native/tests/test_engine.cpp) | Paired modem sessions, synchronous/worker operation, recording and deadline/backlog checks |
| [test_equalizer](../../native/tests/test_equalizer.cpp) | Channel estimation and equalization |
| [test_gfldpc](../../native/tests/test_gfldpc.cpp) | GF LDPC coding/decoding |
| [test_hand](../../native/tests/test_hand.cpp) | HAND burst round trips |
| [test_host](../../native/tests/test_host.cpp) | Host-command behavior |
| [test_ldpc](../../native/tests/test_ldpc.cpp) | LDPC coding/decoding |
| [test_modem](../../native/tests/test_modem.cpp) | Modem transmit/receive operations |
| [test_monitor](../../native/tests/test_monitor.cpp) | Promiscuous monitoring |
| [test_polar](../../native/tests/test_polar.cpp) | Polar coding/decoding |
| [test_pool](../../native/tests/test_pool.cpp) | Pool correctness and consistent results across thread counts, including eight threads |
| [test_primed](../../native/tests/test_primed.cpp) | Reception aided by expected slots/known bits and paired-station cases |
| [test_receiver](../../native/tests/test_receiver.cpp) | Receiver acquisition and streaming behavior |
| [test_rig](../../native/tests/test_rig.cpp) | Radio-control abstractions with test doubles |
| [test_rig_bridge](../../native/tests/test_rig_bridge.cpp) | Mock radio bridge/socket behavior |
| [test_rig_bridged](../../native/tests/test_rig_bridged.cpp) | Bridged radio-control behavior with mocks |
| [test_rig_cm108](../../native/tests/test_rig_cm108.cpp) | CM108 PTT behavior against mock files/devices |
| [test_tnc](../../native/tests/test_tnc.cpp) | TNC/KISS framing |
| [test_waveform](../../native/tests/test_waveform.cpp) | Waveform and DSP primitives |

The collection mixes single-stage, single-receiver and paired-endpoint work. Its CPU/memory traces should be interpreted by suite. For example, `test_pool` intentionally changes pool sizes, so its roughly seven-core peak does not imply a normal modem run ignored the four-thread setting.

## Excluded coverage

The APK does not embed Python, NumPy, SciPy or pytest. The Python reference suites, Python-versus-native parity suites, Python-only stress drivers and additional research arms remain outside the APK. The native tests are not a one-for-one replacement for every Python test.

The native `args`, `realtime`, `rig_hamlib`, `rx_plot`, `station_tx`, `tci` and `gui` suites are also excluded because this standalone app does not package their desktop Qt/station/Hamlib dependencies. Radio-interface tests in the included catalog use mocks, not a real radio.

The app does not qualify USB audio, CAT/PTT hardware integration, RF performance or live-audio deadlines. A weak-channel miss in a campaign is a measured outcome; an assertion failure in a native correctness suite is a different result.
