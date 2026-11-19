# Data2G Lab layout and v0.5.2 validation

The harness is based on upstream v0.5.2 (`dd7af8df57373aa9f652a0af03481ab71f1608b9`). Local `master` remains identical to that upstream revision. The retrained predictor and CPM receiver changes are upstream code; this tool does not change the modem's DSP, weights or over-air protocol relative to that baseline.

The portable implementation is in `native/lab`, the Android frontend is in `native/android-lab`, and the build script is `tools/build_android_lab.py`. The CLI is `data2g-lab`. Current documentation is under `docs/lab`; older evidence remains under `docs/lab/validation` with its original recorded payload identities.

## Local macOS ARM64

The renamed desktop project built from a fresh `native/build-lab` directory with AppleClang 17 and RelWithDebInfo. All 27 CTests passed in a final serial run (52.86 seconds), including the original 26 native suites and the Lab test.

An initial run overlapped the Android compiler and failed the original engine worker timing check. It also hit the sandbox's localhost bind restriction in two mock bridge checks. The final run used an idle host and allowed localhost mock sockets; all original assertions passed without changing upstream tests.

The Lab test's old eight-second cutoff no longer fell between delivery and the final ACK for the updated model. The test now uses a clean reference exchange's observed delivery/ACK interval and cuts a second exchange inside that interval. It still requires delivered bytes without claiming their final acknowledgement.

Channel checks passed against the existing Python reference for all four upstream severe ITU profiles, the four ordinary/empirical presets, flutter, and the legacy NVIS/high-latitude aliases. The full HF session matrix has 560 points per seed; the severe matrix has 224. The public CPM floor grid remains 558 points per seed and matches the original study's `e2e_grid` function.

## Android and reports

The Android ARM64 project built from a fresh `native/build-android-lab-arm64-v8a` directory with NDK 28.2.13676358 and JDK 17. The APK includes the original native suites, replay/listening/burst tools, offline HTML exporter and license notices. APK signing verification is part of the build script.

The HTML exporter was exercised with Android's actual Java runtime against the saved 26-suite phone campaign and synthetic edge cases. All raw entries survived ZIP re-export; older archives gained an HTML report. Desktop and 390-pixel-width Chrome checks passed for rendering, case identification at the CPU peak, pagination, search, segment selection, JSON loading, goodput and literal-string escaping.

The frozen phone evidence in this folder describes the earlier installed payloads. It is not a performance measurement of the new v0.5.2 weights. The current Android rebuild has not yet been qualified through a fresh installed-phone campaign. Windows, Linux and Android x86_64 builds were not run. No hosted CI or training was used.
