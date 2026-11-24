"""Robust-start study driver (issue 285 follow-up): arms off / on / gate, with or without the first CONNECT lost.

Stations: this checkout (Python switch DATA2G_ROBUST_START; native DSP built in native/build/python).
Harness: scripts/stream_session. STREAM_SESSION_CHANNEL may pin the channel generator to another checkout
(scripts/stream_session/README.md); rows go under ROBUST_START_OUT (default ./robust-start-results).

Condition "lost": the caller's audio is blanked on its way to the callee until LOST_UNTIL_S, so the first
CONNECT (qpsk-r1/5, 0.5-3.3 s) is not heard whatever the channel, and the link is made by a robust retry.
This stands for a first try lost to momentary QRM or to a callee that was scanning elsewhere.
"""
import os
for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "DATA2G_THREADS"):
    os.environ[k] = "1"
os.environ["DATA2G_PROFILE"] = "hf"
import argparse
import json
import sys
from pathlib import Path
import numpy as np

MODEM = Path(os.environ.get("STUDY_MODEM", Path(__file__).resolve().parents[2]))
HERE = Path(os.environ.get("ROBUST_START_OUT", "robust-start-results")).resolve()
sys.path.insert(0, str(MODEM))
os.environ["STREAM_SESSION_MODEM"] = str(MODEM)
os.environ["STREAM_SESSION_LOG"] = "1"  # the modem's log lines: the connect frame's reading and the decision
LOST_UNTIL_S = 4.0
# Bursty QRM conditions (data2g.interference, rendered at 8 kHz for each receiver and raised to the
# channel's 48 kHz). Levels are over the noise floor in the source's own band, so they do not move
# with the cell's SNR. Both sources sit on 1500 Hz, 500 Hz wide: over the robust modes' tones and
# the middle fifth of the OFDM band.
#   qrm-first  one episode of band noise, 0 to LOST_UNTIL_S, at the callee only: the first CONNECT
#              goes out under it; nothing afterwards
#   qrm-noise  band noise in episodes of mean 3 s, on 30% of the time, at both receivers, all session
#   qrm-fsk    an FSK-like hopper (another data station), episodes of mean 5 s, on 30% of the time
QRM_INR_DB = 20.0
QRM = {"qrm-first": ("noise", None), "qrm-noise": ("noise", (3.0, 0.3)), "qrm-fsk": ("fsk", (5.0, 0.3))}
# (name, Doppler spread Hz, delay ms, SNR dB in 2500 Hz, carrier)
POINTS = [
    ("awgn+20", 0, 0, 20, False), ("awgn+5", 0, 0, 5, False), ("awgn+0", 0, 0, 0, False), ("awgn-4", 0, 0, -4, False),
    ("awgn-8", 0, 0, -8, False), ("awgn-12", 0, 0, -12, False), ("awgn-14", 0, 0, -14, False),
    ("mpp+2", 1, 2, 2, False), ("mpp-2", 1, 2, -2, False), ("mpp-6", 1, 2, -6, False), ("mpp-8", 1, 2, -8, False),
    ("mpp-10", 1, 2, -10, False), ("nvis-8", 1, 7, -8, False), ("nvis-10", 1, 7, -10, False),
    ("flutter+0", 10, 7, 0, False), ("hilat+0", 30, 7, 0, False),
]


