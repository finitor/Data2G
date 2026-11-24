# Streaming two-station sessions

A session harness on one sample clock: two live Data2G Engines exchange
audio through a continuous channel, 10 ms at a time, with real receiver
carrier sense and real turnaround timing. It complements
`scripts/phy_session.py` (an event loop: bursts are modulated and decoded
one at a time) by exercising what only a live audio path shows: busy
detection, CW ID sense, timers running against air time.

| File | Role |
|---|---|
| `run_sessions.py` | Runs trials: channel points, seeds, payload size; one JSON row and one log per trial. |
| `endpoint_data2g.py` | Both stations in one process: Python Engine, ARQ and policy over native DSP. |
| `stream_channel.py` | `phy_session.ContinuousChannel`'s taps as a streaming 48 kHz channel, plus noise and an optional interfering carrier. |
| `validate_channel.py` | Physical checks of the channel: signal against the analytic delayed tone, noise variance, carrier level, determinism. |

## Running

The native module must be built in the modem checkout (`tools/build_native.sh`).

```sh
export DATA2G_PROFILE=hf
python scripts/stream_session/validate_channel.py
python scripts/stream_session/run_sessions.py --points carrier,hilat --trials 8 --seed 125000 --directory /path/to/out/sessions
```

- `STREAM_SESSION_MODEM`: the Data2G checkout the stations run (default: this one).
- `STREAM_SESSION_CHANNEL`: the Data2G checkout the channel generator comes from (default: this one). Pin it to one revision to compare modem revisions on identical channels.
- `STREAM_SESSION_LOG=1`: the modem's own log lines, and each station's receiver, CW-sense and timer state whenever it changes, in the trial's log.

## Channel points

Two equal-power Rayleigh paths with the stated delay and Gaussian Doppler
spread (the generator's two-sigma convention), continuous across bursts and
reciprocal; independent continuous noise at each receiver; SNR in 2500 Hz
against a mean transmitted power of 0.01; +4.5 Hz CFO each way.

| Point | Doppler | Delay | SNR | Carrier |
|---|---:|---:|---:|---|
| `clean` | – | – | +20 dB | – |
| `awgn-12`, `-14`, `-15`, `-16` | – | – | −12 to −16 dB | – |
| `poor` | 1 Hz | 2 ms | −8 dB | – |
| `nvis` | 1 Hz | 7 ms | −8 dB | – |
| `flutter` | 10 Hz | 7 ms | 0 dB | – |
| `hilat` | 30 Hz | 7 ms | 0 dB | – |
| `carrier` | 1 Hz | 2 ms | −6 dB | steady 1573.4 Hz tone, +12 dB over the noise in 50 Hz |
| `carrier-fade1`, `carrier-fade10` | 1 Hz | 2 ms | −6 dB | the same tone, Rayleigh fading at 1 or 10 Hz, +12 dB mean |

## Accounting

The caller dials at 0.5 s. Each station queues its seeded random message
when it reports CONNECTED. `complete` needs both exact messages delivered
and both sender queues drained by 180 s; times include connection,
turnarounds, retries and acknowledgements. Failures stay in the rows with
their partial delivery. Disconnect is observed for up to 60 s more and not
counted. Wrong delivered bytes abort the trial.

## Limits

- Each transmitted burst is rescaled to a mean power of 0.01 (an equal mean power comparison, not equal PEP).
- The decision-directed decoder has no wall-clock budget, so real-time decoder deadlines are not modelled.
- No AGC, clipping, radio passband, sample-clock error or independent forward/reverse fading.
- Python Engine, ARQ and policy with native DSP: the native Engine and host are not exercised.
- Trials are deterministic for a given seed, channel checkout, modem checkout and native build.
