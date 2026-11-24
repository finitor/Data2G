"""For bursts where cpm.spread takes its no-fit branch: the energy correlation between symbols close in time AND tone."""
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


def near(top, k, lags, dt):
    t = top-top.mean(); v = np.mean(t*t); num, n = 0.0, 0
    for L in lags:
        ok = np.abs(k[L:]-k[:-L]) <= dt
        num += np.sum(t[L:][ok]*t[:-L][ok]); n += ok.sum()
    return (num/n/v if n else 0.0), n


CASES = [("2 ms / 0.1 Hz", 0.1, 2.0, 2), ("2 ms / 1 Hz", 1.0, 2.0, 2), ("2 ms / 1 Hz", 1.0, 2.0, -6), ("2 ms / 1 Hz", 1.0, 2.0, -10),
         ("7 ms / 1 Hz", 1.0, 7.0, -8), ("4 ms / 2 Hz", 2.0, 4.0, 0), ("2 ms / 4 Hz", 4.0, 2.0, 0), ("7 ms / 10 Hz", 10.0, 7.0, 0),
         ("2 ms / 10 Hz", 10.0, 2.0, 0), ("7 ms / 30 Hz", 30.0, 7.0, 0), ("2 ms / 30 Hz", 30.0, 2.0, -6)]
for lags, dt in [((1, 2), 0), ((1, 2, 3), 0), ((1, 2), 1), ((1, 2, 3), 1), ((1,), 1), ((1,), 2)]:
    print(f"\nlags {lags}, tone distance <= {dt}")
    for label, dop, delay, snr in CASES:
        rs, ns = [], []
        tot = 0
        for seed in range(200):
            y = H.fading(x, H.FadingPreset("p", dop, delay), seed=seed)
            y = H.awgn(y, snr, seed=seed+1, s_power=H.active_power(x))
            _, E = cpm.soft(g, spec, y, 0, 0.0, 0, False)
            n0 = max(np.median(np.sort(E, axis=1)[:, :-1])/np.log(2), 1e-300)
            top = E.max(axis=1)
            if cpm.spread(g, top, n0) < 11.99:
                continue
            tot += 1
            r, n = near(top, E.argmax(axis=1), lags, dt)
            rs.append(r*np.sqrt(n)); ns.append(n)
        rs = np.array(rs)
        q = np.quantile(rs, [0.05, 0.25, 0.5, 0.75, 0.95]) if len(rs) else [float("nan")]*5
        print(f"  {label:14s} {snr:+3d} dB: {tot:3d} ceiling readings, pairs ~{int(np.median(ns)) if ns else 0:3d}; z = corr*sqrt(pairs) 5/25/50/75/95%: "
              + " ".join(f"{v:5.2f}" for v in q) + f" | z>2: {np.mean(rs > 2)*100:3.0f}%  z>2.5: {np.mean(rs > 2.5)*100:3.0f}%  z>3: {np.mean(rs > 3)*100:3.0f}%")
