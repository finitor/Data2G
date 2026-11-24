"""Why cpm.spread reads its 12 Hz ceiling on 1 Hz fading: a control-only fsk16r25 burst (the robust connect
frame's shape) through two-path fading, genie timing, Python reference estimator."""
import os, sys
os.environ["DATA2G_PROFILE"] = "hf"
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import numpy as np
from data2g import cpm, codes, hfchannel as H

spec = cpm.SPECS[sys.argv[1] if len(sys.argv) > 1 else "fsk16r25-r1/2"]
g = cpm.GRIDS[spec.grid]
ctl = codes.encode(cpm.CTL[g.name], bytes(range(codes.payload_bytes(cpm.CTL[g.name]))), 0, 0)
x = cpm.modulate(spec, [ctl], dup=False)
print(spec.name, "symbols", len(x)//g.T, "seconds", len(x)/H.FS, "tone span Hz", g.m*g.rate)


def parts(top, n0):
    n = len(top); mean = top.mean(); t = top-mean
    c = np.array([np.mean(t[k:]*t[:n-k]) for k in range(1, 9)]); v = np.mean(t*t)
    s = max(mean-n0, 1e-12)
    return (v-(2*n0*s+n0*n0))/(s*s), c[0]/v, cpm.SPREAD_SIG/np.sqrt(n), c[1]/c[0] if c[0] > 0 else float("nan")


def read(y):
    E, _ = None, None
    soft, E = cpm.soft(g, spec, y, 0, 0.0, 0, False)
    n0 = max(np.median(np.sort(E, axis=1)[:, :-1])/np.log(2), 1e-300)
    return E, n0


for label, dop, delay, snr in [("awgn", None, 0, 2), ("flat 1 Hz", 1.0, 0.0, 2), ("2 ms / 1 Hz", 1.0, 2.0, 2), ("2 ms / 1 Hz", 1.0, 2.0, -6),
                               ("7 ms / 1 Hz", 1.0, 7.0, -8), ("2 ms / 0.1 Hz", 0.1, 2.0, 2), ("7 ms / 10 Hz", 10.0, 7.0, 0), ("7 ms / 30 Hz", 30.0, 7.0, 0)]:
    out, eq = [], []
    for seed in range(200):
        y = x if dop is None else H.fading(x, H.FadingPreset("p", dop, delay), seed=seed)
        y = H.awgn(y, snr, seed=seed+1, s_power=H.active_power(x))
        E, n0 = read(y)
        top = E.max(axis=1)
        sp = cpm.spread(g, top, n0)
        # the same estimator with each tone's own mean taken out of the symbols it won
        k = E.argmax(axis=1)
        gain = np.array([top[k == j].mean() if (k == j).sum() >= 3 else np.nan for j in range(g.m)])
        ref = np.nanmean(gain)
        flat = top/np.where(np.isnan(gain[k]), ref, gain[k])*ref
        out.append((sp, *parts(top, n0)))
        eq.append(cpm.spread(g, flat, n0))
    o = np.array(out); sp = o[:, 0]; hi = sp >= 11.99
    e = np.array(eq)
    print(f"{label:14s} {snr:+3d} dB: reads 12.0 in {hi.sum():3d}/200, 0.0 in {(sp == 0).sum():3d}, median {np.median(sp):5.2f} | "
          f"when 12.0: lag-1 corr median {np.median(o[hi, 2]) if hi.any() else float('nan'):.3f} (needs > {o[0, 3]:.3f}), excess {np.median(o[hi, 1]) if hi.any() else float('nan'):.2f} | "
          f"per-tone normalised: 12.0 in {(e >= 11.99).sum():3d}, 0.0 in {(e == 0).sum():3d}, median {np.median(e):5.2f}")
