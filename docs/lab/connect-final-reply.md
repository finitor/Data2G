# Final CONNECT reply allowance

On a weak streaming link, the caller can close NO_ANSWER while the peer's valid CONNECT_ACK is still arriving. The final robust CONNECT ended at 53.06 s, its matching ACK occupied 53.10–58.16 s, the caller closed at 56.60 s, the header was reported at 57.40 s and the nonce-matching ACK decoded at 58.30 s. Earlier timeouts leave the caller CONNECTING during the 3–5 s retry jitter; the last timeout closes immediately. This is a CONNECT-specific instance of the timer pattern reported for DISCONNECT in upstream #253. That fix was not included or revalidated.

## Change

Only the final CONNECT's reply timer adds one full CONNECT_ACK airtime in the request's mode to the existing turnaround and reply-start allowance. ACK slots are computed from its control envelope and the mode's control payload size, including modes with multiple control slots. Python and C++ use the same rule. With the stock robust CPM mode, the extra allowance is 4.98 s; its default total wait becomes 8.48 s after CONNECT TX ends. Ordinary header-based extensions still apply.

No earlier retry deadline, retry jitter, retry count, mode choice, waveform, frame or protocol version changes. A missing, unreadable, malformed or wrong-nonce ACK still ends in NO_ANSWER. A matching NAK closes immediately. Host DISCONNECT still prevents another attempt; a late accepted dial gets DISC next. An already closed dial cannot be reopened by a late ACK. The cost is a longer final no-answer window, including when the host cancels during it; successful earlier handshakes incur no added wait.

## Paired streaming check

Twelve ordinary Python Engine/native streaming receiver cases from the preceding investigation are reused as baselines; twelve new corrected cases use the same frozen driver, seeds, continuous noise/fading and 300 s limit. One additional corrected +20 dB clean control is compared with its saved baseline. All use stock Python ARQ/policy with native DSP/FEC, mean active power against noise in 2500 Hz, 4.5 Hz CFO, 64-byte request/response and exact bytes/final ACK accounting. NVIS has equal two-path Rayleigh fading, 7 ms delay and 1 Hz Gaussian Doppler (2σ). Oracle carrier holds and runtime deadline deferrals are off. The #286 tooling guard is present in the source baseline; the Engine does not use its event loop. Neither #284 nor #285 is included.

| Point, four seeds each | Both ends connect, baseline → corrected | Complete exchange, baseline → corrected |
|---|---:|---:|
| AWGN −14 dB | 4 → 4 | 4 → 4 |
| AWGN −16 dB | 0 → 2 | 0 → 0 |
| NVIS −12 dB | 4 → 4 | 4 → 4 |

The original seed 111001 now accepts the matching ACK at 58.3 s without a diagnostic override. Seed 111002 also establishes both ends. Both subsequently close LINK_LOST with no application bytes; two other −16 dB callers still exhaust their attempts. There is no completed-exchange gain. Every noise hash and pre-original-closure physical TX/receiver/state prefix matches. All eight successful matrix cases and the clean control reproduce their entire prior result, excluding added telemetry and wall-clock execution time. The clean control completes at 10.5 s in both. No broad sensitivity or field-cause claim follows.

## Validation

macOS 15.8.3 ARM64, AppleClang 17, Release, Python 3.12.15, NumPy 2.5.5, SciPy 1.18.1, pybind11 3.1.0. Native module and arq_link/engine/host test targets build. Reference CONNECT/session tests: 75 passed. The native-substituted CONNECT/session/parity subset: 129 passed; the same run additionally passes five host tests. Two further host socket tests pass after allowing loopback access. Three targeted native Engine host cancellation/retry tests pass. Python-free arq_link, engine and host ctests: 3/3 passed, including the late-ACK and absent-ACK timer regression with the native GearPolicy. Include, layering and whitespace checks pass.

Three broader Python-host checks remain unavailable because PyAudio is missing: the capture check and two fake-audio TCP tests whose host threads require its constants. The sandbox first blocked four loopback tests; after allowing socket access, two passed and the other two exposed that missing audio dependency. These are recorded as environment failures, not passes. No dependency installation, full suite, hardware, other-platform or wall-clock decoder-deadline qualification was performed. The streaming screen uses Python Engine/ARQ with native reception; it is not a pure C++ weak-channel Engine comparison.

```sh
python scripts/connect_final_reply_repro.py --expect-connected
python scripts/connect_final_reply_repro.py --root BASELINE_CHECKOUT
python -m pytest tests/test_connect_reply.py tests/test_arq_session.py -q -n0
python -m pytest tests/test_connect_reply.py tests/test_arq_session.py tests/test_native_arq_link.py -q --native -n0
python -m pytest tests/test_engine.py::test_disconnect_while_dialing_frees_the_modem_after_one_try tests/test_engine.py::test_retries_sets_this_clients_connect_retries -q --native -n0
ctest --test-dir native/build -R '^(arq_link|engine|host)$' --output-on-failure
```

The standalone reproducer needs only the chosen checkout and its test dependencies, without DSP/native binaries or another repository. A baseline checkout closes after 3.5 s and ignores the ACK; corrected source waits 8.48 s and accepts it. Build the native module for the selected interpreter as described in native/README.md. Streaming drivers, raw paired evidence, hashes and exact plans are retained in the investigation evidence bundle, without binary build artifacts.

## Handoff

Repository finitor/Data2G; branch fix/connect-final-reply; base 509dfc6ba08f810c60edf021bc8df9579743302c (upstream 9894b6366cfe7f5bd4d30555c3327a808840e248 plus the #286 tooling correction and its notes). Upstream HEAD was refreshed and unchanged. The review revision is the commit containing this note; the evidence bundle records its exact hash. Intended eventual target is fork master, through deliberate selection/review; no merge or upstream publication is authorized by this note. Root AGENTS.md originates from maintained checkout 9924772; README, architecture and native guides were read. Private repository unattended-merge instructions do not apply. Combined #284/#285 testing remains on hold; do not routinely repeat their existing qualification.

The scoped correction and bounded local checks are complete. Remaining gates are review of the final no-answer/cancellation latency tradeoff, sequential platform qualification and hardware/audio testing. This change does not address the persistent weak-link data/control outages. Directional asymmetry and sample-clock/drift studies remain separate, unrun hypotheses. No hosted CI, training, broad profiling or upstream communication was performed.