def rows(p):
    return [json.loads(s) for s in p.read_text().splitlines() if s] if p.exists() else []


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--arm", required=True, help="off | on | gate<snr dB>[s<spread Hz>] | caller... | both..., e.g. caller-6s6; a trailing m adds the "
                   "near-tone spread check (Python measure), a trailing p the Python measure alone")
    p.add_argument("--cond", choices=["normal", "lost", *QRM], required=True)
    p.add_argument("--points", default=None)
    p.add_argument("--seed", type=int, default=125000)
    p.add_argument("--trials", type=int, default=8)
    p.add_argument("--shard", type=int, default=0)
    p.add_argument("--shards", type=int, default=1)
    a = p.parse_args()
    if a.arm.endswith("m"):  # the Python cpm.measure with the near-tone spread check (cpm.SPREAD_NEAR), e.g. caller-6s6m
        os.environ.update(DATA2G_SPREAD_NEAR="1", DATA2G_PY_MEASURE="1")
        a.arm_base = a.arm[:-1]
    elif a.arm.endswith("p"):  # the Python cpm.measure as it is: the control for the m arms, e.g. offp
        os.environ["DATA2G_PY_MEASURE"] = "1"
        a.arm_base = a.arm[:-1]
    else:
        a.arm_base = a.arm
    if a.arm.startswith(("gate", "caller", "both")):
        kind = next(k for k in ("gate", "caller", "both") if a.arm.startswith(k))
        snr, _, spread = a.arm_base[len(kind):].partition("s")
        os.environ.update(DATA2G_ROBUST_START=kind, DATA2G_ROBUST_START_SNR_DB=snr)
        if spread:
            os.environ["DATA2G_ROBUST_START_SPREAD_HZ"] = spread
    else:
        assert a.arm_base in ("off", "on")
        os.environ["DATA2G_ROBUST_START"] = a.arm_base
    sys.path.insert(0, str(MODEM/"scripts/stream_session"))
    import run_sessions as RS
    if a.cond == "lost":
        class Lost(RS.StreamingChannel):
            def process(self, outputs):
                if self.n < LOST_UNTIL_S*RS.FS:
                    outputs = [np.zeros_like(outputs[0]), outputs[1]]
                return super().process(outputs)
        RS.StreamingChannel = Lost
    if a.cond in QRM:
        from scipy import signal
        from data2g import interference as I
        kind, timing = QRM[a.cond]

        class Disturbed(RS.StreamingChannel):
            def __init__(self, dop, delay_ms, snr, seed, carrier=False, **kw):
                super().__init__(dop, delay_ms, snr, seed, carrier, **kw)
                horizon = 250.0
                sigma8 = self.sigma*np.sqrt((I.FS/2)/(RS.FS/2))  # the same floor density at 8 kHz
                self.qrm = []
                for dest in range(2):
                    on_s, duty = timing or (LOST_UNTIL_S, 0.5)
                    it = I.Interference(I.Spec(qrm=(I.Qrm(kind, 1500.0, 500.0, QRM_INR_DB, on_s, duty),)),
                                        seed*10+7+dest, horizon)
                    if timing is None:  # one fixed episode at the callee (station 1), none at the caller
                        n = int(LOST_UNTIL_S*I.FS) if dest == 1 else 0
                        it._episodes = [(np.array([0], dtype=np.int64), np.array([n], dtype=np.int64))]
                    y = it.render(0.0, int(horizon*I.FS), sigma8)
                    self.qrm.append(signal.resample_poly(y, RS.FS//I.FS, 1, window=("kaiser", 8.6)))

            def process(self, outputs):
                k, n = self.n, len(outputs[0])
                heard = super().process(outputs)  # [what station 0 hears, what station 1 hears]
                return [h+self.qrm[dest][k:k+n] for dest, h in enumerate(heard)]
        RS.StreamingChannel = Disturbed
    names = a.points.split(",") if a.points else [q[0] for q in POINTS]
    by = {q[0]: q for q in POINTS}
    root = HERE/f"{a.arm}-{a.cond}"
    root.mkdir(parents=True, exist_ok=True)
    dest = root/(f"sessions-shard-{a.shard}.jsonl" if a.shards > 1 else "sessions.jsonl")
    seen = {(r["point"][0], r["seed"]) for r in rows(dest)}
    todo = [(n, s) for n in names for s in range(a.seed, a.seed+a.trials)]
    for k, (name, seed) in enumerate(todo):
        if k % a.shards != a.shard or (name, seed) in seen:
            continue
        r = RS.run("data2g", by[name], seed, root/"sessions")
        r = dict(json.loads(json.dumps(r)), arm=a.arm, cond=a.cond)
        with dest.open("a") as f:
            f.write(json.dumps(r)+"\n")
        print(json.dumps({k: r[k] for k in ("arm", "cond", "point", "seed", "complete", "connected_at", "acknowledged_at", "wall_s")}), flush=True)


if __name__ == "__main__":
    main()
