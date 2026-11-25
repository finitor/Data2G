# fast-fading-integration under in-band tones: single-burst tests

Study scripts behind the interim findings on `fast-fading-integration` (`cd01560`) against master (`b278852`) in
the stream_session cell `qrm-carriers` (two +25 dB carriers at 800 and 2200 Hz, switching on and off). Each
compares master's pilot row with the branch's scattered pilots on the branch's own checkout, by running once
with `DATA2G_PILOTS=off` and once with `DATA2G_PILOTS=mix`.

| Script | Adapted from | What it measures |
|---|---|---|
| `single_burst_tone.py` | `scripts/sc_phy_study.py` | fixed bursts under steady tones, found and decoded offline (`receive_any`): where each burst is lost (missed, wrong header, header only, some or all codewords) |
| `tone_estimate_error.py` | `scripts/sc_diag.py` | fixed bursts with known timing and channel: the channel estimate's error per carrier, and the error the data carries against the noise the decoder is told |
| `stream_detect_tone.py` | the engine's `receiver.Receiver`, fed as `scripts/false_lock_study.py` feeds its receiver | single bursts streamed through the receiver a session runs (native DSP substituted as the stream_session endpoint does): header found, burst received, false headers |

These scripts aren't part of fast-fading-integration; they need its checkout to run against.

## Running

`STUDY_MODEM` names the checkout under test: a fast-fading-integration worktree with its native module built.
The scripts put that checkout first on `sys.path` and assert that `data2g` and the native module come from it.
SNR is PEP-5 (`DATA2G_PEP_REF_DB=5`, AGENTS.md §11).

```bash
export STUDY_MODEM=/path/to/fast-fading-integration DATA2G_PROFILE=hf DATA2G_PEP_REF_DB=5
DATA2G_PILOTS=off python scripts/studies/ffi_qrm_carriers/stream_detect_tone.py --out sd_off.csv
DATA2G_PILOTS=mix python scripts/studies/ffi_qrm_carriers/stream_detect_tone.py --out sd_mix.csv
python scripts/studies/ffi_qrm_carriers/stream_detect_tone.py --compare sd_off.csv sd_mix.csv
```

`single_burst_tone.py` works the same way. `tone_estimate_error.py` runs both layouts in one process (its jobs
switch them through `sc_diag.setup`): `--out` to measure, `--show` to print.

## Limits

- **Offline search:** `single_burst_tone.py` searches an offline window around each burst, not the streaming
  receiver.
- **Quiet receiver:** `stream_detect_tone.py` streams one burst into a quiet receiver, so session state (holds,
  busy, CW sense, a burst arriving during another) isn't covered.
- **Steady tones:** the tones here are always on; in `qrm-carriers` they switch.
