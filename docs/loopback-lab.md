# Native loopback lab prototype

A reusable native runner with a desktop CLI and a thin Android APK for
checking the modem on modest hardware. It runs two unmodified C++ engines
through actual simulated audio and checks application bytes. No radio,
audio device, network service, Python runtime or Qt is needed on the phone.
The separate APK application ID is `org.cleverdomain.data2g.lab`.

## Existing infrastructure and reuse

| Existing component | Role retained |
|---|---|
| `native/tests/test_engine.cpp` | Native two-engine loopback/worker tests; the basis for this runner |
| `native/apps/data2g_replay.cpp` | One-endpoint profiling on fixed recordings, with worker mode/DD budgets |
| `native/apps/data2g_bench_rx.cpp` | Decoder-stage, listener and shifter microbenchmarks |
| `scripts/cpu_profile/speedtest.py` | Two complete stacks through resamplers and channels, including final ACKs |
| `scripts/cpu_profile/run.sh` | Live two-host/PipeWire profiling on Linux |
| `scripts/phy_session.py`, `data2g/hfchannel.py` | Reference session studies and Gaussian-scatter model |

The new parts are the native scenario driver, resource measurements,
structured results and Android packaging/UI. Production DSP, generated
tables and host behavior are unchanged. The common build gains an opt-out
for Android device backends, defaulting to enabled.

For hardware comparisons, generated sessions explore adaptive behavior;
fixed recordings with `data2g-replay` compare identical receive workloads.
Keep `data2g-bench-rx` for detailed stage measurements. Do not infer one
modem's requirements from two modems plus a simulator.

## Cases and model

Each case connects LAB1 and LAB2, writes seeded random bytes both ways,
checks every received prefix, drains final acknowledgements, and disconnects.
Success requires both sessions closed. Outcomes distinguish connection,
delivery, ACK and disconnect timeouts, corruption, cancellation and success.
A difficult channel timing out is a measurement, not necessarily a defect.
The default is 64 bytes each way and a 180-second simulated horizon; bounds
are 65536 bytes and 600 seconds. The quick suite is clean, AWGN and MPP at
the selected SNR and seed. One seed is a smoke check, not reliability evidence.

| Profile | Path separation | Gaussian Doppler spread (2 sigma) |
|---|---:|---:|
| `clean` | None | None; no noise |
| `awgn` | None | None |
| `mpg` | 0.5 ms | 0.1 Hz |
| `mpp` | 2 ms | 1 Hz |
| `mpd` | 4 ms | 2 Hz |
| `nvis` | 7 ms | 1 Hz |
| `hilat` | 7 ms | 30 Hz |

These are selected Gaussian-scatter presets, not the full ITU-R F.1487
catalog or a certified simulator. `mpg/mpp/mpd` reuse reference presets;
`nvis/hilat` explicitly define severe cases. Two independent equal-power
Rayleigh paths evolve continuously, including silence. Fading is shared
reciprocally; each receiver has independent noise. No oracle channel,
timing or frequency information is given to either receiver.

Spectral shaping and expectation normalization follow the existing
`hfchannel._gaussian_taps`. The specified SplitMix64/Box-Muller draws differ
from NumPy defaults. `check_channel.py` supplies identical draws to the
Python reference and compares taps, delayed burst audio, power scaling
and frequency shift with floating-point tolerances. Native session RNG
behavior remains C++ library dependent, as in the core.

Each burst is normalized to unit **active mean transmitted power** before
fading, using the reference active-power definition. Fixed white noise
corresponds to the selected SNR in 2500 Hz, including silence. Fades are
never normalized away. This differs from `cpu_profile/speedtest.py`'s
PEP-referenced SNR in 3000 Hz; results cannot be pooled without matched
models and normalization.

Both engines take 100 ms blocks on one sample clock with a symmetric
one-block transport delay. Complete bursts use the existing `tx_burst`
hook for the reference FFT analytic-signal transform, avoiding blockwise
Hilbert artifacts; delayed tails are retained. Operation is synchronous
and virtual-time: decoder elapsed time does not delay protocol events.
The production DD wall-time budget is retained and recorded, so sufficiently
slow hardware can still produce different outcomes.

