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
from stream_channel import StreamingChannel, BLOCK, FS

HERE = Path(__file__).resolve().parent
# (name, Doppler spread Hz, delay ms, SNR dB in 2500 Hz, carrier: False, True (steady) or its own Doppler spread Hz)
POINTS = [
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
]


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
    name, dop, delay, snr, car = point
    stem = f"{modem}-{name}-{seed}"
    payload = [directory/f"{stem}-{i}.bin" for i in range(2)]
    for i, path in enumerate(payload):
        path.write_bytes(np.random.default_rng(np.random.SeedSequence([seed, 1, i])).bytes(nbytes))
    assert modem == "data2g", modem  # the one endpoint here; another speaks the same pipe protocol
    args = [sys.executable, str(HERE/"endpoint_data2g.py")]
    logpath = directory/f"{stem}.log"
    ch = StreamingChannel(dop, delay, snr, seed, car)
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
        proc = subprocess.Popen(args+[str(seed), *map(str, payload)], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=log)
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
    row = dict(modem=modem, point=point, seed=seed, nbytes=nbytes,
               connected=all(c is not None for c in connection), connected_at=connection,
               delivered=status[2:4], delivered_at=delivered_at, acknowledged_at=acknowledged_at,
               complete=acknowledged_at is not None, close_confirmed=bool(close_at is not None and status[6]),
               close_s=None if close_at is None else samples/FS-close_at, elapsed=samples/FS,
               airtime=airtime, energy=energy, status=status, events=events,
               wall_s=time.monotonic()-wall, log=logpath.name)
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
    with (a.directory.parent/(a.directory.name+".jsonl")).open("a") as f:
        for point in POINTS:
            if point[0] not in a.points.split(","):
                continue
            for seed in range(a.seed, a.seed+a.trials):
                for modem in a.modems.split(","):
                    row = run(modem, point, seed, a.directory, horizon=a.horizon, nbytes=a.bytes)
                    f.write(json.dumps(row)+"\n")
                    f.flush()
                    print(json.dumps({k: row[k] for k in ["modem", "point", "seed", "complete", "acknowledged_at", "delivered", "wall_s"]}), flush=True)


if __name__ == "__main__":
    main()
