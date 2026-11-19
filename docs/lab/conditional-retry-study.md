# Conditional session retry study

This is the second local increment following the [controlled-loss harness](controlled-session-loss.md), committed separately as `e5ea243`. The initial study code is `ca0d008`, the targeted ACK follow-up is `6cd1437`, and the final shared analysis is `c6653c5`, on `codex/conditional-retry-study`. The binary identifies its harness as `e5ea243-controlled-loss`; each run also records the full source hashes, binary hash, study HEAD and environment. Production Python/native modem source, weights and waveform definitions remain identical to upstream v0.5.2 (`dd7af8df57373aa9f652a0af03481ab71f1608b9`).

## Question and paired design

Does alternating an existing wider-spaced CPM mode into later session retries improve recovery after earlier losses, and what does it cost on ordinary weak channels? The original natural-loss control cases did not reach the modified retry, so they could not answer that question.

The shipped caller retries in `fsk16r25-r1/2`; the candidate retains its initial transmission and first robust retry, then uses `fsk8r50-r1/3` on zero-based tries 2 and 4. The peer always uses the shipped modem. Both arms start with identical channel, noise, payload and session seeds and the same loss plan; run order alternates. Fading/noise continue on one sample clock through erased frames and silence. Schedules diverge after the changed retry; this is a policy comparison, not a fixed-audio receiver comparison.

All trials use 64 random bytes in each direction, 4.5 Hz CFO, a 2400 Hz cap, one decoder thread, a 180-second virtual-time horizon and the production DD wall-time budget. SNR is in 2500 Hz against unit active mean transmitted power; it is not PEP-matched. Sequential runs avoid competing study jobs.

### Scenarios

| Scenario | Forced signal erasures | Recovery endpoint |
|---|---|---|
| `connect` | Caller CONNECT occurrences 1 and 2 | Both sessions connected |
| `connect_ack` | Callee CONNECT_ACK occurrences 1 and 2 | Both sessions connected |
| `disc` | Caller DISC occurrences 1 and 2 | Confirmed caller closure after delivery/data ACKs |
| `disc_ack` | Callee DISC_ACK occurrences 1 and 2 | Confirmed caller closure after delivery/data ACKs |
| `connect_ack_after_loss` | Initial caller CONNECT, then first callee CONNECT_ACK | Both sessions connected |
| `disc_ack_after_loss` | Initial caller DISC, then first callee DISC_ACK | Confirmed caller closure |

The initial CONNECT matrix uses fresh seeds 101–104 at AWGN −12/−10 dB, MPP −12/−8 dB and high-latitude difficult 0/+12 dB. The other scenarios use seeds 101–102 at AWGN −12 dB and MPP −8 dB. The high-latitude cell is 0 dB for lost CONNECT_ACKs and +12 dB for DISC/DISC_ACK, to reduce setup failure dominating the closure experiment. Unreached stages remain in the results. These are small exploratory samples, not reliability qualification.

The mixed request/ACK follow-ups use the same two-seed, three-cell matrix as their corresponding ACK-only scenario. They were added after observing that two ACK losses often consumed the changed retry before the final loss was injected. All original trials are retained.

### Evidence gates and failure accounting

Every attempt retains its outcome, including untriggered loss requests, failed connection, incomplete bytes, missing final ACKs and failed closure. An eligible conditional case requires every requested erasure to have been applied **and** an actual, unsuppressed later caller retry in the expected policy mode after those erasures have **begun**. A third CONNECT alone is not sufficient: natural losses may postpone the second CONNECT_ACK erasure until a later caller attempt. In that case the script requires a subsequent eligible policy opportunity, if the retry limit allows one.

A retry that starts while an erased ACK is still being transmitted remains eligible: loss injection has already begun, and that overlap can itself cause failure. The final analysis explicitly records `opportunity_overlaps_suppressed_tx`. Earlier execution-time indexes used an end-of-erasure gate that excluded these cases; all 108 raw reports were reanalyzed consistently with the final rule. Original indexes remain in the raw archive. This exploratory refinement adds failed closure comparisons.

A paired conditional comparison also requires identical TX histories and channel start time before the first policy difference (caller occurrence 3 of CONNECT or DISC). Invalid/unreached comparisons stay visible in the all-attempt results; they are not silently counted as zero-cost successes or removed from overall outcome counts. `pairs.jsonl` records both gates explicitly. Recovery duration starts at the eligible retry's channel sample index; successful-only durations always require their denominators.

