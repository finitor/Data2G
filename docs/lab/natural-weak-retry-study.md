# Natural-loss weak-channel retry validation

This follow-up measures how often the candidate's later retries are reached under natural losses and what their costs are on ordinary weak channels. It follows the [conditional study](conditional-retry-study.md), uses the same existing native Lab executable and keeps the production modem and default policy unchanged.

The fixed plan and accounting tests were committed as `adba6c7` before measurements. All four cells used that execution revision and the same binary, identified as `e5ea243-controlled-loss`. The production Python/native core and generated weights remain identical to the local upstream v0.5.2 baseline, `dd7af8df57373aa9f652a0af03481ab71f1608b9`.

## Fixed plan

The matrix is fixed before execution. Each cell has 32 fresh paired seeds, with separate seed ranges across cells: 128 pairs / 256 session attempts. Every attempt counts, including cases that never exercise the candidate and cases that fail to connect or complete.

| Channel | SNR in 2500 Hz | Seeds |
|---|---:|---|
| AWGN | −16 dB | 2001–2032 |
| AWGN | −14 dB | 2101–2132 |
| MPP: 2 ms delay / 1 Hz Doppler spread | −12 dB | 2201–2232 |
| MPP: 2 ms delay / 1 Hz Doppler spread | −8 dB | 2301–2332 |

The AWGN cells probe the ordinary weak-signal control region. MPP −12 dB targets the previously observed conditional connection regression; MPP −8 dB includes the nearby operating point where short transfers generally completed. This is a focused screen, not an estimate of the distribution of channels encountered on air.

Both arms use identical starting channel/noise/payload/session seeds, 64 random bytes per direction, 4.5 Hz CFO, a 2400 Hz bandwidth cap, one decoder thread and a 180-second simulated horizon. They use unit active mean transmit power and the existing production DD wall-time budget. Run order alternates, and trials run sequentially. There are no synthetic erasures. The callee always uses the shipped policy; only the caller optionally alternates existing CPM modes on later CONNECT/DISC retries.

## Accounting

The first policy-changing opportunity is caller occurrence 3 of either CONNECT or DISC. The analysis checks both phases together. A pair with matching TX history and start time before that opportunity is classified as exposed, with its first phase recorded. A wholly unexposed pair must have identical transmission traces and protocol outcomes/timing. Pre-change or unexposed mismatches remain visible and cannot be attributed to the retry policy; DD's wall-time budget is one possible source of such nondeterminism.

Primary counts include all attempts: connection, exact delivered bytes, final data ACKs, the original both-peers-closed completion criterion and confirmed caller closure. Confirmed completion additionally requires the exact caller event `DISCONNECTED CLIENT`, excluding `CLIENT unconfirmed`.

Timing summaries include paired deltas among cases that connected or confirmed completion in both arms, with their sample counts. Separate all-attempt capped-wait scores assign the 180-second horizon to a failed connection or unconfirmed completion. These scores combine success and delay within this experiment; they are not mean latency estimates for successful traffic or sustained application goodput. Per-cell results are retained separately; the four selected SNR points are not weighted to represent an on-air population.

## Reproduction

```sh
python3 native/lab/natural_retry_study.py run \
  --binary native/build-lab/data2g-lab \
  --output runs/natural-weak-retries-20261119
python3 native/lab/natural_retry_study.py analyze \
  runs/natural-weak-retries-20261119 runs/natural-weak-retries-analysis
python3 -m unittest discover -s native/lab -p 'test_*retry_study.py' -v
```

The existing sequential driver preserves each arm's complete JSON and progress log, exact invocation and source/binary/environment identity. The natural-loss analysis reads those raw reports directly and preserves the execution-time conditional indexes unchanged. Its paired classifications and summaries are specific to this all-attempt natural-loss question.

## Results

All 256 attempts / 128 pairs completed as measurements. **59 pairs reached a changed retry with matching prior TX history and start time; 69 pairs never reached a changed retry and matched exactly.** There were no unexposed or pre-change mismatches, synthetic erasures or accepted-payload mismatches. The fixed sample was completed without stopping early on observed outcomes.

### Natural retry frequency

These are counts out of 32 pairs per cell. A pair is assigned to its first changed phase; a CONNECT-first pair can subsequently also reach changed DISC retries. These frequencies describe the selected test points, not an on-air channel population.

| Point | CONNECT first | DISC first | Never exposed |
|---|---:|---:|---:|
| AWGN −16 dB | 32 | 0 | 0 |
| AWGN −14 dB | 2 | 5 | 25 |
| MPP −12 dB | 17 | 1 | 14 |
| MPP −8 dB | 0 | 2 | 30 |

### All-attempt outcomes

Each entry is **shipped / candidate**, with 32 attempts per arm. Delivery means all 64 bytes arrived exactly in both directions. Final data ACKs are a separate gate. The original `complete` outcome additionally requires both peers closed; confirmed completion also excludes caller closure marked `CLIENT unconfirmed`.

| Point | Connected | Delivered both ways | Final data ACKs | Complete | Confirmed complete |
|---|---:|---:|---:|---:|---:|
| AWGN −16 dB | 20 / 7 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| AWGN −14 dB | 32 / 32 | 30 / 30 | 29 / 29 | 25 / 22 | 25 / 21 |
| MPP −12 dB | 29 / 25 | 11 / 8 | 7 / 5 | 4 / 2 | 3 / 2 |
| MPP −8 dB | 32 / 32 | 32 / 32 | 32 / 32 | 32 / 32 | 31 / 31 |