## Desktop

```sh
cmake -S native/loopback -B native/build-loopback -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build native/build-loopback --target data2g-loopback test_loopback --parallel 6
ctest --test-dir native/build-loopback --output-on-failure
python native/loopback/check_channel.py native/build-loopback/data2g-loopback
native/build-loopback/data2g-loopback --channel mpp --snr 12 --seed 1 --threads 1 \
  --bytes 64 --horizon 180 --output native/build-loopback/mpp.json
```

Only the parity script needs the normal NumPy/SciPy environment. Windows
uses the generator's configuration-specific executable path. Resource
adapters support Windows and POSIX; initial validation is macOS ARM64 and
Android ARM64. Configure `DATA2G_LAB_REVISION` with a revision/worktree
fingerprint for pinned results; the default `unknown` is not a pinned build.

JSON goes to stdout and optionally `--output FILE`; progress goes to stderr.
Exit codes: 0 complete, 1 incomplete/cancelled, 2 configuration/runtime error.
Run additional seeds/SNRs separately and retain failed trials too.

`--record-dir NEW_DIRECTORY` writes the **existing** Recorder format under
`a/` and `b/`, refusing an existing directory. Reuse it directly:

```sh
cmake --build native/build-loopback --target data2g-replay --parallel 6
native/build-loopback/native/data2g-replay NEW_DIRECTORY/a --call LAB1 --threads 1
```

## Android

Requires an installed SDK platform 35, build-tools 35+, NDK, CMake/make,
Python 3 and JDK 17. SDK tools package the APK directly; no Qt, Gradle,
dependency downloads or hosted CI are needed.

```sh
python3 tools/build_android_loopback.py --sdk /path/to/Android/sdk --java-home /path/to/jdk
adb -s DEVICE_SERIAL install --no-incremental -r native/build-android-loopback-arm64-v8a/data2g-lab.apk
```

The script only installs with explicit `--install DEVICE_SERIAL`. The APK
uses the repository's existing public debug key and is debuggable for local
result retrieval; it is not a release artifact.

Open **Data2G Lab**, choose the profile, SNR, seed, bytes, horizon and pool
size, then Run. Keep it visible: leaving cancels between engine steps and
may take an in-progress decode to finish. Rotation retains the activity.
There is no background service or automatic radio startup.

Each completed trial checkpoints historical `run-TIMESTAMP.json` and
`latest.json` in the external files directory. **Export JSON results** uses
Android's document picker. Device RAM, app PSS/private-dirty memory, Android
version and thermal status accompany native trial records. Peak RSS is a
process-lifetime high-water mark, not fresh per-trial allocation.

For an ADB smoke check (use `--ez suite true` for the quick suite):

```sh
adb -s DEVICE_SERIAL shell am start -S -n org.cleverdomain.data2g.lab/.MainActivity \
  --ez auto true --es channel clean --es snr 12 --ei bytes 64 --ei horizon 180 --ei threads 1
adb -s DEVICE_SERIAL shell run-as org.cleverdomain.data2g.lab \
  cat /sdcard/Android/data/org.cleverdomain.data2g.lab/files/latest.json
```

## Metrics and limits

Records include source identity, compiler, pool/DD configuration, seeds,
model, byte/ACK/disconnect outcomes and events. Channel wall time, each
engine's accumulated wall time and p95/max step time, total wall/process
CPU time and simulated elapsed time are separate. Engine steps include TX,
acquisition, sessions and decoding; they are not isolated decoder timings.

This does not qualify real-time deadlines, USB audio, CAT/PTT, RF behavior,
clock drift, interference or live-audio interruptions. A synchronous step
exceeding 100 ms alone does not prove a worker-mode deadline failure.
Thermal status is sampled, not a sustained throttling qualification.

Next: expose existing replay/burst benchmarks as selectable workloads,
add versioned multi-case plans and repeat/thermal-soak reports, then paced
worker/backlog measurements. Keep fixed replay separate from adaptive
session outcomes and processing measurements separate from goodput.
