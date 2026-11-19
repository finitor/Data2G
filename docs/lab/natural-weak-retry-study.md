# Natural-loss weak-channel retry validation

This follow-up measures how often the candidate's later retries are reached under natural losses and what their costs are on ordinary weak channels. It follows the [conditional study](conditional-retry-study.md), uses the same existing native Lab executable and keeps the production modem and default policy unchanged.

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
