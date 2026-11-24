# Robust start with a gate: study scripts (issue 285 follow-up)

Experiment branch, not a proposed change. Python reference only: the native
ARQ is not updated, there are no tests for the switches, and the base is not
upstream `master` alone (see Base).

## What is measured

Whether a session whose CONNECT got through only on a robust retry should
start at the top of the escalation floor ("robust start"), and whether a
gate on the connect frame's own readings avoids the cost when the first try
was lost for a reason unrelated to the path (QRM, a scanning callee).

`DATA2G_ROBUST_START` (read in `data2g/arq/session.py`):

| Value | Behaviour |
|---|---|
| `off` | As upstream: the session starts at the bottom of the floor. |
| `on` | Always robust after a retry-made connect (`feature/robust-start`). |
| `gate` | Each station decides from the frame it received: not robust if `snr_est >= DATA2G_ROBUST_START_SNR_DB` and `spread_est < DATA2G_ROBUST_START_SPREAD_HZ`. |
| `caller` | The caller gates on its CONNECT_ACK; the callee follows the mode of the caller's first burst. No wire change. |
| `both` | As `caller`, with the callee's reading in two spare bits of the CONNECT_ACK cap byte (a wire change; experiment only). Robust if either side read weak SNR or both read fast spread. |

`DATA2G_SPREAD_NEAR=1` (`data2g/cpm.py`): before `cpm.spread` reports
`SPREAD_MAX_HZ` for lack of a fit, the correlation between symbols 1 to 3
apart whose winning tones are at most one apart; if significant, the fading
is slow and the spread is reported unmeasured. The sessions read native
measurements, so `DATA2G_PY_MEASURE=1` (`scripts/stream_session/endpoint_data2g.py`)
routes CPM bursts through the Python `phy.measure`; with the check off that
path reproduced the native rows on 128 of 128 sessions.

## Base

`study/combined-fixes`: upstream `95c94b1` plus `fix/cwsense-steady-carrier`
(#302), `fix/connect-retry-fast-fading` (#304), `test/cwsense-fading-carrier`
and `feature/stream-session-harness`. The connect-retry fix sets which robust
modes the retries use, so these numbers are not upstream `master`'s.

## Running

Build the native module (`tools/build_native.sh`, HF profile), then:

```sh
export DATA2G_PROFILE=hf ROBUST_START_OUT=/path/to/out
python scripts/robust_start_study/run_gate.py --arm off        --cond lost
python scripts/robust_start_study/run_gate.py --arm on         --cond lost
python scripts/robust_start_study/run_gate.py --arm gate-6s6   --cond lost
python scripts/robust_start_study/run_gate.py --arm caller-6s6 --cond lost
python scripts/robust_start_study/run_gate.py --arm both-6s6   --cond lost
python scripts/robust_start_study/run_gate.py --arm caller-6s6m --cond lost   # with the spread check
python scripts/robust_start_study/compare.py
python scripts/robust_start_study/spread_probe.py    # the estimator offline, no sessions
```

- Arms: `gate-6s6` is SNR bar −6 dB, spread bar 6 Hz. A trailing `m` adds the spread check, a trailing `p` the Python measure alone (the control).
- Conditions: `normal`; `lost` (the caller's audio is blanked until 4.0 s, so the first CONNECT is never heard); `qrm-first` (band noise +20 dB over the floor in 500 Hz at 1500 Hz, at the callee, over the first CONNECT only); `qrm-noise` and `qrm-fsk` (the same level in Poisson episodes, 30% duty, at both receivers all session).
- `--seed` (default 125000), `--trials` (8), `--points`, `--shard/--shards`. Sessions are deterministic for a seed, checkout and native build. `compare.py` expects every arm above (and `offm`, `offp` in `normal`) to have been run.
- 64 bytes each way, 180 s limit; an unfinished session counts as 179.5 s in the means.

## Results (2026-11-24, macOS ARM64, simulation only)

Change in mean session time against `off`, seconds. First try lost: 16 seeds
(125000–125007, 128000–128007); normal: 8 seeds.

| Channel | Condition | on | caller-6s6 | both-6s6 | caller-6s6m |
|---|---|---:|---:|---:|---:|
| AWGN +20 to 0 dB | lost | +7.0 to +8.3 | 0.0 | 0.0 | 0.0 |
| AWGN −4 dB | lost | +16.0 | 0.0 | 0.0 | 0.0 |
| 2 ms / 1 Hz, +2 dB | lost | +8.7 | +1.8 | 0.0 | 0.0 |
| 2 ms / 1 Hz, −2 dB | lost | +8.7 | +0.8 | 0.0 | 0.0 |
| 2 ms / 1 Hz, −6 dB | lost | +0.6 | +1.3 | +1.0 | +3.5 |
| AWGN −8 dB | lost | +5.7 | +5.7 | +5.7 | +5.7 |
| AWGN −12, −14 dB | normal | −3.7, −3.8 | same | same | same |
| 2 ms / 1 Hz, −8 dB | normal | −30.5 | −30.5 | −30.5 | −30.5 |
| 2 ms / 1 Hz, −10 dB | normal | −42.3 | −42.3 | −33.8 | −42.6 |
| 7 ms / 1 Hz, −8 dB | normal | −20.7 | −20.7 | −21.0 | −29.9 |
| 7 ms / 1 Hz, −10 dB | normal | −25.5 | −25.5 | −41.3 | −31.0 |
| 7 ms / 10 Hz, 0 dB | normal | −31.7 | −31.7 | −28.8 | −26.8 |
| 7 ms / 30 Hz, 0 dB | normal | −17.0 | −17.0 | −17.2 | −17.8 |

With `gate-6s6` the two stations decided differently in 31 sessions; four
were slower than both `off` and `on` and one failed where both completed.
`caller-6s6` on those 31: each equals `off` or `on` exactly.

Spread estimator offline (`spread_probe.py`, control-only `fsk16r25-r1/2`,
200 seeds): reads 12.0 Hz in 0 on AWGN and on flat 1 Hz fading, 29 at
2 ms / 1 Hz +2 dB, 68 at 7 ms / 1 Hz −8 dB, 152 at 2 ms / 0.1 Hz +2 dB.

Limits: one platform, simulation, 8 to 16 seeds per cell; descriptive, not
thresholds. The cutoff was chosen on the first seed set and rerun on the
second.