Connection recovery and whole-session completion are separate metrics. Changing the successful handshake mode can change subsequent measurements, recommendations, transmission timing and fading experienced by data. A quicker handshake therefore need not produce a quicker complete session.

The harness's original `complete` outcome includes both peers closing after the caller exhausts DISC retries. `closure_confirmed` additionally requires the exact caller event `DISCONNECTED CLIENT`, excluding `CLIENT unconfirmed`. DISC recovery and `confirmed_complete` use this stronger condition. Raw outcomes are retained unchanged.

## Results

There are **108 session attempts / 54 pairs**, of which **37 pairs** satisfy both the actual-exposure and matching-history gates. Every attempt remains in the all-attempt indexes and summaries, including the 17 pairs that do not support a paired conditional claim.

### Two forced CONNECT losses

Every cell below has four comparable pairs, seeds 101–104. Completion here also requires confirmed caller closure; it agrees with the raw `complete` counts for these cells.

| Channel | SNR | Connected: shipped / candidate | Complete: shipped / candidate |
|---|---:|---:|---:|
| AWGN | −12 dB | 4/4 / 4/4 | 4/4 / 4/4 |
| AWGN | −10 dB | 4/4 / 4/4 | 4/4 / 4/4 |
| MPP (2 ms / 1 Hz) | −12 dB | 4/4 / 3/4 | 0/4 / 0/4 |
| MPP (2 ms / 1 Hz) | −8 dB | 4/4 / 4/4 | 4/4 / 4/4 |
| High-latitude difficult (7 ms / 30 Hz) | 0 dB | 0/4 / 4/4 | 0/4 / 4/4 |
| High-latitude difficult (7 ms / 30 Hz) | +12 dB | 0/4 / 4/4 | 0/4 / 4/4 |

AWGN recovery was about 2.6–2.7 seconds quicker with the candidate. MPP at −8 dB recovered about 2.8 seconds quicker. At −12 dB MPP, one candidate never connected; among the three pairs that connected in both arms, the candidate's median additional recovery time was **20.3 seconds**. Both policies then failed to finish all four weak-MPP sessions within 180 seconds.

Complete-session timing was mixed even when recovery improved. Among pairs that completed with confirmed closure in both arms, median candidate-minus-shipped end times were +9.9 seconds at AWGN −12, −8.35 seconds at AWGN −10, and +17.2 seconds at MPP −8. These short-session times are not sustained goodput estimates; failed cases must also be read in the count table.

### ACK and closure cases

- The mixed CONNECT/CONNECT_ACK loss case produced four comparable ordinary weak-channel pairs: both policies connected and completed all four. One extreme-Doppler pair was comparable: shipped failed to connect, candidate connected and completed. The second extreme pair lacked matched eligible exposure in both arms and remains in the all-attempt results.
- Two forced DISC losses produced four comparable AWGN/MPP pairs. Both policies closed with confirmation in all four; the candidate was about 2.7 seconds quicker. The extreme cases failed to isolate closure because the shipped caller never connected. They do not qualify severe-channel DISC behavior.
- Mixed DISC/DISC_ACK losses produced four comparable AWGN/MPP pairs. **Neither policy confirmed closure in any of the four.** Both peers eventually closed, and the raw harness outcome was `complete`, illustrating why that field alone is insufficient for this question.
- The two-ACK-only scenarios did not provide comparable post-loss policy exposure in both arms. Their original outcomes, including unconfirmed closure, are retained rather than described as recovery evidence.

### Separate DISC reply-timing lead

In the AWGN −12 dB, seed 101 mixed DISC/ACK case, the unchanged shipped modem starts its last DISC while the callee is still transmitting the ACK whose signal was erased at the caller:

| Event | Channel time |
|---|---:|
| Callee starts the suppressed DISC_ACK | 86.30 s |
| Callee finishes that ACK's waveform | 91.26 s |
| Caller starts the final DISC | 89.70 s |

That is **1.56 seconds of overlap**. The callee is half duplex and misses the start of the retry. Both policies close `CLIENT unconfirmed`.