At AWGN −16 dB, 15 pairs connected only with the shipped policy and two only with the candidate. This demonstrates a connection-margin cost, but neither policy delivered application bytes in these 180-second cases; it does not establish a useful application-data operating point there.

At MPP −12 dB, four pairs connected only with the shipped policy and none only with the candidate. Three pairs delivered the full payload only with the shipped policy and none only with the candidate. Total verified application bytes were **1,728 shipped versus 1,152 candidate**, including partial deliveries. Thus the observed cost is not confined to setup or closing bookkeeping. The sample remains too small to claim a precise population regression rate.

At AWGN −14 dB, both arms delivered the same total of 3,968 verified bytes. The four lost confirmed completions all came from the five DISC-first exposed pairs: shipped confirmed closure in four, candidate in none. At MPP −8 dB, both arms delivered all 4,096 possible bytes. The two exposed DISC pairs had matching success outcomes; the candidate closed 2.8 seconds sooner in the one that confirmed closure in both arms.

### Recovery and completion time

The all-attempt scores below assign 180 seconds to failed connection or unconfirmed completion. The activated-CONNECT delta is candidate minus shipped, among CONNECT-first exposed pairs that connected in both arms; its sample count is explicit. Matching opportunity start times make that paired setup-time difference also the difference in recovery time after the changed retry. These conditional medians do not include failed setups.

| Point | Mean capped connection wait: shipped / candidate | Activated-CONNECT median delta (paired successes) | Mean capped confirmed-completion wait: shipped / candidate |
|---|---:|---:|---:|
| AWGN −16 dB | 94.49 / 149.91 s | −1.40 s (5) | 180.00 / 180.00 s |
| AWGN −14 dB | 20.34 / 21.04 s | +11.15 s (2) | 156.56 / 158.28 s |
| MPP −12 dB | 41.02 / 61.26 s | +10.50 s (10) | 178.74 / 179.47 s |
| MPP −8 dB | 18.66 / 18.66 s | Not reached | 109.61 / 109.52 s |

All-pair successful-only medians often equal zero because most pairs at the stronger operating points are unexposed. The [exposed summaries](validation/natural-weak-retries-2026-11-19/exposed-summary.json) therefore also retain activation-only and first-phase breakdowns, using the same summary function. Those are descriptive subgroups; all-attempt outcome counts remain the primary comparison.

## Interpretation

The natural-loss measurements confirm a practical tradeoff worth preserving in the decision. Later retries are common at the weak control points, and blind alternation loses connection margin and, at MPP −12 dB, delivered application bytes. At the stronger MPP point it is mostly inactive and the outcomes match. The earlier extreme-Doppler gains remain valid within that model; they do not establish that an unconditional default improves ordinary weak-channel operation.

One plausible contributor is the existing control-repeat combining rule: both `data2g/arq/phy.py` and `native/core/arq/phy.cpp` discard stored repeated-control soft information when the received mode changes. Natural failed attempts can contain useful partial information that forced whole-frame erasures removed. This study includes that behavior, but does not isolate its contribution from waveform sensitivity, subsequent recommendations or changed fading/noise sampling after schedules diverge.

**Recommendation: retain the shipped production default.** Continue developing a condition-aware or more carefully bounded severe-channel retry policy, and treat the separately reproduced DISC blind-reply timing issue as its own increment. These results do not justify universal blind alternation. They also do not qualify other bandwidth caps, larger transfers, two changed peers, interference, impulsive atmospheric noise, real audio deadlines or field performance. No natural channel mixture was assumed to weight a global default decision.

## Saved evidence and validation

- [Fixed execution plan](validation/natural-weak-retries-2026-11-19/plan.json).
- [All 256 attempt outcomes](validation/natural-weak-retries-2026-11-19/cases.jsonl) and [128 paired classifications](validation/natural-weak-retries-2026-11-19/pairs.jsonl).
- [All-attempt cell summaries](validation/natural-weak-retries-2026-11-19/summary.json) and [exposed/first-phase summaries](validation/natural-weak-retries-2026-11-19/exposed-summary.json).
- [Source, binary and execution identities](validation/natural-weak-retries-2026-11-19/metadata.json). Repeated source manifests are deduplicated by SHA-256; original full metadata remains in the raw archive.
- [Full raw reports, progress logs and original execution-time indexes](validation/natural-weak-retries-2026-11-19/raw-cases.zip): 533 files. The original driver's CONNECT-focused conditional eligibility fields remain unchanged; the natural-loss paired analysis above accounts for CONNECT and DISC jointly.
- [Accounting-test output](validation/natural-weak-retries-2026-11-19/accounting-tests.log): all 14 tests passed before measurements, including six new natural-loss accounting checks.

The analysis checked every paired input against the fixed matrix and declared settings, rejected any synthetic suppression or wrong retry mode, and retained all failures. The binary hash and every recorded source hash matched the files used; all four cells have the same manifest. The raw archive passed its CRC check. The production `data2g/` and `native/core/` trees have no differences from local upstream `master`. No modem build, training, hosted CI or other-platform work was performed for this follow-up.
