# Initial local validation — 18 November 2026

Base: upstream `8bf21625402f9865a637ee65b90f391cd848ef45`. No private experimental history was imported. GitHub-hosted CI was not used.

Local desktop: macOS ARM64, AppleClang 17, RelWithDebInfo, one modem pool thread. Android: Redmi 10C (220333QAG), Android 13, ARM64, NDK 28.2.13676358 / Clang 19.0.1, RelWithDebInfo, one pool thread.

Checks completed:

- Native end-to-end tests: clean and AWGN connect, exact bytes both ways, final ACK drain and disconnect; timeout and cancellation; delivery before the final ACK is not counted as acknowledged completion; noise mean/variance and a fixed PRNG vector.
- Native channel parity: all five fading profiles match the existing Python reference for continuous taps and complete burst rendering, including delayed tails, mean-power scaling and CFO.
- Existing `data2g-replay` successfully consumes a recording emitted by the new runner.
- Include, layering and whitespace checks pass.
- Android APK built and signature verified locally. Installed manually through Files because MIUI refused USB installation. Final APK quick suite passed on the actual phone.

Raw Android records: [redmi-10c-smoke-2026-11-18.json](redmi-10c-smoke-2026-11-18.json).

| Case | Outcome | Verified bytes A / B | Simulated seconds | Wall seconds | Process lifetime peak RSS |
|---|---|---:|---:|---:|---:|
| clean | complete | 64 / 64 | 12.2 | 1.856 | 164.1 MiB |
| awgn | complete | 64 / 64 | 14 | 1.761 | 164.1 MiB |
| mpp | complete | 64 / 64 | 12.8 | 1.757 | 165.8 MiB |

APK SHA-256: `faf5cf8cf21c0535530bfec3b06a44e8dbbd4458b637823f77013420fe9ec024`.

Source identity recorded by every phone trial: `8bf21625402f9865a637ee65b90f391cd848ef45+6aa2cc721ee83890`.

These are three short smoke cases at seed 1 and SNR 12 dB (unused for clean), not a sustained thermal, bulk-transfer, deadline or reliability qualification. Total CPU/RAM include two engines, the simulator and the Android app. Engine-step maxima are not isolated decode times. Other operating systems remain unqualified.

A separate macOS severe-channel smoke (7 ms / 30 Hz, +12 dB, seed 1, 60 simulated seconds) produced a connection timeout, retained as an incomplete outcome. It does not establish a sensitivity threshold or diagnose an upstream defect.
