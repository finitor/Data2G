"""Synchronous live audio sessions over the existing continuous fading taps.

Two Data2G stations (endpoint_data2g.py, one process) exchange `--bytes`
random bytes each way through StreamingChannel, block by block on one
sample clock. A trial completes when both exact messages are delivered and
both sender queues drain within the horizon. One JSON row per trial, with
its log and payloads, under --directory.
"""
import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "DATA2G_THREADS", "ION_THREADS"):
    os.environ[key] = "1"
import argparse
import json
import struct
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from stream_channel import StreamingChannel, BLOCK, FS, PEP_REF_DB

HERE = Path(__file__).resolve().parent
# (name, Doppler spread Hz, delay ms, SNR dB in 2500 Hz, carrier: False, True (steady) or its own Doppler
# spread Hz[, options]). SNR: mean power, or PEP-fair with DATA2G_PEP_REF_DB
# (stream_channel.py). Options:
# stream_channel.StreamingChannel's (cfo, cfo_rate, ppm, qrm) and cap, the session's bandwidth cap code
# (0: 500 Hz, 1: 1200, 2: none; default 2).
QRM_NOISE = ("noise", 1500.0, 500.0, 20.0, 3.0, 0.3)  # run_gate.py's qrm-noise: 30% of the time, mean 3 s
POINTS = [
    # the session matrix
    ("clean", 0, 0, 20, False),
    ("awgn-12", 0, 0, -12, False),
    ("awgn-14", 0, 0, -14, False),
    ("awgn-15", 0, 0, -15, False),
    ("awgn-16", 0, 0, -16, False),
    ("poor", 1, 2, -8, False),
    ("nvis", 1, 7, -8, False),
    ("flutter", 10, 7, 0, False),
    ("hilat", 30, 7, 0, False),
    ("carrier", 1, 2, -6, True),
    ("carrier-fade1", 1, 2, -6, 1.0),
    ("carrier-fade10", 1, 2, -6, 10.0),
    ("qrm-noise", 1, 2, 2, False, dict(qrm=QRM_NOISE)),
    # the robust-start gate study's grid (awgn+20 is clean, mpp-8 poor, nvis-8 nvis)
    ("awgn+10", 0, 0, 10, False),
    ("awgn+5", 0, 0, 5, False),
    ("awgn+0", 0, 0, 0, False),
    ("awgn-4", 0, 0, -4, False),
    ("awgn-8", 0, 0, -8, False),
    ("mpp+2", 1, 2, 2, False),
    ("mpp-2", 1, 2, -2, False),
    ("mpp-6", 1, 2, -6, False),
    ("mpp-10", 1, 2, -10, False),
    ("nvis-10", 1, 7, -10, False),
    # fast-fading-integration's smoke loss study (ITU-R F.1487 / hfchannel presets), at our SNR
    ("hilat+10", 30, 7, 10, False),
    ("hilat-m+10", 10, 3, 10, False),
    ("hilat-m+20", 10, 3, 20, False),
    ("lowlat-d+10", 10, 6, 10, False),
    ("nvis+10", 1, 7, 10, False),
    ("mpd+0", 2, 4, 0, False),
    ("mpp+0", 1, 2, 0, False),
    ("mpg-4", 0.1, 0.5, -4, False),
    ("awgn-18", 0, 0, -18, False),
    # the PEP-5 AWGN ladder's own steps (AWGN_PEP5 below)
    ("awgn-6", 0, 0, -6, False),
    ("awgn-10", 0, 0, -10, False),
    ("awgn-19", 0, 0, -19, False),
    ("awgn-20", 0, 0, -20, False),
    ("awgn-21", 0, 0, -21, False),
    ("awgn-12+carrier", 0, 0, -12, True),
    ("cap500-mpd+0", 2, 4, 0, False, dict(cap=0)),
    ("cap500-mpp+0", 1, 2, 0, False, dict(cap=0)),
    ("cap500-awgn-12", 0, 0, -12, False, dict(cap=0)),
    # conditions neither suite covered: data2g.interference presets on poor fading at +2 dB, as qrm-noise
    ("imp", 1, 2, 2, False, dict(qrm="imp")),
    ("imp-long", 1, 2, 2, False, dict(qrm="imp_long")),
    ("qrm-fsk", 1, 2, 2, False, dict(qrm="mid")),
    ("qrm-edge", 1, 2, 2, False, dict(qrm="edge")),
    ("qrm-carriers", 1, 2, 2, False, dict(qrm="carriers")),
    ("qrm-wide", 1, 2, 2, False, dict(qrm="qrm_wide")),
    # sample clocks 100 ppm apart; frequency offset and drift
    ("clock-awgn-12", 0, 0, -12, False, dict(ppm=100.0)),
    ("clock-poor", 1, 2, -8, False, dict(ppm=100.0)),
    ("cfo25-poor", 1, 2, -8, False, dict(cfo=25.0)),
    ("drift-poor", 1, 2, -8, False, dict(cfo_rate=0.1)),
]

