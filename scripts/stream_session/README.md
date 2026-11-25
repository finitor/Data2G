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
reciprocal; independent continuous noise at each receiver; +4.5 Hz CFO each
way unless a point says otherwise.

SNR is in 2500 Hz against the bursts' mean power: every burst is sent at a
mean power of 0.01, so this is `hfchannel.awgn`'s definition, the one the
test suite uses. It is not the PEP-fair convention that upstream's AGENTS.md (#319) section 11
asks studies on `ContinuousChannel` to use (`DATA2G_PEP_REF_DB=5`: noise
against each burst's peak less 5 dB). Data2G's clipped bursts sit well under
5 dB peak-to-average (`phy.peak_db`): OFDM 2.4-2.9 dB (w48 about 4), CPM/FSK
about 0.1. So a PEP-5 cell of the same number is easier for every mode: 2.1-2.6
dB for OFDM, 1.0 for w48, 4.8-4.9 for CPM/FSK. Results from this harness are
not on the PEP scale and do not compare directly with loss-study cells or ladder
scores.

`run_sessions.POINTS` lists every point. The groups:

| Group | Points |
|---|---|
| The session matrix | `clean` (+20), `awgn-12` to `-16`, `poor` (1 Hz, 2 ms, −8), `nvis` (1, 7, −8), `flutter` (10, 7, 0), `hilat` (30, 7, 0), `carrier`, `carrier-fade1`, `carrier-fade10` (1, 2, −6, with the tone below), `qrm-noise` |
| The robust-start gate study's grid | `awgn+10`, `+5`, `+0`, `-4`, `-8`; `mpp+2`, `-2`, `-6`, `-10`; `nvis-10` |
| `fast-fading-integration`'s smoke cells, at this SNR | `hilat+10`, `hilat-m+10`, `hilat-m+20` (10, 3), `lowlat-d+10` (10, 6), `nvis+10`, `mpd+0` (2, 4), `mpp+0`, `mpg-4` (0.1, 0.5), `awgn-18`, `awgn-12+carrier`; 500 Hz cap: `cap500-mpd+0`, `cap500-mpp+0`, `cap500-awgn-12` |
| Interference (`data2g.interference` presets, on 1 Hz / 2 ms at +2 dB) | `imp`, `imp-long`, `qrm-fsk` (`mid`), `qrm-edge`, `qrm-carriers`, `qrm-wide` |
| Clocks and tuning | `clock-awgn-12`, `clock-poor` (sample clocks 100 ppm apart), `cfo25-poor` (25 Hz offset), `drift-poor` (+0.1 Hz/s from 4.5 Hz) |

The carriers (`carrier`, `awgn-12+carrier`): a 1573.4 Hz tone, +12 dB over
the noise in 50 Hz, as `data2g.interference`'s `Qrm("carrier")` defines a
level, generated in `stream_channel.py` with the seeds the recorded studies
used. `qrm-noise`: band noise on 1500 Hz, 500 Hz wide, +20 dB over the floor
in its band, episodes of mean 3 s on 30% of the time, at both receivers
(`run_gate.py`'s, the same seeds). The other interference points render that
module's presets the same way. Their levels are over the floor, so they do
not move with the SNR.

A point's options (its sixth element): `cap` (the session's bandwidth cap
code: 0 is 500 Hz, 2 none), and `StreamingChannel`'s `cfo`, `cfo_rate`, `ppm`
and `qrm`. With `ppm`, the faster clock's received audio is read ahead of the
samples sent, so that path starts with a propagation delay of
ppm × 240 s (24 ms at 100 ppm), which shrinks to zero; the other path's grows
from zero.

## Accounting

The caller dials at 0.5 s. Each station queues its seeded random message
when it reports CONNECTED. `complete` needs both exact messages delivered
and both sender queues drained by 180 s; times include connection,
turnarounds, retries and acknowledgements. Failures stay in the rows with
their partial delivery. Disconnect is observed for up to 60 s more and not
counted. Wrong delivered bytes abort the trial.

## Limits

- Each transmitted burst is rescaled to a mean power of 0.01 (an equal mean power comparison, not equal PEP: see Channel points).
- The decision-directed decoder has no wall-clock budget, so real-time decoder deadlines are not modelled.
- No AGC, clipping, radio passband or independent forward/reverse fading. Sample-clock error only in the clock points.
- Python Engine, ARQ and policy with native DSP: the native Engine and host are not exercised.
- Trials are deterministic for a given seed, channel checkout, modem checkout and native build.
