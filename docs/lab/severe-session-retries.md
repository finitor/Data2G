# Severe-channel session retries

Local investigation resumed at the user's request on 2026-11-19, against
the newer public fork's upstream v0.5.2 baseline
`dd7af8df57373aa9f652a0af03481ab71f1608b9`. The standalone Lab study is
`0060965`, descended from the existing Lab branch `8eb9cf4`. Python and
native production modem sources, generated weights and on-air formats
remain identical to v0.5.2. Hosted Actions and other-platform work remain
disabled/suspended.

## Candidate and reason

The shipped gear shifter already uses `fsk8r50-r1/3` for robust in-session
control once measured spread reaches 6 Hz. Session retries instead always
use `fsk16r25-r1/2`, before channel measurements are available. The narrower
25 Hz tone spacing is vulnerable to severe Doppler. Upstream issue
[#244](https://github.com/arodland/Data2G/issues/244) documents this, and
v0.5.2 includes both the fast control selection and a correction to the CPM
tone metric's treatment of neighboring-tone spill. Old receiver results
cannot be assumed to describe this release.

The opt-in `--alternate-retries` experiment changes only the caller's
`GearPolicy.connect_mode`: keep the initial OFDM transmission and first
robust retry, then alternate the two existing CPM modes. Zero-based tries
2 and 4 use `fsk8r50-r1/3`; odd tries retain `fsk16r25-r1/2`. This method
selects both CONNECT and DISC retries. Data recommendations, recovery-poll
selection, coding and receiver processing retain the shipped behavior.
The callee uses the shipped policy throughout, replying in the received
session-frame mode. Both retry modes fit every bandwidth cap. No channel
oracle or new peer capability is used.

This is a **Lab-only candidate**, not a production fix. A result with one
changed caller also does not qualify two changed peers, every bandwidth,
host RETRIES settings or live radio timing.

## Reproduction and accounting

```sh
cmake -S native/lab -B native/build-lab \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DDATA2G_LAB_NATIVE_SUITES=ON \
  -DDATA2G_LAB_REVISION=0060965
cmake --build native/build-lab --target data2g-lab test_lab --parallel 4
python3 native/lab/study_retries.py --binary native/build-lab/data2g-lab \
  --output runs/severe-retries-20261119/hilat \
  --channels hilat-d --snrs 0 12 --seeds 4
python3 native/lab/study_retries.py --binary native/build-lab/data2g-lab \
  --output runs/severe-retries-20261119/controls \
  --channels lowlat-d hilat-m nvis-d --snrs 12 --seeds 2
python3 native/lab/study_retries.py --binary native/build-lab/data2g-lab \
  --output runs/severe-retries-20261119/weak \
  --channels mpp awgn --snrs -8 --seeds 2
python3 native/lab/study_retries.py --binary native/build-lab/data2g-lab \
  --output runs/severe-retries-20261119/edge \
  --channels mpp awgn --snrs -12 --seeds 2
```

Run sequentially without competing builds/tests. Each arm uses 64 seeded
random bytes in each direction, a 180-second simulated horizon, 4.5 Hz CFO,
2400 Hz cap and one decoder thread. Paired arms have identical starting
channel, noise, payload and session seeds; their schedules diverge after a
different retry. Trials alternate execution order. The native core uses
its production DD wall-time budget, so fixed seeds do not promise identical
outcomes across machines or CPU contention.

SNR is relative to unit active mean transmitted power in 2500 Hz, not
matched PEP. Results require byte-exact delivery, final ACKs and both peers
closed for `complete`. Connection, delivery, ACK and disconnect failures
remain separate. Never substitute successful-only latency for reliability
or sustained application goodput. Process CPU and wall time are retained
as context, not an isolated decoder benchmark.

The driver retains full JSON and progress logs, an append-only case index,
per-arm summaries, source hashes, binary hash, revision and environment.
Gaussian fading plus white noise models delay/Doppler stress; it does not
test impulsive atmospheric noise, interference, clock drift or RF hardware.

## Severe-channel observations

On `hilat-d` (7 ms / 30 Hz), seeds 1–4:

| SNR | Shipped connected | Candidate connected | Shipped complete | Candidate complete |
|---|---:|---:|---:|---:|
| 0 dB | 1/4 | 4/4 | 0/4 | 4/4 |
| +12 dB | 3/4 | 4/4 | 3/4 | 4/4 |

At 0 dB, three shipped cases never connected; the fourth delivered and
acknowledged both directions but timed out during disconnect. Candidate
completion times were 89.1, 84.2, 158.5 and 84.6 simulated seconds.
At +12 dB, seed 4 never connected with the shipped policy. Seeds 1–3
completed in both arms; the candidate completed 6.8, 53.3 and 11.4 seconds
sooner respectively. Failed cases remain censored at the 180-second
horizon, not omitted from the completion counts.

Seed 1 includes the exploratory pilot; seeds 2–4 were added after choosing
the schedule. These eight paired short-session cases are preliminary
evidence, not a reliability estimate, sustained throughput benchmark or
general atmospheric-channel qualification. The schedule has not been
optimized, and no production behavior is changed.

At +12 dB on `lowlat-d`, `hilat-m` and `nvis-d`, and at −8 dB on MPP and
AWGN, both policies completed both seeds with identical channel timing.
At −12 dB, both AWGN seeds also completed with matching timing. Both MPP
seeds connected but failed to finish: seed 1 timed out during disconnect
after exact delivery and ACKs, and seed 2 timed out during delivery. Both
policies produced matching outcomes and timing on those failures too.

All fourteen control pairs had identical caller TX mode/timing sequences;
the changed retry was not exercised there. They check preservation of the
early path, **not** the sensitivity of the added retry. Stored *data*
thresholds favor `fsk16r25-r1/2` over `fsk8r50-r1/3` on AWGN by 2.5 dB
(−12.75 versus −10.25 dB). Those are not control-codeword thresholds, but
they reinforce the need to measure the tradeoff before changing defaults.

The whole study is 22 paired cases / 44 sessions. The next qualification
step is a larger, independently seeded SNR sweep that actually reaches
later retries on ordinary weak channels, plus other bandwidth caps, CFOs,
both peers changed, long transfers and live timing. A production change
would also require the matching Python policy and native/reference tests.
The present result justifies retaining the Lab candidate for that work.

## Saved evidence

- [Per-case index](validation/severe-retries-2026-11-19/cases.jsonl),
  including every failed case and exact invocation.
- [Cell summaries](validation/severe-retries-2026-11-19/summary.json).
  Successful-only medians are labeled and must be read with completion
  counts; do not compare them as unconditional throughput.
- [Source/binary hashes and environment](validation/severe-retries-2026-11-19/metadata.json).
- [Full raw JSON and progress logs](validation/severe-retries-2026-11-19/raw-cases.zip),
  retaining each run's original metadata, summaries and index as well.

The archived source and binary hashes were checked against the files used
for the runs. No raw cases were discarded. The production `data2g/` and
`native/core/` trees were checked against local upstream `master` and have
no differences.

## Local correctness validation

The macOS ARM64 RelWithDebInfo build succeeded. The updated `lab` suite
checks retry selection across all caps, identifies the study policy in
results, rejects combining it with a fixed policy, and completes mixed
candidate/shipped clean and AWGN sessions with exact bytes and final ACKs.
The focused `lab`, `arq`, `arq_link` and `cpm` suites passed. Includes,
layering and `git diff --check` checks passed.

The unchanged `engine` suite failed 1 of its 73 checks on both the initial
run and an isolated rerun: `worker: on time` requires less than 150 ms of
worker header lateness, while this host measured 195 ms and 255 ms. The
relative worker-versus-synchronous check passed in both runs. No deadline
assertion was relaxed or skipped. The cause of this timing failure has not
been isolated; the full engine validation is **not passing**. The study's
synchronous virtual-time outcomes do not resolve it or qualify live audio.

A subsequent user-requested rerun of the unchanged engine test measured
153 ms worker lateness against the same 150 ms limit (1,089 ms synchronous
lateness). It again failed only this one of 73 checks. The improvement from
195/255 ms is consistent with sensitivity to host conditions, but host load
was not measured, so it does not establish the cause. No repeated reruns
were used to select a passing result.

Commands and retained output:

```sh
ctest --test-dir native/build-lab \
  -R '^(lab|arq|arq_link|engine|cpm)$' --output-on-failure
ctest --test-dir native/build-lab -R '^engine$' --output-on-failure
python3 tools/check_includes.py
python3 tools/check_layering.py
git diff --check
```

- [Focused suite output](validation/severe-retries-2026-11-19/correctness.log).
- [Isolated engine rerun](validation/severe-retries-2026-11-19/engine-rerun.log).
- [User-requested subsequent rerun](validation/severe-retries-2026-11-19/engine-user-rerun.log).

No Python/native parity, full-platform, Android, training, hosted CI or
radio qualification is claimed for this Lab-only change.

## Further incremental candidates

- Trace robust-control selection during the transition from OFDM to CPM.
  OFDM's reported spread is bounded at 4 Hz (`equalizer.measure_spread`),
  below the 6 Hz fast-control threshold. That path cannot select the fast
  control mode from an OFDM spread reading alone. Establish actual session
  impact before proposing a change to the measurement/model contract.
- Evaluate recovery from the CPM floor on changing channels using the
  retrained predictor. The floor deliberately substitutes a historical
  3 Hz spread for CPM bursts even when measured spread differs. Its
  documented prior gains make simply removing it an unsupported change.
- Treat impulsive atmospheric noise as a separate paired experiment using
  the existing interference and blanker studies. These fading results do
  not qualify blanker behavior.

OFDM's existing 4 ms cyclic prefix and 144 ms pilot spacing limit what a
receiver-only increment can recover on 6–7 ms / 10–30 Hz profiles. Longer
guards or denser transmitted pilots change the waveform and require a
separately negotiated, qualified design; they are not part of this public
fork contribution.
