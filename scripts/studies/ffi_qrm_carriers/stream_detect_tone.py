"""Streamed detection of single bursts next to steady tones: pilot row against scattered pilots.

The receiver a session runs: data2g.receiver.Receiver with the engine's accept rule and CPM grids, native DSP
substituted as scripts/stream_session/endpoint_data2g.py does (native_subs; the branch keeps its study switches in
Python), fed in 20 ms blocks. Each burst goes through phy_session's ContinuousChannel with 1 s of noise before and
2 s after, plus steady tones at the receiver (data2g.interference Qrm "carrier", +25 dB over the floor in 50 Hz,
always on: qrm-carriers' carriers while on). A fresh receiver per burst. Per burst:
  header    a header of the sent mode found within 0.5 s of the burst's start
  received  that header's burst handed on with a receive result (rx not None)
  false     headers of anything else (other modes or places) seen during the burst's audio

Run on the branch checkout, once per arm (the pilot switch is read at import):
    DATA2G_PEP_REF_DB=5 DATA2G_PILOTS=off python stream_detect_tone.py --out sd_off.csv
    DATA2G_PEP_REF_DB=5 DATA2G_PILOTS=mix python stream_detect_tone.py --out sd_mix.csv
    python stream_detect_tone.py --compare sd_off.csv sd_mix.csv

SNR is upstream's PEP-5 convention. Limits: one burst on a quiet receiver, so session state (holds, busy,
CW sense, a burst arriving while another is being received) is not covered.
"""
import os
import sys
from pathlib import Path

if not os.environ.get("STUDY_MODEM"):
    sys.exit("set STUDY_MODEM to the Data2G checkout under test (fast-fading-integration, native built)")
CHECKOUT = Path(os.environ["STUDY_MODEM"]).resolve()
sys.path[:0] = [str(CHECKOUT), str(CHECKOUT / "scripts"), str(CHECKOUT / "tests")]
os.environ.setdefault("DATA2G_PROFILE", "hf")

from data2g import threads  # noqa: E402

threads.limit(1)

import argparse  # noqa: E402
import csv  # noqa: E402
from collections import Counter  # noqa: E402
from multiprocessing import Pool  # noqa: E402

import numpy as np  # noqa: E402

import data2g  # noqa: E402
import native_subs  # noqa: E402

_native, _why = native_subs.import_native()
assert _native is not None, _why
assert Path(_native.__file__).resolve().is_relative_to(CHECKOUT), _native.__file__
_native.set_threads(1)
native_subs.apply(native_subs.build(_native, skip={"arq", "gear", "engine", "host"}))  # as the session endpoint

from data2g import codes, cpm, modem  # noqa: E402
from data2g import interference as I  # noqa: E402
from data2g.arq.engine import receive_accept  # noqa: E402
from data2g.arq.policy import slots_for  # noqa: E402
from data2g.config import FS, LEADIN_SAMPLES, SUBMODES  # noqa: E402
from data2g.receiver import Receiver  # noqa: E402
import phy_session as G  # noqa: E402

assert str(CHECKOUT) in data2g.__file__, data2g.__file__
BLK = FS // 50  # 20 ms blocks
LEAD_S, TAIL_S = 1.0, 2.0
BURST_S = 4.0  # data bursts: as many codewords as fit (acks are what they are)
TONE_INR_DB = 25.0
TONES = {"none": (), "800": (800.0,), "2200": (2200.0,), "both": (800.0, 2200.0)}


def one(args):
    name, chan, snr, tone, seed = args
    spec = SUBMODES[name]
    rng = np.random.default_rng([seed, 3])
    n_cw = slots_for(spec, BURST_S) if "ack" not in name else 1
    x = modem.modulate([rng.bytes(codes.payload_bytes(spec)) for _ in range(n_cw)], name)
    xs = np.concatenate([np.zeros(int(LEAD_S * FS)), x, np.zeros(int(TAIL_S * FS))])
    q = tuple(I.Qrm("carrier", f, 50.0, TONE_INR_DB, 600.0, 1.0) for f in TONES[tone])
    s = I.Spec(qrm=q)
    ch = G.ContinuousChannel(chan, snr, seed, 60.0, interference=(s, s))
    y = ch.apply(xs, 5.0, rx=0)
    start = int(G.PAD_S * FS) + int(LEAD_S * FS) + LEADIN_SAMPLES  # the burst's preamble in y
    r = Receiver(receive_accept(), cpm_grids=tuple(cpm.GRIDS))
    header = received = False
    false = 0
    for i in range(0, len(y) - BLK + 1, BLK):
        for kind, d in r.feed(y[i:i + BLK]):
            p = d if kind == "header" else d["header"]
            mine = p["spec"].name == name and abs(p["start"] - start) < FS // 2
            if kind == "header":
                if mine:
                    header = True
                else:
                    false += 1
            elif kind == "burst" and mine and d["rx"] is not None:
                received = True
    return dict(pilots=os.environ.get("DATA2G_PILOTS", ""), mode=name, chan=chan, snr=snr, tone=tone, seed=seed,
                header=int(header), received=int(received), false=false)


def compare(a, b):
    def load(p):
        out = {}
        for r in csv.DictReader(open(p)):
            out.setdefault((r["mode"], r["chan"], float(r["snr"]), r["tone"]), []).append(r)
        return out
    A, B = load(a), load(b)
    print("| Mode | Channel | SNR (PEP-5) | Tone | header found: off / mix | received: off / mix | false headers: off / mix |")
    print("|---|---|---|---|---|---|---|")
    for k in sorted(A, key=lambda k: (k[0], k[1], ("none", "800", "2200", "both").index(k[3]), k[2])):
        x, y = A[k], B.get(k, [])
        f = lambda rows, c: sum(int(r[c]) for r in rows)  # noqa: E731
        print(f"| {k[0]} | {k[1]} | {k[2]:+.0f} | {k[3]} | {f(x, 'header')}/{len(x)} / {f(y, 'header')}/{len(y)} | "
              f"{f(x, 'received')}/{len(x)} / {f(y, 'received')}/{len(y)} | {f(x, 'false')} / {f(y, 'false')} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--modes", default="16qam-r1/3,ack-1f,qpsk-r1/2,w48-qpsk-r1/3")
    ap.add_argument("--chans", default="awgn,mpp")
    ap.add_argument("--snrs", default="0,4")
    ap.add_argument("--tones", default=",".join(TONES))
    ap.add_argument("--bursts", type=int, default=10)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--compare", nargs=2)
    a = ap.parse_args()
    if a.compare:
        return compare(*a.compare)
    if G.PEP_REF_DB is None:
        ap.error("set DATA2G_PEP_REF_DB=5")
    jobs = [(m, c, float(s), t, seed) for m in a.modes.split(",") for c in a.chans.split(",")
            for s in a.snrs.split(",") for t in a.tones.split(",") for seed in range(a.bursts)]
    with Pool(a.jobs, maxtasksperchild=100) as pool, open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, ["pilots", "mode", "chan", "snr", "tone", "seed", "header", "received", "false"])
        w.writeheader()
        for row in pool.imap_unordered(one, jobs, chunksize=2):
            w.writerow(row)
            f.flush()


if __name__ == "__main__":
    main()
