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
| `endpoint_data2g_native.py` | `--modems data2g-native`: both stations on the native C++ engine (`native.engine.Engine`, what `data2g-host` runs), stepped synchronously, with the app's native 48 ↔ 8 kHz rate conversion; PEP-fair only. Writes per-block CPU for `cpu` in each row. |
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
- `STREAM_SESSION_MERCURY`: the bridge for `--modems mercury` (`tests/stream_session/stream_session_bridge.py` on Mercury's `study/stream-session-adapter` branch), which starts two `mercury -x sock` stations from `MERCURY_BIN`. Under `DATA2G_PEP_REF_DB` it gets `MERCURY_PEAK_FULL_SCALE` and `MERCURY_CPU` like the other adapters. Mercury's sessions don't repeat exactly (its demodulator runs on its own thread).
- `STREAM_SESSION_ION`: the binary for `--modems ion`, the Ion comparison adapter, on the same terms as Xara's below (`ION_PEAK_FULL_SCALE`, `ION_CPU`). Ion has one bandwidth, so the cap argument has no effect: cap500 cells run it uncapped.
- `STREAM_SESSION_XARA`: the binary for `--modems xara`, a Xara comparison adapter speaking the same pipe protocol (seed, two payload files, cap; cap 0 selects Xara's 500 Hz bandwidth). Under `DATA2G_PEP_REF_DB` the harness sets `XARA_PEAK_FULL_SCALE=1`, which a study-patched adapter takes as every burst at sample peak 1.0; unset, it sends at mean power 0.01.
- CPU: endpoints that write per-block CPU (`data2g-native`, and a Xara adapter built with the study's patch) get a `cpu` entry in each row: each station's modem and rate-conversion thread time, the whole process's, and the load in cores at real time, averaged over the session and over its busiest 1 s window (`peak`, `p95`). Single-threaded on this machine: scale by a measured factor for other hardware.
- `STREAM_SESSION_LOG=1`: the modem's own log lines, and each station's receiver, CW-sense and timer state whenever it changes, in the trial's log.

## Channel points

Two equal-power Rayleigh paths with the stated delay and Gaussian Doppler
spread (the generator's two-sigma convention), continuous across bursts and
reciprocal; independent continuous noise at each receiver; +4.5 Hz CFO each
way unless a point says otherwise.

SNR is in 2500 Hz, on one of two scales, chosen by `DATA2G_PEP_REF_DB` (recorded in each row as
`pep_ref_db`):

- **PEP-fair, `DATA2G_PEP_REF_DB=5`** (upstream AGENTS.md (#319) section 11; use this for new
  runs): every burst keeps the engine's full-scale envelope peak, as data2g-host sends it, and the
  noise is against that peak less 5 dB, as `phy_session.floor_sigma` sets it. A burst whose
  peak-to-average is 5 dB has the cell's SNR; Data2G's sit lower (`phy.peak_db`: OFDM 2.4-2.9 dB,
  w48 about 4, CPM/FSK about 0.1), so they see 2.1-2.6, 1.0 and 4.8-4.9 dB more.
- **Mean power, unset** (runs up to 2026-11-25): every burst is rescaled to a mean power of 0.01,
  `hfchannel.awgn`'s definition, the test suite's. Not on the PEP scale: those results do not
  compare directly with loss-study cells, ladder scores or PEP-5 runs of the same cell.

`run_sessions.POINTS` lists every point, and `--points` also takes the names of the sets in `run_sessions.SETS`; unknown names are an error. The groups:

| Group | Points |
|---|---|
| The session matrix | `clean` (+20), `awgn-12` to `-16`, `poor` (1 Hz, 2 ms, −8), `nvis` (1, 7, −8), `flutter` (10, 7, 0), `hilat` (30, 7, 0), `carrier`, `carrier-fade1`, `carrier-fade10` (1, 2, −6, with the tone below), `qrm-noise` |
| The robust-start gate study's grid | `awgn+10`, `+5`, `+0`, `-4`, `-8`; `mpp+2`, `-2`, `-6`, `-10`; `nvis-10` |
| `fast-fading-integration`'s smoke cells, at this SNR | `hilat+10`, `hilat-m+10`, `hilat-m+20` (10, 3), `lowlat-d+10` (10, 6), `nvis+10`, `mpd+0` (2, 4), `mpp+0`, `mpg-4` (0.1, 0.5), `awgn-18`, `awgn-12+carrier`; 500 Hz cap: `cap500-mpd+0`, `cap500-mpp+0`, `cap500-awgn-12` |
| Interference (`data2g.interference` presets, on 1 Hz / 2 ms at +2 dB) | `imp`, `imp-long`, `qrm-fsk` (`mid`), `qrm-edge`, `qrm-carriers`, `qrm-wide` |
| The PEP-5 AWGN ladder (`--points awgn-pep5`, `run_sessions.SETS`) | `clean`, `awgn+10`, `+0`, `-6`, `-10`, `-12`, `-14`, `-16`, `-19`, `-20`, `-21`: clean to the floor, 1 dB steps at the bottom. Below about −10 dB sessions run in constant-envelope FSK, which PEP-5 makes 5 dB easier, so the failure floor sits about 5 dB lower than on the mean-power scale |
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

- Bursts are at the engine's full-scale peak (PEP-fair) or rescaled to equal mean power: see Channel points. Neither models a radio's ALC or clipper.
- The decision-directed decoder has no wall-clock budget, so real-time decoder deadlines are not modelled.
- No AGC, clipping, radio passband or independent forward/reverse fading. Sample-clock error only in the clock points.
- Python Engine, ARQ and policy with native DSP: the native Engine and host are not exercised.
- Trials are deterministic for a given seed, channel checkout, modem checkout and native build.
