# Campaign/console build validation — 18 November 2026

This work resumes local harness implementation/validation with existing
weights, as requested in this chat. It does not resume model training or
private modem implementation studies. No GitHub-hosted CI was used.

## Local correctness and packaging

- macOS ARM64 / AppleClang 17: all 27 CTests passed (26 original hardware-free
  suites plus the harness). The mock bridge tests require localhost bind
  permission; an initial sandbox denial was resolved by running locally with
  that permission. Final complete run: 31.35 seconds, no failed tests.
- Goodput warmup, independent delivery/ACK counters, expiry during stalls,
  clean/AWGN sessions, partial ACK, cancellation and pacing checks passed.
- CPM normal and supplied-information arms recover the clean test burst.
- Native Gaussian-scatter taps and rendered audio match the existing Python
  reference for MPG, MPP, MPD, empirical MPS, flutter, NVIS and high latitude.
- Campaign enumeration matches the public study's actual `e2e_grid` for all
  six CPM modes, all seven channels and paired seeds. HF session plans contain
  448 full / 112 extreme points per seed.
- Include, layering, whitespace checks and Java compilation passed.
- Android ARM64 APK built and signature verified locally with NDK
  28.2.13676358 / JDK 17. It contains 26 original native suites, two existing
  tools, the JNI harness and C++ runtime (30 native payload files).

## Phone evidence collected

Redmi 10C / Android 13. The initial lab3 payload was
`a094a4a874417934e29f2e2fbfe75e1bb44342ac+970a659d60022bf0`.

- Paced quick suite, automatic pool of 4: clean, AWGN and MPP all completed
  exact 64-byte delivery in both directions, final ACKs and disconnect.
  150 resource samples over 39.25 wall seconds. Final moving-goodput trace
  counters each contained 64 delivered and acknowledged bytes per direction.
- Live console observed on the phone with case/mode/channel/SNR/seed context
  and actual adaptive TX/RX mode events.
- Native campaign finished: 25 suites passed, 3,864 checks, one launcher
  runtime error. The launcher incorrectly rejected digits in `test_rig_cm108`;
  the corrected APK accepts them. This was not a failing native assertion.
- Native run: 649 samples over 170.77 wall seconds. All 642 samples with an
  active child had readable child CPU and RSS. Child PSS was unavailable;
  the exported combined PSS is null, rather than an invented estimate.
- An initial older-report restore error was traced to a null parent for an
  absent campaign directory. Its path check is corrected in the rebuilt APK.
- A 15-case CPM slice finished: the NVIS SNR grid and one high-latitude
  point for fsk16r25-r1/3. All cases were saved as measurements, including
  weak-channel misses; normal/supplied data decoded in 13 cases and control
  in 10. This one-seed subset is not a reliability or sensitivity estimate.

Raw records preserve the initial launcher error:

- [Paced suite and timeline](redmi-10c-lab3-paced-2026-11-18.json)
- [Initial native suite run and timeline](redmi-10c-lab3-native-initial-2026-11-18.json)
- [NVIS/high-latitude CPM subset](redmi-10c-lab3-cpm-subset-2026-11-18.json)

## Rebuilt APK and remaining checks

Latest APK payload:
`a094a4a874417934e29f2e2fbfe75e1bb44342ac+b693d41476e9ccce`.

SHA-256:
`f00dfe693bb4a6ee84e53ef51f7b18d8d2d42dffa6e8df9bd13e1039952f37a5`.

This adds the restore/name-check corrections and the single contextual memory
graph (lab estimate and phone available RAM, both as percentages of total).
Its Java compiles and APK contents were checked. The corrected APK was installed manually. Its runtime source identity was
checked against the build.

Final-payload checks so far:

- `test_rig_cm108` now launches and passes all 13 checks.
- Contextual memory samples contain lab percentage/source, phone total and
  available RAM, available percentage, low-memory threshold and OS flag.
- Existing replay processes the retained 12.2-second recording with exit 0.
- Existing listening benchmark completes with exit 0.
- Existing recorded-burst benchmark decodes 1/1 codewords and exits 0; its
  reference-generated input and SHA256 are retained in the campaign.
- Backgrounding cancels and saves the case with next ordinal 0. Resuming
  preserves that attempt, records a second profiling segment and completes
  exact bidirectional 64-byte delivery, final ACKs and disconnect.
- Startup restoration of the actual older schema-2 report was observed with
  no restore error; the current latest report was preserved and restored.

[Final-payload smoke records](redmi-10c-lab3-final-smokes-2026-11-18.json)
include each native result, memory timeline and both resume attempts.

The final-payload full native campaign passed **26/26 suites, 3,877 checks,
zero failures**. Its 171.46-second timeline contains 650 samples, including
645 with an active native child. Contextual memory counters are present and
valid; lab memory uses both PSS and the explicitly labelled RSS fallback.
Raw evidence: [final native campaign](redmi-10c-lab3-native-final-2026-11-18.json).

The user confirmed all three manual checks on the installed final APK:
the single memory graph shows Lab and Available percentages, the case
browser opens an individual case, and a campaign ZIP exported to Downloads
can be reopened through the app's document picker. These checks complete
the prototype's end-to-end validation.

No complete 55,800-case campaign or sustained thermal/deadline
qualification is claimed. These results exercise the current weights and
must not be presented as qualification of future retrained weights.