Both unchanged implementations have the same relevant timing condition: `Session.on_tx_end` uses the 2.5-second reply-start allowance during DISCONNECTING, while the policy's longer blind-reply hold applies only in CONNECTED. A robust CPM DISC_ACK lasts roughly five seconds. The standalone [timer arithmetic reproduction](../../native/lab/repro_disc_reply_overlap.py) uses the ordinary Python reference and runs on upstream v0.5.2 without the Lab or another repository. With a 1-second turn, the OFDM case has a 3.5 s deadline and nominal ACK end at 2.624 s; the robust CPM case has the same 3.5 s deadline but nominal ACK end at 5.98 s, even ignoring PTT/audio latency. The reference session source hash was checked against local upstream master.

This is a separate, narrower correction candidate: make blind DISC reply waiting account for the known ACK waveform duration, then test that normal confirmed closure timing stays unchanged. It has not been implemented or reported upstream in this increment.

## Reproduction

For each cell, run the existing sequential driver into a new directory:

```sh
python3 native/lab/study_retries.py --binary native/build-lab/data2g-lab \
  --output runs/conditional-retries-20261119/connect-awgn --scenario connect \
  --channels awgn --snrs -12 -10 --first-seed 101 --seeds 4
```

Repeat for MPP −12/−8 dB and `hilat-d` 0/+12 dB, keeping separate output directories. For each ACK or DISC scenario above, run the three single-SNR cells above with `--seeds 2`. Each output contains full per-arm JSON/progress logs, exact invocations, cases/pairs JSONL indexes, cell and paired summaries, source identities and limitations.

Reanalyze every retained raw report consistently, without overwriting the execution-time indexes:

```sh
python3 native/lab/summarize_retry_study.py \
  runs/conditional-retries-20261119 runs/conditional-retries-analysis-final
PYTHONPATH=. python native/lab/repro_disc_reply_overlap.py
```

The accounting tests run without a modem or third-party packages:

```sh
python3 -m unittest discover -s native/lab -p test_retry_study.py -v
```

They cover untriggered losses, unreached/wrong-mode retries, late ACK erasures, stage-specific recovery, unconfirmed closure, overlapping lost replies and matching pre-decision histories. Six initial tests passed before measurements; all eight final tests passed after the analysis refinements. The standalone reference reproduction was executed with the current checkout's module path and source hash verified. No hosted CI, training, cross-platform or Android work is part of this increment.

## Decision boundary

Forced erasures establish recovery conditional on specified earlier losses. They do not establish how frequently such histories occur on air. They also discard all signal from those selected bursts, rather than exercising partial reception and any cross-retry soft combining it could provide. A production change would need natural-loss comparisons, a larger independent seed set, other caps/CFOs, both peers changed, longer transfers, the matching Python policy and native/reference regression coverage.

The broad retry-policy production change is **not justified by these results**: it regresses weak-MPP connection recovery and does not establish an overall complete-session improvement. The production policy remains unchanged. The DISC reply-timing finding is retained as an independent next increment with a direct reproduction, rather than bundled into this policy.

## Evidence and validation

- [All-attempt final case index](validation/conditional-retries-2026-11-19/cases.jsonl).
- [Final paired eligibility and outcomes](validation/conditional-retries-2026-11-19/pairs.jsonl).
- [Cell summaries](validation/conditional-retries-2026-11-19/summary.json), including all-attempt completion, confirmed completion, conditional recovery and overlapping-retry counts.
- [Source, execution and analysis identities](validation/conditional-retries-2026-11-19/metadata.json). Repeated source manifests are deduplicated by SHA-256; original full execution metadata remains in the raw archive.
- [All raw reports, logs and original indexes](validation/conditional-retries-2026-11-19/raw-cases.zip): 306 files across 18 run directories, retaining the initial and follow-up analyses as they were emitted.
- [Standalone reference timer result](validation/conditional-retries-2026-11-19/disc-timer-repro.json).

All 108 reports were checked against their requested loss plans and policy identity. Their native core/harness source hashes and binary hashes match; study source hashes match their execution commits. All 54 paired attempts are retained. The raw archive passed its CRC check, and the timer reference source hash matches upstream-baseline `master`. The final whitespace check passed. The earlier harness suites, default-behavior comparisons and native includes/layering checks are recorded in the [harness increment](controlled-session-loss.md#validation); all eight final accounting tests passed. Production `data2g/` and `native/core/` trees have no differences from local upstream `master`.
