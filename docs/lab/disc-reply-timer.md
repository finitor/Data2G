# DISC reply-timer investigation

The unchanged v0.5.2 session timer can retry a DISC while its peer is still transmitting DISC_ACK, when the ACK header was not decoded. This is a protocol-timer defect reproduced in both Python and C++, independently of the retry-mode study. An isolated local correction eliminates the observed ACK overlaps and recovers all eight mixed-loss cases in this small paired sample. Its cost is longer unanswered disconnects; the documented host ABORT budget needs consideration before shipping it.

## Cause and isolated correction

Baseline: upstream `dd7af8df57373aa9f652a0af03481ab71f1608b9` (v0.5.2). `Session.on_tx_end` arms `now + t_turn + 2.5 s` during DISCONNECTING. A decoded header extends that deadline, but a completely missed header cannot. The longer blind-reply hold applies only to CONNECTED. DISC retries have no CONNECT-style randomized backoff, so the timeout can immediately produce a collision.

DISC_ACK is sent in the received DISC's mode. Its one-byte session body has the same control layout and slot count as DISC. With a one-second turn, the baseline deadline is 3.5 seconds after DISC ends, but a robust `fsk16r25-r1/2` ACK nominally finishes at 5.98 seconds: 2.48 seconds too late, even before PTT/audio delays.

The focused branch `codex/disc-reply-timer`, commit `958a265`, starts directly from upstream master and contains only the correction, documentation and regression tests. In both implementations, DISCONNECTING adds the actual DISC mode's reply airtime, using the actual control slot count, to the existing reply-start window. The robust-mode deadline above becomes 8.48 seconds; the initial OFDM deadline becomes 5.124 seconds. The full existing start allowance is retained, including for a late short ACK. A heard ACK still closes immediately.

Retry count, retry modes, wire format, negotiation and CONNECT/CONNECTED timers remain unchanged. The Lab validation branch `codex/disc-reply-timer-study` deliberately imports that focused commit as `bfa831b`; it does not import Lab history into the focused branch. Upstream master is unchanged, and nothing has been published upstream.

## Paired audio results

The two binaries use identical compiled Lab sources and upstream native core sources except for `native/core/arq/session.cpp`. The baseline binary's hash and core source hashes were verified against the earlier pinned study and upstream master. Both arms use the shipped retry policy throughout; blind alternation is disabled.

All 60 trials use 64 random bytes each direction, a 2400 Hz cap, one decoder thread, 4.5 Hz CFO, a 180-second virtual-time horizon, unit active mean transmitted power and SNR referenced to 2500 Hz. They run sequentially on macOS ARM64 with the production DD wall-time budget. Seeds are 101–104 for four-pair cells, 101–102 for two-pair cells, and 201–208 for natural AWGN −14 dB. These are Gaussian noise/fading simulations, not impulsive atmospheric-noise or RF tests.

Completion below requires exact delivery, final data ACKs, both peers closed, and the exact `A DISCONNECTED CLIENT` event. Raw `outcome: complete` alone includes unconfirmed closure and is insufficient.

| Scenario | Pairs | Confirmed before | Confirmed after | Pairs with DISC/ACK overlap, before → after |
|---|---:|---:|---:|---:|
| Natural, clean | 2 | 2 | 2 | 0 → 0 |
| Natural, AWGN −12 dB | 4 | 4 | 4 | 0 → 0 |
| Natural, MPP −8 dB | 4 | 4 | 4 | 0 → 0 |
| Natural, AWGN −14 dB | 8 | 5 | 6 | 1 → 0 |
| First DISC and first DISC_ACK erased, AWGN −12 dB | 4 | 0 | 4 | 4 → 0 |
| First DISC and first DISC_ACK erased, MPP −8 dB | 4 | 0 | 4 | 4 → 0 |
| First two DISCs erased, AWGN −12 dB | 2 | 2 | 2 | 0 → 0 |
| First two DISC_ACKs targeted, AWGN −12 dB | 2 | 0 | 0 | 2 → 0 |

All 30 pairs have identical connection, delivery and final data-ACK times. All 29 pairs that reach DISC have identical transmission histories through the first DISC; natural AWGN seed 203 never reaches that stage in either arm. Both clean controls have identical complete transmission traces and closure times. Failures and unreached stages are retained.

The two-ACK-loss control deliberately remains unconfirmed. Both requested ACK erasures occur after the correction; only the first occurs on the baseline because its collision prevents the peer from sending the second ACK. It verifies bounded failure rather than providing an equally exposed recovery comparison.

In the original mixed-loss AWGN −12 dB seed 101 reproduction, the baseline sends its final DISC at 89.70 s while the suppressed ACK occupies 86.30–91.26 s: 1.56 s of overlap. After correction, the suppressed ACK occupies 87.90–92.86 s and the final DISC starts at 96.30 s. The re-ACK finishes at 106.36 s and closure is confirmed. The native core's responder path is unchanged; these are two-endpoint candidate runs, not a separately built old-peer interoperability test.

