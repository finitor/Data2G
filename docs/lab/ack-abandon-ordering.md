# ACK/abandon follow-up

Repository: finitor/Data2G; branch study/ack-abandon-ordering; base 9894b6366cfe7f5bd4d30555c3327a808840e248 (upstream HEAD refreshed 22 Nov 2026). The correction commit on this branch is the review revision; see Git HEAD and the evidence bundle's COMMIT.txt for its exact identifier. Root guide copied from maintained checkout 9924772 before work. Eventual contribution target is fork master; this investigation makes no merge decision.

User authorized tracing the uninvestigated ACK/abandon failures in #285. Do not repeat validation already covered by #284/#285. Do not test their fixes together until the user reviews this next round. No upstream posting. Only bounded local macOS ARM64 studies; hosted CI stays disabled.

Known failing session seeds from the original confirmation JSONL:
- unchanged baseline, NVIS 1 Hz / 7 ms, -10 dB, seed 100033: ACK of pre-abandon burst 3 past the abandon at 0.
- robust-start-only branch, poor 1 Hz / 2 ms, -6 dB, seed 100023: abandon at 0, cumulative 2.

## Finding

Both reported failures reproduce exactly and both disappear when the event harness enforces the Engine's existing rule: do not poll a session while its own transmitter is active. This is a reproduced simulator scheduling defect, not evidence requiring relaxation of the ARQ's abandon checks. The live Engine has this guard already (`Engine.step`, its `tx is None` branch). No production modem/ARQ implementation was changed in this round.

A callee sends a long control reply, then its host writes data while that reply is still on air. `Session._wake_time` can expose the old wake timer from its preceding transmission. `linksim.run` had suppressed polling while receiving, but not while transmitting. It polls early, builds/sends another burst, then the old TX-end callback rearms the wake timer during the new transmission. Later overlapping receptions can make abandon state diverge.

The callee's first premature poll in the baseline case occurs at 79.310660 s, before its previous burst ends at 79.845938 s. The robust-start case polls at 42.421630 s, before its previous burst ends at 42.475568 s. PTT delay avoids actual overlap on that first robust-case poll, but the later old TX-end callback triggers a repeat at 47.850730 s while its data burst continues until 52.521630 s. The event PHY independently decodes both waveforms instead of modeling an impossible self-overlap.

## Correction and regression

`scripts/linksim.py` now tracks each sender's TX end, suppresses its poll through that end and omits its blocked timers from the next-event set. The TX-end event stays scheduled and releases the guard. Excluding the blocked timer also avoids spinning on a timer already due during TX. Receive holds and the carrier-sense model otherwise retain their behavior.

`tests/test_linksim.py` minimizes the defect with a deterministic fake PHY, five-second bursts and a host write during the callee's reply. The one-second application-delay case fails on unchanged HEAD by detecting a station keying over itself; zero/0.2-second controls pass. All three pass with the harness correction in both Python and native-substituted session runs. The native run uses the unchanged baseline module; no C++ source changed.

## Targeted replay outcomes

These replay only the two untraced failures, not the studies already covered by #284/#285. The baseline stays unchanged; the other replay uses only the published robust-start commit `025d21e05365cffe2f7adacceb9fc16623a866ed`. Neither arm includes the per-tone fix or notch. The same final-ACK drain and 180 s horizon as the source study are retained. The canonical patched `linksim.run` was supplied to both replays without modifying either source checkout. Fixed results match the initial in-process guard diagnostic.

| Case | Original protocol outcome | With harness correction |
|---|---|---|
| NVIS 1 Hz / 7 ms, -10 dB, seed 100033, baseline | pre-abandon ACK failure | No protocol failure or overlap; 128 bytes delivered, final ACKs incomplete at 180 s |
| Poor 1 Hz / 2 ms, -6 dB, seed 100023, robust start only | abandon/cumulative failure | No protocol failure or overlap; 128 bytes and final ACKs complete at 63.023 s |

Exact delivered bytes are checked by the upstream harness, not just lengths. Zero mismatch counts and both corrected sessions remaining connected are recorded in the raw traces. No broad protocol-correctness guarantee follows from two cases; the safety checks remain necessary for genuine reordering.

## Exposure in existing saved results

A read-only audit of the existing 1040-row confirmation JSONL, without new DSP runs, finds overlapping transmission intervals in 56/520 baseline sessions (145 interval pairs) and 57/520 robust-start sessions (153 pairs). 113/1040 sessions therefore violate the declared ideal carrier-sense model. The overlap audit lacks sender labels; it does not attribute every case to self-transmission, only flags invalid overlap for that model. The two instrumented failure replays do establish the self-transmission mechanism.

The aggregate #285 comparative outcomes should be refreshed after the harness fix. This audit neither computes revised gains nor invalidates the separately demonstrated post-CONNECT policy mechanism. No published studies were rerun wholesale and no issue/comment/PR was posted by this round.

## Validation and evidence

Local macOS ARM64, Python 3.12.15, native baseline Release module:

- Regression before correction: 1 failed, 2 passed.
- After correction: 3 passed (Python); 3 passed (native substitutions).
- Four original/guard diagnostic replays and two canonical fixed-harness replays completed. Only the original two have protocol failures.
- Layering and `git diff --check` pass. No native rebuild, full modem suite, platform matrix, audio/radio run or hosted CI was needed/run for this Python study-harness-only correction.

Raw traces, original failing rows, saved-result overlap audit, checksums and logs are under local `runs/ack-abandon/`. The baseline source snapshot was checked against the pinned Git blobs; provenance includes the native module hash and relevant study source hashes. Preserve the evidence bundle with this note when handing off; no runtime machine path is required.

```sh
python -m pytest tests/test_linksim.py -q -n0
python -m pytest tests/test_linksim.py -q --native -n0
python scripts/ack_abandon_repro.py --root /path/to/built-baseline --case baseline --out runs/ack-abandon/baseline-original.json
python scripts/ack_abandon_repro.py --root /path/to/built-robust-start --case robust --out runs/ack-abandon/robust-original.json
python scripts/ack_abandon_repro.py --root /path/to/built-baseline --harness-root /path/to/corrected-harness --case baseline --out runs/ack-abandon/baseline-fixed.json
python scripts/ack_abandon_repro.py --root /path/to/built-robust-start --harness-root /path/to/corrected-harness --case robust --out runs/ack-abandon/robust-fixed.json
python scripts/audit_session_overlap.py /path/to/sess-start-confirm.jsonl --out runs/ack-abandon/saved-trace-audit.json
```

The source-root native module must be built for the selected interpreter. For this study, the new harness checkout borrowed the verified baseline module via PYTHONPATH; the replay script also accepts separate source and harness paths. Its optional `--guard` is the diagnostic runtime intervention; canonical fixed runs above read the actual corrected function instead.

## Next review

Review this simulator correction first. Hold combined #284/#285 testing until the user reviews this round, as explicitly requested. Do not weaken ARQ safety checks or infer an upstream reporting/merge authorization. Once reviewed, decide whether to refresh affected independent session measurements before any combined study. Existing packet-level and continuous receiver tests that do not use this event loop are outside this finding.
