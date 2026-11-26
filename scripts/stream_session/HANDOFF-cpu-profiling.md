# Handoff: CPU profiling with the stream_session harness

2026-11-26. Provisional throughout: 8 seeds per cell, 64 B transfers, one machine (Apple M1, macOS ARM64).

## Repository state

| Item | Value |
|---|---|
| Repository | `finitor/Data2G` (fork only: this harness never goes upstream) |
| Branch | `feature/stream-session-cells`, worktree `.worktrees/stream-session-cells` |
| Base | fork `master` at `fd514ec` (merge base) |
| Integration target | stays on this branch; not proposed to upstream |
| Current commit | `83b1525` (an Aether HF endpoint). The fork has `0d36296` and earlier; `83b1525` isn't pushed |
| Uncommitted | this file |
| Mercury adapter | `../mercury` (Rhizomatica's repo, local clone), branch `study/stream-session-adapter`: `efdaa98`, `39ce153`. Not pushed anywhere |
| Local rules | `AGENTS.local.md` dated 2026-11-25 (lane cap of 3, no hosted CI, nothing upstream unless asked) |

Commits on this branch that the profiling work added:

| Commit | What it adds |
|---|---|
| `fd73795` | PEP-fair SNR through `DATA2G_PEP_REF_DB` |
| `792ee54` | Xara endpoint over the same pipe protocol |
| `8f24865`, `e5975a6` | PEP-5 AWGN ladder (`--points awgn-pep5`): clean, +10, +0, −6, −10, −12, −14, −16, −19, −20, −21 |
| `ade2eda` | Native Data2G endpoint (`--modems data2g-native`) and per-station CPU |
| `9d32db4` | Ion endpoint; per-block CPU from any adapter (`<MODEM>_CPU`) |
| `0d36296` | Mercury endpoint through its bridge script |
| `83b1525` | Aether HF endpoint |

## Tooling

### Harness

Files are in `scripts/stream_session/`; `README.md` documents them all.

- **`run_sessions.py`** runs trials, one JSON row and one log per trial.
  - Modems: `data2g`, `data2g-native`, `xara`, `ion`, `aether`, `mercury`.
  - `--points` takes cell names or set names (`SETS`); unknown names are an error.
  - Under `DATA2G_PEP_REF_DB`, the harness also sets `<MODEM>_PEAK_FULL_SCALE`, so patched adapters send each transmission at sample peak 1.0.
- **`endpoint_data2g_native.py`** runs both stations as `native.engine.Engine`, the C++ engine that `data2g-host` runs.
  - Stepped synchronously, with `native.set_threads(1)`.
  - Uses the app's native `audio.Decimator` and `Interpolator` for 48 ↔ 8 kHz.
  - PEP-fair only.
  - `STREAM_SESSION_RECORD=<dir>` writes each engine's own recording (`events.jsonl`).

### CPU metric

- **What's recorded.** Each endpoint writes one row of five uint64 nanosecond counts per 10 ms block:
  - each station's modem thread time;
  - each station's rate-conversion time (Data2G only);
  - the whole process.

  It goes to `STREAM_SESSION_CPU` (native Data2G) or `<MODEM>_CPU` (adapters).
- **What's reported.** `run_sessions.cpu_metrics` puts a `cpu` entry in each row, per station: `avg` over the session, plus `peak` and `p95` over 1 s sliding windows. Units are cores at real time.
- **Reading it.** Report the busier station. A process-to-stations ratio near 1 confirms nothing ran on uncounted threads: about 1.05 for Data2G and Xara, 1.006 for Aether.
- **Measure one modem at a time** (two lanes), so all modems see the same machine load.

### Comparison adapters

These are study-patched copies, outside the repository, under `local-evidence/`:

| Modem | Source and patch | What the patch does |
|---|---|---|
| Xara | `xara-pep5-20261126/xara-src`, `xara-study.patch` | `XARA_PEAK_FULL_SCALE` in `scheduler.rs` (which already normalises to mean 0.01); cap 0 → Hz500; `XARA_CPU`. Qualified bit-identical with the switch off (`qualify.py`) |
| Aether HF | `aether-pep5-20261126/aether-src/core`, `aether-study.patch` | `AETHER_PEAK_FULL_SCALE` (gain 1/peak at keying, `station.rs`); cap 0 → NARROW_500; `AETHER_CPU`; `unsafe_code` forbid → deny |
| Ion | `ion-pep5-20261126/ion-src`, `ion-study.patch` | `ION_PEAK_FULL_SCALE`, `ION_CPU`. Built, never run |
| Mercury v2 | `../mercury`, branch `study/stream-session-adapter` | Bridge `tests/stream_session/stream_session_bridge.py` that starts two `mercury -x sock` stations. TNC over TCP, port retry, `proc_pid_rusage` CPU. Build: `LDFLAGS="-framework AppKit" make HAVE_HAMLIB=0 HAVE_HIDAPI=0` |

### Profiling

- **Sampling.** macOS `sample` on the endpoint process, 1 ms, for a whole session: `sample $PID 30 1 -mayDie -file why/prof3/<modem>-<cell>.txt`.
- **Attribution.**
  - `why/prof3/breakdown.py` gives an exclusive breakdown. Each sample is counted once, under the first category rule that matches its stack, and only station work is counted.
  - `why/prof3/components.py` gives finer, per-modem components on the same rules.
  - Shares are multiplied by the session's measured CPU from the harness rows (`why/prof3/s.jsonl`) to give ms of CPU per second of audio.
- **Candidate counting** (`why/count/`): the Python reference Receiver wrapped around native search functions, counting search rounds, outcomes and cost per round.

## Where the data is

Everything below is under `local-evidence/`, which is excluded from Git and exists only on this machine. Copy it explicitly if it needs to move.

| Path | Contents |
|---|---|
| `native-cpu-20261126/env.sh` | Every environment variable for the runs: pins, adapter binaries, the interpreter |
| `native-cpu-20261126/run_all.sh`, `run_aether.sh`, `run_mercury.sh` | Full runs: one modem at a time, two lanes each (`cells-a.txt`, `cells-b.txt`) |
| `native-cpu-20261126/resume.py` | Reruns the (cell, seed) pairs missing from a lane's jsonl |
| `native-cpu-20261126/full/<modem>-{a,b}.jsonl` | Raw rows: 408 per modem (51 cells × 8 seeds) for data2g-native, xara, aether and mercury. Per-trial logs and CPU files are in the matching directories |
| `native-cpu-20261126/summarize_full.py`, `cpu_report_tables.py` | Build the summary and report tables from the rows |
| `native-cpu-20261126/SUMMARY-full.md` | Outcomes and CPU per cell for Data2G, Xara and Aether, with an analysis of each. `SUMMARY-preliminary.md` is the early one-lane run: ignore its 0/0 rows |
| `native-cpu-20261126/CPU-REPORT-data2g-native-43b2968-xara-aether.md` | **Start here for findings.** The CPU report: overall, by condition, time spread, where the time goes, strategies, Pi 3B+ estimate, savings, limits |
| `native-cpu-20261126/why/NOTES.md` | Working notes: why Data2G peaks, candidate counts, why Xara and Aether are flat, the exclusive breakdown |
| `native-cpu-20261126/why/prof3/` | The three-way profiles (seed 125001, awgn-12 and hilat-m+10), the attribution scripts, and their harness rows and per-trial files (`s/`) |
| `native-cpu-20261126/why/sample-*.txt`, `xsample-*`, `asample-*`, `rec-*` | Earlier inclusive profiles, and engine recordings of single sessions |
| `master-43b2968-pep5-20261125/` | Master baseline: PEP-5 sessions and the MER on/off comparison |
| `master-43b2968-pep5-20261125/cliff/` | The AWGN −8 → −12 cliff sweep (`sweep.py`, `NOTES.md`) |
| `xara-pep5-20261126/` | Xara against master on outcomes (`COMPARE-master-43b2968-vs-xara-pep5.md`) and its qualification fixtures (`qualification/`) |

**Fixtures for repeating a run:**
- **Pins:** the modem from worktree `.worktrees/arm-master-43b2968`; the channel pinned to `.worktrees/combined-base` (`STREAM_SESSION_CHANNEL`).
- **Trials:** seeds 125000–125007, 64 B payloads (fixed by seed), PEP-5 (`DATA2G_PEP_REF_DB=5`).
- **Interpreter:** `/Users/tvetter/work/hybrid-hf/.venv/bin/python`.
- **Determinism:** Data2G, Xara and Aether sessions repeat exactly for a given seed and pins. Mercury's don't.

## Findings

All figures are % of one M1 core for the busier station: the median over sessions, with the worst session in brackets. Busiest second means the busiest 1 s window. See the CPU report for the tables.

| Modem | Average | Busiest second | CPU per completed exchange | Complete |
|---|---:|---:|---:|---:|
| Data2G (native, master `43b2968`) | 1.5% | 8.5% (26.5%) | 0.69 s | 391/408; floor −20 dB (5/8), a few losses on carriers, qrm-noise, hilat+10 |
| Xara | 0.6% | 1.5% (3.1%) | 0.26 s | 388/408; floor −19 dB (5/8), 7/8 on qrm-carriers |
| Aether HF | 3.8% | 8.2% (15.9%) | 2.55 s | 343/408; floor −18 dB (5/8); fails hilat, hilat+10 and the steady carriers |

- **Data2G: a low average, but peaks that grow with the channel.**
  - **How much:** the busiest second goes from about 5% (clean) to 15–20% under fast fading, carriers, interference and AWGN at −18 dB and below.
  - **Cause:** the receiver's acquisition search, run every 0.25 s while unlocked, which is mostly serial (the pool covers about 9–13%).
  - **Under fading:** about twice the search rounds, each about twice the cost, and almost all of them find nothing. The header-copy search grows about 6× and the OFDM header search about 8×; decoding doesn't grow.
  - **The DD wall-clock budget never bound:** the longest step was 198 ms.
- **Xara: low and flat.** The ARQ tells its receiver which modes to expect, it narrows its search once linked, and it processes only new samples every block. About 60% of its CPU is the 48 → 3 kHz front end, which runs twice because the busy detector has its own copy (19–22%).
- **Aether: high and flat.** A PMF-FFT matched-filter bank tests every timing position, every carrier-offset bin and both preamble sequences, all the time. That's about 50% of its CPU, independent of the channel. Single-threaded, in 60 ms chunks.
- **Shared finding:** decoding is cheap for all three (at most 1.5 ms/s). Acquisition strategy decides CPU.
- **Pi 3B+ estimate (an unmeasured 11× factor):**
  - Xara fits easily.
  - Aether holds about 400 ms/s and comes near a full core in its busy seconds.
  - Data2G's hardest seconds need about 1,500–2,100 ms/s of mostly serial work, so it would fall behind.
- **Mercury v2:** 249/408 complete, fails every carrier cell, non-deterministic. Left out of the tables at the maintainer's request; its rows are in `full/mercury-*`.
- **AWGN cliff on master (−8 → −12 dB):** the first CONNECT (qpsk-r1/5) stops decoding at −11. Recovery then costs about 16 s (a reply timeout, a retry wait, and CONNECT in fsk16r25), and the slower acks add about 7 s more.
- **SNR convention:** the failure floor moving from about −15 to below −18 is the PEP-5 convention, not a modem change. Below about −10 dB sessions run in constant-envelope FSK, which PEP-5 credits with about 5 dB.
- **Scattered pilots (upstream branch, from its commit messages, not measured here):**
  - Wouldn't ease Data2G's CPU. Listening costs about 3× the pilot row even after streaming, and the per-burst channel estimate is far heavier.
  - Its streamed CombStream copy search (each start computed once as audio arrives) is the model for fixing master's search.

## Next steps

1. **Measure a real Pi factor.** Time one session per modem on a Pi 3B+ (and a Pi 4) to replace the 11× estimate.
2. **Run Data2G with the shipped threading.** That's the decode worker plus the 4-thread pool, as `data2g-host` runs it. Only then will its busiest seconds be measured rather than inferred from the profile.
3. **Prototype Data2G search savings on a fork feature branch**, and measure each with this harness:
   - search only for the expected modes once linked;
   - stream the header and copy searches so each candidate start is computed once (as CombStream does);
   - cap or spread the work per 0.25 s step;
   - reject false candidates before the full header search.
4. **Measure scattered pilots** once the maintainer says the branch is ready (don't build it before then).
   - Point `STREAM_SESSION_MODEM` at a pinned checkout and set `DATA2G_PILOTS=mix`.
   - Same cells, seeds and channel pin; profile awgn-12 and hilat-m+10 as in `why/prof3/`.
5. **Widen the evidence:**
   - more seeds per cell;
   - 1024 B transfers (seeds from 127000);
   - profiles of the busiest seconds themselves, not only session averages.
6. **Optional comparisons:**
   - Ion is built and patched but was never run (dropped as an outlier).
   - Mercury could be rerun if its non-determinism is acceptable.
7. **Housekeeping on this branch:**
   - The README's Limits section still says the native Engine isn't exercised, and that the DD decoder has no wall-clock budget. Both are stale now that `data2g-native` exists.
   - Push `83b1525` (and this file) to `origin` when the maintainer approves.
   - The Mercury branch stays local unless asked.

## Not covered

- **Platforms:** only macOS ARM64. No Android, Linux or Pi runs.
- **Runtime:** no radio, ALC, AGC or clipping, and no real-time deadlines (sessions are stepped, not clocked).
- **Breakdowns:** the per-component breakdowns come from two cells and one seed.