Natural AWGN −14 dB seed 205 changes from overlapping retry and unconfirmed closure at 169.4 s to confirmed closure at 164.3 s. Across all natural cases the count changes from 15/18 to 16/18. This supports the mechanism, not a broad channel-reliability or goodput claim: schedules sample different channel/noise times after the timer changes.

## Cost and host timing

An unheard reply now costs one additional expected ACK airtime per attempted DISC: about 1.624 seconds for the initial OFDM attempt and 4.98 seconds for each robust FSK attempt at this cap. In the two-lost-DISC controls, completion is about 6.5 seconds later with no increase in the completion count. Normally heard replies finish immediately, as the regression cases and clean controls verify.

The standalone default-policy exhaustion reproduction, with every reply absent, a one-second turn, no PTT/ID overhead and the first DISC starting at zero, takes **22.084 s before versus 33.668 s after**, still with exactly three attempts. Thus the conservative guard adds 11.584 seconds in complete failure. The repository [documents BPQ32 sending ABORT 30 seconds after an unanswered DISCONNECT](../arq.md#6a-v1-implementation-choices-data2garqsessionpy). Such a client can preempt the longer timer sequence. This study does not exercise a BPQ32 client or establish that host-budget compatibility; the local candidate should not be presented as having no host-timing tradeoff.

This is a session protocol deadline. Its arithmetic reproduction and the unpaced Lab use protocol/sample time, so it is distinct from the engine's wall-clock processing deadline under competing builds or swapping. These runs do not qualify live audio scheduling, arbitrary backend latency or a CW-ID timing matrix.

## Correctness and reproduction

The new 42-case Python/native timer suite fails 12 cases on unchanged upstream and passes all 42 after correction. It covers either disconnecting role, five actual modes including multi-slot control, missed headers, a late OFDM reply, immediate confirmed closure and unchanged retry exhaustion. Unlike the general session simulator, it does not defer retries using oracle knowledge of an unheard peer transmission. Four direct C++ regression checks also fail on the baseline.

The corrected native ARQ suite passes 818 checks and the engine suite passes 73 checks. The broader reference/parity run reports 401 passed, two skipped and one failure because the unrelated outcome-ensemble test cannot import PyTorch. With native substitutions and that test explicitly deselected, 400 pass and three skip. The skips concern disabled outcome-model gates and Python-only history. No training was run or dependencies installed. The Lab loss-selection/recovery suite also passes; full logs are retained.

The [timer arithmetic fixture](../../native/lab/repro_disc_reply_overlap.py) and [default retry-budget fixture](../../native/lab/repro_disc_retry_budget.py) run against an ordinary upstream checkout without the Lab or another repository:

```sh
PYTHONPATH=. python /path/to/repro_disc_reply_overlap.py
PYTHONPATH=. python /path/to/repro_disc_retry_budget.py
```

Build the original Lab harness at `20bd62c` with unchanged upstream core, retaining its binary as `/tmp/data2g-disc-timer-before`; build `bfa831b` with revision label `958a265-disc-reply-timer` for the corrected arm. Use the [normal local Lab build](build.md), RelWithDebInfo and two build workers. The [paired driver](../../native/lab/disc_timer_study.py) fixes the complete case matrix and never enables alternation:

```sh
python native/lab/disc_timer_study.py \
  --before /tmp/data2g-disc-timer-before \
  --after native/build-lab/data2g-lab \
  --output runs/disc-reply-timer-repeat
```

The focused worktree was validated with the normal pybind module and `test_arq_link`/`test_engine` targets, then:

```sh
PYTHONPATH=. python -m pytest tests/test_disc_reply_timer.py tests/test_arq_session.py tests/test_native_arq_link.py tests/test_arq.py tests/test_arq_policy.py -n 0 -q
PYTHONPATH=. python -m pytest tests/test_disc_reply_timer.py tests/test_arq_session.py tests/test_native_arq_link.py tests/test_arq.py tests/test_arq_policy.py --native -n 0 -q -k 'not test_outcome_ensemble_averages_member_probabilities'
ctest --test-dir native/build -R '^(engine|arq_link)$' --output-on-failure
```

[Validation evidence](validation/disc-reply-timer-20261119/) contains readable summaries, paired outcomes, source/binary hashes, environment and timer-budget outputs. Its raw archive includes every trial JSON, stdout/stderr record, test/build logs and failed cases. The archive CRC, requested settings, all pre-DISC metrics, reached-stage prefixes and zero remaining ACK overlaps were checked. Validation was local macOS ARM64 only; no hosted CI was enabled or run.