# Named cell sets for --points. awgn-pep5: AWGN from clean to -21 dB in 11 cells for DATA2G_PEP_REF_DB=5. Below about
# -10 dB the sessions run in constant-envelope FSK, which PEP-5 makes 5 dB easier than the mean-power
# scale, so the floor moves from -15/-16 to -20/-21 (master 43b2968: mean-power -15/-16 and PEP-5 -20/-21
# match seed for seed). Like the mean-power ladder, it steps 1 dB around the floor. Mean-power runs keep
# the original cells.
SETS = {"awgn-pep5": ["clean", "awgn+10", "awgn+0", "awgn-6", "awgn-10", "awgn-12", "awgn-14",
                      "awgn-16", "awgn-19", "awgn-20", "awgn-21"]}


CPU_WINDOW_S = 1.0


def cpu_metrics(path, elapsed):
    """Per-station CPU from an endpoint's per-block file (endpoint_data2g_native.py, the Xara and Ion
    adapters' <MODEM>_CPU): five uint64 ns per 10 ms block, the stations' modem thread time, their rate conversion (Data2G
    only: 48 <-> 8 kHz through the app's native Decimator and Interpolator) and the whole process. A
    station's load counts its modem and rate conversion: audio in and out at 48 kHz, as Xara's process()
    takes it. Loads are in cores at real time: average over the
    session, and the busiest CPU_WINDOW_S of session time (max and 95th percentile of the sliding windows).
    None when the endpoint wrote no file (endpoint_data2g.py)."""
    if not path.exists():
        return None
    a = np.fromfile(path, dtype="<u8").reshape(-1, 5).astype(float) / 1e9
    st = a[:, 0:2] + a[:, 2:4]
    w = max(1, round(CPU_WINDOW_S * FS / BLOCK))
    c = np.vstack([np.zeros((1, 2)), np.cumsum(st, axis=0)])
    win = (c[w:] - c[:-w]) / (w * BLOCK / FS) if len(st) >= w else c[-1:] / max(elapsed, 1e-9)
    return dict(modem_s=a[:, 0:2].sum(0).round(4).tolist(), resample_s=a[:, 2:4].sum(0).round(4).tolist(),
                process_s=round(float(a[:, 4].sum()), 4), avg=(st.sum(0) / elapsed).round(5).tolist(),
                peak=win.max(0).round(4).tolist(), p95=np.percentile(win, 95, axis=0).round(4).tolist(),
                window_s=CPU_WINDOW_S)


def read_exact(pipe, n):
    parts = []
    while n:
        b = pipe.read(n)
        if not b:
            raise RuntimeError("endpoint stopped before its audio/status response")
        parts.append(b)
        n -= len(b)
    return b"".join(parts)


