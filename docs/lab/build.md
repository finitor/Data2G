# Building Data2G Android Lab locally

The app runs the fork's existing native modem (current baseline: upstream v0.5.2). Its package ID is `org.cleverdomain.data2g.lab`; it installs separately from the production TNC. See [the user guide](README.md) for workloads, graphs, report archives, coverage and measurement limits. Builds and tests stay local. Do not enable or dispatch GitHub-hosted CI.

## Android APK

Install these tools first (the build script does not install them):

- CMake 3.24+, a C++20-capable Android NDK, and Make.
- Android SDK platform 35, build-tools 35+ and platform-tools (ADB).
- JDK 17 and Python 3. No Android Python runtime, Qt or Gradle is required.

Validated toolchain: macOS ARM64, NDK `28.2.13676358`, JDK 17, ARM64 Android 13 phone. The APK requires Android 10/API 29 or later. ARM64 is the default; `--abi x86_64` is available but is not device-qualified by these results.

From the Data2G checkout:

```sh
python3 tools/build_android_lab.py \
  --sdk "$HOME/Library/Android/sdk" \
  --java-home /opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home
```

Adjust SDK/JDK locations for your machine; `cmake` and `make` must be on PATH. The script selects the newest installed NDK/build-tools; pin the NDK with `--ndk /path/to/ndk/28.2.13676358`. Use `--jobs 4` to reduce build load.

Output: `native/build-android-lab-arm64-v8a/data2g-lab.apk`. The script compiles the modem and harness, compiles Java, packages 26 native suites plus replay/benchmark tools, aligns and signs the APK, and verifies the signature. It uses the repository's public debug key. Unstripped native binaries remain in the build directory; only APK copies are stripped. This is a debuggable local diagnostics build, not a store release.

No device action occurs unless `--install SERIAL` is supplied. Always choose a specific device, especially if multiple phones are connected:

```sh
adb devices -l
adb -s SERIAL install -r native/build-android-lab-arm64-v8a/data2g-lab.apk
```

Some MIUI phones reject ADB installation. The alternative is:

```sh
adb -s SERIAL push native/build-android-lab-arm64-v8a/data2g-lab.apk \
  /sdcard/Download/data2g-lab.apk
```

On the phone, open Downloads → `data2g-lab.apk` and choose Install/Update. Launch **Data2G Android Lab**. Keep it visible during runs; leaving cancels the active case. Use **Resume this campaign** to retry an interrupted case.

## Desktop correctness checks and reference comparisons

The portable CLI uses the same native channel, campaign plans, byte/ACK accounting and modem core as Android. It does not need Qt or audio hardware.

```sh
cmake -S native/lab -B native/build-lab \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DDATA2G_LAB_NATIVE_SUITES=ON
cmake --build native/build-lab --parallel 6
ctest --test-dir native/build-lab --output-on-failure --parallel 2
python3 tools/check_includes.py
python3 tools/check_layering.py
git diff --check
```

There are 28 CTests: two harness tests plus 26 existing native suites. Mock radio bridge checks bind localhost sockets; a restrictive sandbox can deny that operation. No physical radio is used. Configure without `DATA2G_LAB_NATIVE_SUITES=ON` to build only the harness tests.

With NumPy/SciPy installed in a local Python environment:

```sh
python native/lab/check_channel.py native/build-lab/data2g-lab
python native/lab/check_campaign.py native/build-lab/data2g-lab
```

The first compares fading taps/rendered samples to the existing reference. The second checks every CPM grid point against the public study's actual `e2e_grid` function without running that study or training anything.

## Phone smoke checks

Use a fresh activity only after the previous run has finished; `-S` stops any active app run. For a paced quick suite with the default pool:

```sh
adb -s SERIAL shell am start -S -n org.cleverdomain.data2g.lab/.MainActivity \
  --ez auto true --es workload quick --ei threads 0 --ei horizon 180 \
  --ez paced true --ez profiling true
```

Use `--es workload native_all` for all packaged native suites. For a short extreme campaign, select the workload and a small case limit in the app; preview the count first. A complete 55,800-case CPM campaign is deliberately not an automatic smoke test. Confirm case outcomes, console context, saved reports, and graph availability. Receiver failures at weak SNR are measured outcomes, distinct from failures in the native correctness suites.

**Export report / complete campaign ZIP** saves every case attempt, native program log, retained input recording and resource segment through Android Files. The app can reopen ZIPs and old JSON reports. If collecting via ADB, use the shell's external-storage access rather than `run-as` on this Redmi:

```sh
adb -s SERIAL shell cat /sdcard/Android/data/org.cleverdomain.data2g.lab/files/latest.json
adb -s SERIAL pull /sdcard/Android/data/org.cleverdomain.data2g.lab/files/campaign-TIMESTAMP
```

For offline HTML export validation without an APK install, see [the HTML report checks](html-export.md#local-validation).

## Replacing the native weights later

Update deliberately selected upstream source/generated model files in this fork, preserving upstream generation instructions and licenses. Do not edit generated weights by hand or copy private experimental history into this repository. Re-run relevant local correctness checks, then use the same APK build command and update the installed app. There is no separately downloaded weight file in this prototype: weights are compiled into the native core.

Every result records HEAD plus a fingerprint covering the native core, including generated weights, native tests/tools and harness sources. Keep the source revision, APK and raw reports together. A payload change prevents resuming an old campaign; begin a new run for the new weights so measurements from different models are not silently mixed. Current-weight harness smoke checks do not qualify reception reliability with future weights.
