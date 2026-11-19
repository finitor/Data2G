# Controlled session losses

This desktop Lab increment supplies deterministic, opt-in received-signal
erasures for the [session retry study](severe-session-retries.md). It changes
no production modem source, trained weight, transmitted waveform or retry
default. It builds on the existing Lab and retry-study branch; local
upstream `master` remains untouched.

## Selecting losses

Repeat `--suppress ENDPOINT:FRAME:OCCURRENCE`, where endpoint is `A` (caller)
or `B` (callee), frame is `CONNECT`, `CONNECT_ACK`, `DISC` or `DISC_ACK`, and
occurrence is one-based **per endpoint and frame type**. Requests must be
unique; occurrences are limited to 1–1000, with at most 64 requests. These
flags apply only to session workloads, including diagnostic fixed modes.
They are not exposed in the Android UI or campaign enumerator.

For example, erase the initial CONNECT and first robust retry, allowing the
third CONNECT to exercise the candidate's different mode:

```sh
native/build-lab/data2g-lab --channel awgn --snr -12 --seed 101 \
  --threads 1 --cfo 4.5 --bytes 64 --horizon 180 \
  --suppress A:CONNECT:1 --suppress A:CONNECT:2
```

Repeat with `--alternate-retries` for the candidate. Other scenarios replace
the two targets with `B:CONNECT_ACK:1/2`, `A:DISC:1/2` or `B:DISC_ACK:1/2`.
Suppressing acknowledgments retains the receiver's normal protocol state,
so these cases exercise duplicate handling as well as subsequent retries.

## Signal and protocol semantics

The existing engine virtual TX seam supplies exact sample lengths for each
frame. Ordinary and compact CONNECTs are classified from the transmitter's
own control slots. IDs, CQ, data and nod signals do not count as session
frames. This metadata controls only the loss injector; it supplies no
timing, channel or header knowledge to a receiver.

The engine transmits the full original audio, with its original PTT,
airtime and timers. The channel measures active power on the original
bundle, computes its analytic samples, zeros the selected frame's interval,
and then applies normal fading, delay and CFO. A selected first frame's
leading PTT prefix is included to remove analytic-transform ringing. This
also removes that interval's delayed echo while preserving other frames'
gain, including IDs bundled on the same PTT. Additive receiver noise is
drawn continuously by the unchanged transport on the channel sample clock.
No surviving waveform is renormalized after an erasure.

This is a synthetic, whole-frame received-signal erasure. It does not model
the probability, shape or duration distribution of atmospheric fades or
impulses. Conditional recovery after forced losses must be reported
separately from natural-loss reliability and application goodput.

## Result accounting

- `suppression_plan`: every requested target with its `applied` status.
- `suppression_plan_applied`: true only when **all** requests were applied;
  true for an empty plan.
- `suppressed_bursts`: applied request count, separate from natural RX loss
  counters.
- `transmission_trace`: endpoint, frame type, occurrence, mode, absolute
  `channel_first_sample`, sample length and suppression status. The channel
  sample index includes the harness's existing one-block transport latency
  and excludes a frame's leading PTT prefix.

A session can complete without reaching a requested loss. Its normal
outcome stays `complete`, while the plan remains visibly unapplied. Such a
case cannot be counted as conditional recovery evidence. A study must also
verify the later, unsuppressed retry was actually emitted in the expected
mode; applying the plan alone does not establish that.

## Validation

Build and run locally on macOS ARM64:

```sh
cmake -S native/lab -B native/build-lab -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build native/build-lab --target data2g-lab test_lab test_lab_loss --parallel 4
ctest --test-dir native/build-lab -R '^(lab|lab_loss)$' --output-on-failure
```

`lab_loss` checks selection and malformed/duplicate requests, ordinary,
multi-codeword and compact controls, exclusion of IDs/nods, applied versus
untriggered accounting, whole-frame erasures including fading tails,
partial-frame gain preservation and the actual transport's continuous
noise stream. It runs both retry policies through clean complete sessions
with two forced losses for each of CONNECT, CONNECT_ACK, DISC and DISC_ACK,
requiring exact bidirectional bytes, final ACKs and closure.

The empty-plan regression compares the saved pre-change executable with
the new executable for clean, AWGN, MPP and high-latitude difficult cases
at +12 dB, seed 1, 4.5 Hz CFO, 64 bytes each way and a 180-second horizon.
Protocol events, burst counts, delivered/ACKed bytes, outcomes and channel
timing must match. CPU and wall times are excluded from that comparison.
No full-platform, radio or live-deadline qualification is implied.

Recorded validation: both harness suites passed, and all four empty-plan
comparisons matched. Includes, layering and whitespace checks passed; the
production Python/native core trees have no differences from local upstream
`master`. [Correctness output](validation/controlled-loss-2026-11-19/correctness.log),
[parity summary](validation/controlled-loss-2026-11-19/default-parity.json),
[full paired reports](validation/controlled-loss-2026-11-19/default-parity-raw.zip)
and [tested source hashes](validation/controlled-loss-2026-11-19/source-sha256.json)
are retained.
