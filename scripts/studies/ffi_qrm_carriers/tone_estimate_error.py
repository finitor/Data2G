"""Per-carrier channel-estimate error under a steady tone: pilot row against scattered pilots.

Adapted from fast-fading-integration's scripts/sc_diag.py (fixed bursts, the receiver given the burst's
timing so no search, the channel's taps known, the estimate compared with the true channel after fitting one
gain and the window's delay per burst). Added: a steady tone at the receiver, +25 dB over the floor in 50 Hz
(as qrm-carriers' carriers while on), and every measure kept per carrier:
  est_err   |h_est - h_true|^2 over the mean |h_true|^2: the channel estimate's own error
  meas      |Y - h_est X|^2 over the signal: the error the data cells actually carry
  told      noise_var + mse over the signal: what the LLRs were told about those cells
meas/told above 1 on a carrier means its bits are overconfident.

    python tone_estimate_error.py --out est_err.csv          # flag 0: pilot row, 1: scattered pilots (mix)
    python tone_estimate_error.py --show est_err.csv

SNR is PEP-5 (sc_diag's: noise against the burst's peak less 5 dB). Runs on the branch checkout, where
sc_diag.setup switches the layout per job.
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
from multiprocessing import Pool  # noqa: E402

import numpy as np  # noqa: E402
from scipy import signal  # noqa: E402

import data2g  # noqa: E402
from data2g import codes, constellation, hfchannel, modem  # noqa: E402
from data2g.config import FS, LEADIN_SAMPLES, M, NCP, NSYM, SNR_REF_BW_HZ, SUBMODES  # noqa: E402
from data2g.waveform import ofdm  # noqa: E402
import sc_diag as D  # noqa: E402

assert str(CHECKOUT) in data2g.__file__, data2g.__file__
TONE_INR_DB = 25.0  # over the floor in 50 Hz: the carriers preset's level
TONE_REF_HZ = 50.0


def one(args):
    flag, name, chan, snr, tone, seed = args
    D.setup("mix", flag)
    spec = SUBMODES[name]
    b = ofdm.band(spec.band)
    rng = np.random.default_rng([seed, 3])
    n_cw = max(1, int((4.0 - modem.burst_seconds(spec, 0)) / (modem.burst_seconds(spec, 1) - modem.burst_seconds(spec, 0))))
    pl = [rng.bytes(codes.payload_bytes(spec)) for _ in range(n_cw)]
    x = np.concatenate([np.zeros(D.PAD), modem.modulate(pl, name), np.zeros(D.PAD)])
    known = dict(start=D.PAD + LEADIN_SAMPLES, cfo=0.0, spec=spec, n_cw=n_cw)
    z = signal.hilbert(x)
    peak = float(np.max(np.abs(z) ** 2) / 2)
    if chan == "awgn":
        y, taps = x.copy(), None
    else:
        p = D.PRESETS[chan]
        g = np.random.default_rng(seed)
        d = int(round(p.delay_ms * 1e-3 * FS))
        g1, g2 = (hfchannel._gaussian_taps(len(z), p.doppler_hz, g) for _ in range(2))
        y = np.real((z * g1 + np.concatenate([np.zeros(d, dtype=complex), z[:len(z) - d]]) * g2) / np.sqrt(2))
        taps = (g1, g2, d)
    sigma = np.sqrt(peak / 10 ** 0.5 * (FS / 2) / SNR_REF_BW_HZ / 10 ** (snr / 10))
    y = y + np.random.default_rng([seed, 5]).normal(scale=sigma, size=len(y))
    if tone:
        amp = np.sqrt(2 * sigma**2 * TONE_REF_HZ / (FS / 2) * 10 ** (TONE_INR_DB / 10))
        ph = np.random.default_rng([seed, 9]).uniform(0, 2 * np.pi)
        y = y + amp * np.cos(2 * np.pi * tone * np.arange(len(y)) / FS + ph)
    try:
        r = modem.receive(y, known=known)
    except modem.SyncError:
        return args, None
    e = r["est"]
    ok = sum(modem.decode_received(r).crc_ok)
    bits = np.stack([codes.encode(spec, p_, 0, index=i) for i, p_ in enumerate(pl)])
    X = constellation.modulate(codes.spread(bits, spec.bits_per_cu), constellation.load(spec.constellation)).reshape(e["h"].shape)
    Y = modem.data_symbols(r["raw"])
    sym, k = D.cells(r)
    n = r["p0"] + sym * NSYM + NCP + M // 2
    if taps is None:
        H = np.ones(len(sym), dtype=complex)
    else:
        H = (taps[0][n] + taps[1][n] * np.exp(-2j * np.pi * b.freqs[k] * taps[2] / FS)) / np.sqrt(2)
    # the receiver took out what it read as residual CFO (sc_diag does this on fading only; a tone can pull it on AWGN)
    H = H * np.exp(-2j * np.pi * r["cfo"] * n / FS)
    best = None
    for tau in np.arange(-48, 48.01, 0.5):
        ref = H * np.exp(2j * np.pi * b.bb[k] * tau / FS)
        c = np.vdot(ref, e["h"].ravel()) / np.vdot(ref, ref)
        if best is None or abs(c) > abs(best[0]):
            best = (c, ref)
    ref = best[0] * best[1]
    nc = b.nc
    norm = np.mean(np.abs(ref) ** 2)
    sig = np.mean(np.abs(e["h"] * X) ** 2)
    per = lambda v: np.bincount(k, weights=np.ravel(v), minlength=nc) / np.maximum(np.bincount(k, minlength=nc), 1)  # noqa: E731
    out = dict(ok=ok, n_cw=n_cw,
               est_err=per(np.abs(e["h"].ravel() - ref) ** 2) / norm,
               meas=per(np.abs(Y - e["h"] * X) ** 2) / sig,
               told=per(np.broadcast_to(modem.noise_var(e["h"], e) + e["mse"], e["h"].shape)) / sig,
               freqs=np.asarray(b.freqs, float))
    return args, out


def show(path):
    rows = list(csv.DictReader(open(path)))
    keys = sorted({(r["mode"], r["chan"], r["snr"], r["tone"]) for r in rows})
    for key in keys:
        sel = {f: [r for r in rows if (r["mode"], r["chan"], r["snr"], r["tone"]) == key and r["flag"] == f] for f in ("0", "1")}
        print(f"\n### {key[0]}, {key[1]}, SNR {key[2]} (PEP-5), tone {key[3]} Hz\n")
        print("codewords decoded: pilot row " + sel["0"][0]["ok_frac"] + ", scattered " + sel["1"][0]["ok_frac"])
        print("\n| carrier | Hz | est_err dB: row / scattered | meas/told dB: row / scattered |\n|---|---|---|---|")
        a, c = sel["0"], sel["1"]
        for ra, rc in zip(sorted(a, key=lambda r: int(r["k"])), sorted(c, key=lambda r: int(r["k"]))):
            print(f"| {ra['k']} | {float(ra['hz']):.0f} | {float(ra['est_err_db']):+.1f} / {float(rc['est_err_db']):+.1f} | "
                  f"{float(ra['over_db']):+.1f} / {float(rc['over_db']):+.1f} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--mode", default="w48-qpsk-r1/3")
    ap.add_argument("--chans", default="awgn,mpp")
    ap.add_argument("--snrs", default="8")
    ap.add_argument("--tones", default="0,825,2200")
    ap.add_argument("--bursts", type=int, default=24)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--show")
    a = ap.parse_args()
    if a.show:
        return show(a.show)
    jobs = [(f, a.mode, c, float(s), float(t), seed) for f in (False, True) for c in a.chans.split(",")
            for s in a.snrs.split(",") for t in a.tones.split(",") for seed in range(a.bursts)]
    acc = {}
    with Pool(a.jobs, maxtasksperchild=200) as pool:
        for args, o in pool.imap_unordered(one, jobs, chunksize=2):
            acc.setdefault(args[:5], []).append(o)
    db = lambda v: 10 * np.log10(max(float(v), 1e-12))  # noqa: E731
    with open(a.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["flag", "mode", "chan", "snr", "tone", "k", "hz", "est_err_db", "over_db", "ok_frac", "bursts"])
        for (flag, m, c, s, t), outs in sorted(acc.items()):
            got = [o for o in outs if o is not None]
            okf = sum(o["ok"] for o in got) / max(sum(o["n_cw"] for o in got), 1)
            ee = np.median([o["est_err"] for o in got], axis=0)
            ov = np.median([o["meas"] / o["told"] for o in got], axis=0)
            for kk in range(len(ee)):
                w.writerow([int(flag), m, c, s, int(t), kk, round(got[0]["freqs"][kk], 1), round(db(ee[kk]), 2),
                            round(db(ov[kk]), 2), f"{okf:.2f}", len(got)])


if __name__ == "__main__":
    main()