def run(modem, point, seed, directory, horizon=180, nbytes=64):
    directory.mkdir(parents=True, exist_ok=True)
    name, dop, delay, snr, car, *rest = point
    opts = dict(rest[0]) if rest else {}
    cap = opts.pop("cap", 2)
    stem = f"{modem}-{name}-{seed}"
    payload = [directory/f"{stem}-{i}.bin" for i in range(2)]
    for i, path in enumerate(payload):
        path.write_bytes(np.random.default_rng(np.random.SeedSequence([seed, 1, i])).bytes(nbytes))
    cpu_file = directory/f"{stem}.cpu"
    cpu_file.unlink(missing_ok=True)
    env = dict(os.environ, STREAM_SESSION_CPU=str(cpu_file))
    if modem == "data2g":
        args = [sys.executable, str(HERE/"endpoint_data2g.py")]
    elif modem == "data2g-native":
        args = [sys.executable, str(HERE/"endpoint_data2g_native.py")]
    else:
        # Another modem speaking the same pipe protocol (args: seed, two payloads, cap): the 2026-11-23
        # comparison adapters for Xara, Ion and Aether, whose binaries STREAM_SESSION_XARA, _ION and _AETHER
        # name. Under PEP-fair SNR a study-patched adapter is told to send every burst at peak 1.0
        # (<MODEM>_PEAK_FULL_SCALE); otherwise it sends at mean 0.01. It writes per-block CPU to <MODEM>_CPU.
        # Mercury: a bridge script (on the Mercury repo's study/stream-session-adapter branch) that runs two
        # `mercury -x sock` stations; STREAM_SESSION_MERCURY names it, MERCURY_BIN the binary it starts.
        assert modem in ("xara", "ion", "aether", "mercury"), modem
        exe = os.environ[f"STREAM_SESSION_{modem.upper()}"]
        args = [sys.executable, exe] if exe.endswith(".py") else [exe]
        key = f"{modem.upper()}_PEAK_FULL_SCALE"
        env.pop(key, None)
        if PEP_REF_DB is not None:
            env[key] = "1"
        env[f"{modem.upper()}_CPU"] = str(cpu_file)
    logpath = directory/f"{stem}.log"
    ch = StreamingChannel(dop, delay, snr, seed, car, horizon=horizon, **opts)
    inputs = np.zeros((2, BLOCK))
    connection = [None, None]
    delivered_at = None
    acknowledged_at = None
    close_at = None
    samples = 0
    airtime = [0.0, 0.0]
    energy = [0.0, 0.0]
    wall = time.monotonic()
    status = [0]*8
    last = None
    events = []
    with logpath.open("w") as log:
        proc = subprocess.Popen(args+[str(seed), *map(str, payload), str(cap)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=log, env=env)
        try:
            while samples/FS < (horizon if acknowledged_at is None else acknowledged_at+60):
                t = samples/FS
                cmd = 2 if samples == FS//2 else 0
                if acknowledged_at is not None and close_at is None:
                    cmd = 1
                    close_at = t
                proc.stdin.write(struct.pack("<Q", cmd)+inputs.astype("<f8").tobytes())
                proc.stdin.flush()
                raw = read_exact(proc.stdout, 2*BLOCK*8+64)
                outputs = np.frombuffer(raw[:2*BLOCK*8], dtype="<f8").reshape(2, BLOCK)
                status = list(struct.unpack("<8Q", raw[2*BLOCK*8:]))
                assert not status[7], f"wrong application bytes: {stem}"
                for i in range(2):
                    if status[i] and connection[i] is None:
                        connection[i] = t+BLOCK/FS
                    active = np.abs(outputs[i]) > 1e-10
                    airtime[i] += np.count_nonzero(active)/FS
                    energy[i] += float(outputs[i]@outputs[i])/FS
                if status != last:
                    events.append(dict(t=t+BLOCK/FS, status=status))
                    last = status
                samples += BLOCK
                if status[2:4] == [nbytes, nbytes]:
                    delivered_at = delivered_at or samples/FS
                    if status[4:6] == [0, 0] and acknowledged_at is None:
                        acknowledged_at = samples/FS
                if close_at is not None and status[6]:
                    break
                inputs = np.array(ch.process(outputs))
        finally:
            proc.stdin.close()
            proc.wait(timeout=20)
    assert proc.returncode == 0, f"endpoint exited {proc.returncode}: {logpath}"
    row = dict(modem=modem, point=point, seed=seed, nbytes=nbytes, pep_ref_db=PEP_REF_DB,
               connected=all(c is not None for c in connection), connected_at=connection,
               delivered=status[2:4], delivered_at=delivered_at, acknowledged_at=acknowledged_at,
               complete=acknowledged_at is not None, close_confirmed=bool(close_at is not None and status[6]),
               close_s=None if close_at is None else samples/FS-close_at, elapsed=samples/FS,
               airtime=airtime, energy=energy, status=status, events=events,
               wall_s=time.monotonic()-wall, log=logpath.name, cpu=cpu_metrics(cpu_file, samples/FS))
    (directory/f"{stem}.json").write_text(json.dumps(row, indent=2)+"\n")
    return row


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--modems", default="data2g")
    p.add_argument("--points", default="clean")
    p.add_argument("--trials", type=int, default=1)
    p.add_argument("--seed", type=int, default=123000)
    p.add_argument("--bytes", type=int, default=64)
    p.add_argument("--horizon", type=float, default=180, help="seconds a trial has to complete")
    p.add_argument("--directory", type=Path, required=True)
    a = p.parse_args()
    a.directory.mkdir(parents=True, exist_ok=True)
    points = [n for k in a.points.split(",") for n in SETS.get(k, [k])]
    assert set(points) <= {p[0] for p in POINTS}, sorted(set(points) - {p[0] for p in POINTS})
    with (a.directory.parent/(a.directory.name+".jsonl")).open("a") as f:
        for point in POINTS:
            if point[0] not in points:
                continue
            for seed in range(a.seed, a.seed+a.trials):
                for modem in a.modems.split(","):
                    row = run(modem, point, seed, a.directory, horizon=a.horizon, nbytes=a.bytes)
                    f.write(json.dumps(row)+"\n")
                    f.flush()
                    print(json.dumps({k: row[k] for k in ["modem", "point", "seed", "complete", "acknowledged_at", "delivered", "wall_s"]}), flush=True)


if __name__ == "__main__":
    main()
