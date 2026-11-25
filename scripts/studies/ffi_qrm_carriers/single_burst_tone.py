"""Single bursts under steady tones: where a burst is lost, with and without scattered pilots.

Adapted from fast-fading-integration's scripts/sc_phy_study.py (fixed bursts through phy_session's
ContinuousChannel, received offline as a session's bursts are: receive_any, then arq.phy.ModemRx), with:
  - a steady tone at the receiver (data2g.interference Qrm "carrier", +25 dB over the floor in 50 Hz,
    always on), as qrm-carriers' carriers are while on
  - each burst classified by stage: missed (no burst found), wrong (another mode or length read),
    header (the right header, no codeword decoded), part (some codewords), all (every codeword)

Run it on the branch checkout, once per arm (the pilot switch is read at import):
    DATA2G_PEP_REF_DB=5 DATA2G_PILOTS=mix python single_burst_tone.py --out sb_mix.csv
    DATA2G_PEP_REF_DB=5 DATA2G_PILOTS=off python single_burst_tone.py --out sb_off.csv
    python single_burst_tone.py --compare sb_off.csv sb_mix.csv

SNR is upstream's PEP-5 convention (noise against each burst's peak less 5 dB): this is a standalone test on
ContinuousChannel. Limit: receive_any searches an offline window around the burst, not the streaming
receiver.Receiver, so it does not reproduce a session's receiver state (holds, busy, CW sense).
"""
import os
import sys
from pathlib import Path

if not os.environ.get("STUDY_MODEM"):
    sys.exit("set STUDY_MODEM to the Data2G checkout under test (fast-fading-integration, native built)")
CHECKOUT = Path(os.environ["STUDY_MODEM"]).resolve()
sys.path[:0] = [str(CHECKOUT), str(CHECKOUT / "scripts")]

from data2g import threads  # noqa: E402

threads.limit(1)

import argparse  # noqa: E402
import csv  # noqa: E402
from collections import Counter  # noqa: E402
from multiprocessing import Pool  # noqa: E402

import numpy as np  # noqa: E402

import data2g  # noqa: E402
from data2g import codes, modem  # noqa: E402
from data2g import interference as I  # noqa: E402
from data2g.arq import phy as PHY  # noqa: E402
from data2g.config import FS, SUBMODES  # noqa: E402
import phy_session as G  # noqa: E402

assert str(CHECKOUT) in data2g.__file__, data2g.__file__  # AGENTS.md section 11: the arm's own code
BURST_S = 4.0  # as sc_phy_study: as many codewords as fit
TONE_INR_DB = 25.0  # the carriers preset's level over the floor in 50 Hz
TONES = {  # name -> tone frequencies (Hz). w48: carriers 50 Hz apart over about 350-2700 Hz; w: about 950-2100
    "none": (),
    "800": (800.0,),  # qrm-carriers' low tone
    "825": (825.0,),  # the same, half a carrier spacing off
    "2200": (2200.0,),  # qrm-carriers' high tone
    "both": (800.0, 2200.0),
}
STAGES = ("missed", "wrong", "header", "part", "all")


def spec_of(tone):
    return I.Spec(qrm=tuple(I.Qrm("carrier", f, 50.0, TONE_INR_DB, 600.0, 1.0) for f in TONES[tone]))


def one(args):
    name, chan, snr, tone, seed = args
    spec = SUBMODES[name]
    rng = np.random.default_rng([seed, 3])
    n_cw = max(1, int((BURST_S - modem.burst_seconds(spec, 0)) / (modem.burst_seconds(spec, 1) - modem.burst_seconds(spec, 0))))
    pl = [rng.bytes(codes.payload_bytes(spec)) for _ in range(n_cw)]
    x = modem.modulate(pl, name)
    s = spec_of(tone)
    ch = G.ContinuousChannel(chan, snr, seed, 60.0, interference=(s, s))
    y = ch.apply(x, 5.0, rx=0)
    try:
        r = G.receive_any(y, lead=int(G.PAD_S * FS) + FS // 2)
    except modem.SyncError:
        r = None
    ok = 0
    if r is None:
        stage = "missed"
    elif r.get("family") == "cpm" or r["spec"].name != name or r["n_cw"] != n_cw:
        stage = "wrong"
    else:
        rx = PHY.ModemRx(r, {})
        ok = sum(rx.decode(i, (0, 0, 0), 0, None) == p for i, p in enumerate(pl))
        stage = "all" if ok == n_cw else "part" if ok else "header"
    return dict(pilots=os.environ.get("DATA2G_PILOTS", ""), mode=name, chan=chan, snr=snr, tone=tone, seed=seed,
                n_cw=n_cw, stage=stage, ok=ok)


def compare(a, b):
    def load(p):
        out = {}
        for r in csv.DictReader(open(p)):
            out.setdefault((r["mode"], r["chan"], float(r["snr"]), r["tone"]), []).append(r)
        return out
    A, B = load(a), load(b)
    print("| Mode | Channel | SNR (PEP-5) | Tone | Arm | missed | wrong | header only | some cw | all cw | codewords decoded |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for k in sorted(A, key=lambda k: (k[0], k[1], k[3], k[2])):
        for arm, rows in ((Path(a).stem, A[k]), (Path(b).stem, B.get(k, []))):
            if not rows:
                continue
            c = Counter(r["stage"] for r in rows)
            cw = sum(int(r["ok"]) for r in rows) / sum(int(r["n_cw"]) for r in rows)
            print(f"| {k[0]} | {k[1]} | {k[2]:+.0f} | {k[3]} | {arm} | " + " | ".join(str(c[s]) for s in STAGES) + f" | {cw:.2f} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--modes", default="w48-qpsk-r1/3,qpsk-r1/2")
    ap.add_argument("--chans", default="awgn,mpp")
    ap.add_argument("--snrs", default="0,4")
    ap.add_argument("--tones", default=",".join(TONES))
    ap.add_argument("--bursts", type=int, default=16)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--compare", nargs=2)
    a = ap.parse_args()
    if a.compare:
        return compare(*a.compare)
    if G.PEP_REF_DB is None:
        ap.error("set DATA2G_PEP_REF_DB=5")
    jobs = [(m, c, float(s), t, seed) for m in a.modes.split(",") for c in a.chans.split(",")
            for s in a.snrs.split(",") for t in a.tones.split(",") for seed in range(a.bursts)]
    with Pool(a.jobs) as pool, open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, ["pilots", "mode", "chan", "snr", "tone", "seed", "n_cw", "stage", "ok"])
        w.writeheader()
        for row in pool.imap_unordered(one, jobs, chunksize=2):
            w.writerow(row)
            f.flush()


if __name__ == "__main__":
    main()
