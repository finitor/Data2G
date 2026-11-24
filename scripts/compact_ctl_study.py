"""A compact CPM control codeword at code level (EXPERIMENT, Python only;
native not updated, nothing on air changes).

Question: the c16r25 control is polar k=184 of n=360 (20 B + CRC-24), and
a control's content is mostly 9-16 B. What does a second info set of the
same 360 coded bits with far fewer info bits buy, against today's blind
decode and today's padding cuts (phy.POLAR_PIN_CUTS)?

Method, as cpm_floor_study's `ideal`: the real polar code, scrambler,
CRC-24 and list decoder (data2g.codes), tones through noncoherent
orthogonal 16-FSK with synthetic tone energies (AWGN, or i.i.d. Rayleigh a
tone), demapped by the receiver's own cpm.llrs. No sync, header, CFO,
filter or timing loss: thresholds here are the code's, not a burst's. Every
arm sees the same noise at a point (same seed). Es/N0 is per tone; SNR in
2500 Hz is 10 log10(25 / 2500) = -20 dB below it on c16r25.

Arms (k = info bits incl. CRC-24; all n = 360 unless dup):
  data-r1/3, data-r1/2   the grid's GF(16) data codewords (n = 960), for reference
  full                   today's control, a full random 20 B payload, plain decode
  full-c12               today's control with 12 B of content: plain, then the shipped cuts
  full-c8                the same with 8 B of content (the shipped cuts: 12, 16)
  full-g8                8 B of content, pinned at its exact length (the full code's bound)
  full-dup               today's control twice, soft bits added (ARQ_DUP; polar RVs are equal)
  cK-dD                  a compact control, payload K bytes (k = 8K + 24), GA design SNR D dB
  c8-dup                 compact 8 B twice

    python scripts/compact_ctl_study.py --out runs/compact-ctl/code_level.csv

--e2e: control-only bursts (cpm.modulate: sync blocks, two header copies,
the control codeword, the TX filter at cap 2) through phy_session's
ContinuousChannel (mean-power SNR in 2500 Hz, 4.5 Hz CFO, Watterson
fading), then the shipped receiver. A compact codeword rides in the
control slot as it is (same 360 bits; the header says nothing of it).
Trial k has the same fading and noise in every arm. Per arm and point:
  lock   the blind lock (cpm_floor_study.receive_traced: find, late lock,
         mid lock) read a control-only burst of this grid
  blind  that lock, cpm.receive's control soft bits, decoded
  slot   blind, else cpm.prime_lock within ReplySlot.TOL_S of the true
         start at the true CFO (the expected slot of a reply), decoded
  genie  known start and CFO (cpm.receive refines them), decoded
Decoding is unprimed: plain, then the arm's padding cuts. No hypothesis
of the control's content is tried (link.Station.expect).

    python scripts/compact_ctl_study.py --e2e --trials 200 --out runs/compact-ctl/e2e.csv
"""

from data2g import threads  # noqa: E402

threads.limit(1)

import argparse  # noqa: E402
import csv  # noqa: E402
from multiprocessing import Pool  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

from data2g import codes, cpm  # noqa: E402
from data2g.arq.phy import POLAR_PIN_CUTS  # noqa: E402

GRID = "c16r25"
INDEX = 0  # a control's burst position


def compact_spec(payload: int, design: float):
    """A control of `payload` bytes in the grid's 360 coded bits, its info
    set by codes' GA design at `design` dB (codes.POLAR_DESIGN_SNR_DB is the
    shipped -3)."""
    spec = cpm.CpmSpec(f"fsk16r25-ctl-c{payload}-d{design:g}", GRID, -1, "polar", 8 * payload + 24, cpm.CTL_N)
    old = codes.POLAR_DESIGN_SNR_DB
    codes.POLAR_DESIGN_SNR_DB = design
    try:
        codes.polar_code(spec).info_pos  # designed and cached under this spec
    finally:
        codes.POLAR_DESIGN_SNR_DB = old
    return spec


def arms():
    full = cpm.CTL[GRID]
    out = {
        "data-r1/3": dict(spec=cpm.SPECS["fsk16r25-r1/3"], kind="data"),
        "data-r1/2": dict(spec=cpm.SPECS["fsk16r25-r1/2"], kind="data"),
        "full": dict(spec=full, content=20, cuts=()),
        "full-c12": dict(spec=full, content=12, cuts=POLAR_PIN_CUTS),
        "full-c8": dict(spec=full, content=8, cuts=POLAR_PIN_CUTS),
        "full-g8": dict(spec=full, content=8, cuts=(8,)),
        "full-dup": dict(spec=full, content=20, cuts=(), copies=2),
        "c8-dup": dict(payload=8, design=-6.0, copies=2),
    }
    for payload, design in ((8, -3.0), (8, -6.0), (8, -9.0), (6, -6.0), (10, -6.0), (12, -6.0)):
        out[f"c{payload}-d{design:g}"] = dict(payload=payload, design=design)
    return out


def soft_rows(g, spec, coded, esn0_db, fading, rng, metric):
    """(B, coded_bits) coded bits -> (B, soft_len) soft values through the tone channel."""
    es = 10 ** (esn0_db / 10)
    out = []
    for bits in coded:
        t = cpm.to_tones(g, bits)
        h = (rng.normal(size=len(t)) + 1j * rng.normal(size=len(t))) / np.sqrt(2) if fading else np.ones(len(t))
        y = (rng.normal(size=(len(t), g.m)) + 1j * rng.normal(size=(len(t), g.m))) / np.sqrt(2)
        y[np.arange(len(t)), t] += np.sqrt(es) * h
        out.append(metric(g, np.abs(y) ** 2))
    return np.array(out, np.float32)


def point(args):
    """-> (arm, fading, esn0, trials, ok, wrong): wrong = a payload that passed its CRC and is not the one sent."""
    name, fading, esn0, n, seed = args
    a = arms()[name]
    g = cpm.GRIDS[GRID]
    spec = a["spec"] if "spec" in a else compact_spec(a["payload"], a["design"])
    pb = codes.payload_bytes(spec)
    rng = np.random.default_rng([seed, int(fading), int(round(esn0 * 100)) + 10000])
    content = a.get("content", pb)
    pay = [bytes(rng.integers(0, 256, content, dtype=np.uint8)).ljust(pb, b"\0") for _ in range(n)]
    if a.get("kind") == "data":
        coded = [codes.encode(spec, p, index=1) for p in pay]
        got = codes.decode_many(spec, soft_rows(g, spec, coded, esn0, fading, rng, cpm.symbol_ll), index=[1] * n)
        ok = sum(o and p == q for (p, o), q in zip(got, pay))
        return name, fading, esn0, n, ok, sum(o and p != q for (p, o), q in zip(got, pay))
    coded = [codes.encode(spec, p, index=INDEX) for p in pay]
    soft = sum(soft_rows(g, spec, coded, esn0, fading, rng, cpm.llrs) for _ in range(a.get("copies", 1)))
    cands, usable = codes.decode_raw(spec, soft, index=[INDEX] * n)
    got = [codes.check(spec, c, u, 0) for c, u in zip(cands, usable)]
    for off in (c for c in a.get("cuts", ()) if 0 < c < pb and c >= content):
        miss = [i for i, x in enumerate(got) if x is None]
        if not miss:
            break
        cands, usable = codes.decode_raw_pinned(spec, soft[miss], codes.zero_tail(spec, off), INDEX)
        for i, c, u in zip(miss, cands, usable):
            got[i] = codes.check(spec, c, u, 0)
    ok = sum(x == p for x, p in zip(got, pay))
    return name, fading, esn0, n, ok, sum(x is not None and x != p for x, p in zip(got, pay))


E2E_ARMS = ("full", "full-c8", "c8-d-6", "c6-d-6")
E2E_CHANS = {"awgn": None, "mpg": (0.1, 0.5), "mpp": (1.0, 2.0), "mpd": (2.0, 4.0)}
E2E_MODE = "fsk16r25-r1/2"  # the header's mode: a control-only burst of either rate reads alike


def decode_ctl(a, spec, soft, content):
    """One control's soft bits -> its payload or None: plain, then the arm's cuts."""
    pb = codes.payload_bytes(spec)
    cands, usable = codes.decode_raw(spec, soft[None], index=[INDEX])
    got = codes.check(spec, cands[0], usable[0], 0)
    for off in (c for c in a.get("cuts", ()) if 0 < c < pb and c >= content):
        if got is not None:
            break
        cands, usable = codes.decode_raw_pinned(spec, soft[None], codes.zero_tail(spec, off), INDEX)
        got = codes.check(spec, cands[0], usable[0], 0)
    return got


def e2e_trial(args):
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    import phy_session as PS
    from cpm_floor_study import receive_traced
    from data2g.config import FS
    from data2g.receiver import ReplySlot

    chan, snr, seed, names = args
    g = cpm.GRIDS[GRID]
    mode = cpm.SPECS[E2E_MODE]
    out = {}
    for name in names:
        a = arms()[name]
        spec = a["spec"] if "spec" in a else compact_spec(a["payload"], a["design"])
        pb = codes.payload_bytes(spec)
        content = a.get("content", pb)
        rng = np.random.default_rng([seed, 1])  # every arm: the same content bytes' prefix, start time
        t0 = float(rng.uniform(5, 100))
        pay = bytes(rng.integers(0, 256, 20, dtype=np.uint8))[:content].ljust(pb, b"\0")
        x = cpm.modulate(mode, [codes.encode(spec, pay, index=INDEX)], dup=False, cap=2)
        dd = E2E_CHANS[chan]
        ch = PS.ContinuousChannel("awgn", snr, seed, 120.0, *(dd or (None, None)))
        y = ch.apply(x / np.sqrt(np.mean(x**2)), t0)
        s_true = int(PS.PAD_S * FS)

        def dec(r):
            ok = r is not None and r["band"] == GRID and r["n_cw"] == 1 and not r["dup"]
            got = decode_ctl(a, spec, np.asarray(r["soft"][0], np.float32), content) if ok else None
            return int(got == pay), int(got is not None and got != pay)

        r = receive_traced(y, E2E_MODE)
        lock = int(r is not None and r["band"] == GRID and r["n_cw"] == 1 and not r["dup"])
        blind, w1 = dec(r)
        slot, w2 = blind, 0
        if not lock:
            tol = int(ReplySlot.TOL_S * FS)
            pl = cpm.prime_lock(g, y, max(0, s_true - tol), s_true + tol, PS.CFO_HZ)
            slot, w2 = dec(cpm.receive(y, pl) if pl is not None else None)
        genie, w3 = dec(cpm.receive(y, dict(spec=mode, n_data=0, dup=False, start=s_true, cfo=PS.CFO_HZ, band=GRID)))
        out[name] = dict(lock=lock, blind=blind, slot=slot, genie=genie, wrong=w1 + w2 + w3)
    return chan, snr, seed, out


def e2e(a):
    names = a.arms or list(E2E_ARMS)
    grids = {c: [float(s) for s in np.arange(a.lo, a.hi + 1e-9, a.step)] for c in a.chans}
    jobs = [(c, s, 70000 + i, names) for c in a.chans for s in grids[c] for i in range(a.trials)]
    rows = []
    with Pool(a.jobs) as p:
        for c, s, seed, out in p.imap_unordered(e2e_trial, jobs, chunksize=4):
            rows += [(c, s, seed, arm, *(o[k] for k in ("lock", "blind", "slot", "genie", "wrong"))) for arm, o in out.items()]
    rows.sort()
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        with open(a.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["channel", "snr_db", "seed", "arm", "lock", "blind", "slot", "genie", "wrong"])
            w.writerows(rows)
    print("SNR (dB, mean power in 2500 Hz) at 10% failure [50%], control-only c16r25 bursts through the receiver")
    for c in a.chans:
        print(f" {c}")
        for arm in names:
            s = []
            for j, k in ((4, "lock"), (5, "blind"), (6, "slot"), (7, "genie")):
                fail = [1 - np.mean([r[j] for r in rows if r[0] == c and r[1] == x and r[3] == arm]) for x in grids[c]]
                s.append(f"{k} {crossing(grids[c], fail, 0.1):6.2f} [{crossing(grids[c], fail, 0.5):6.2f}]")
            wrong = sum(r[8] for r in rows if r[0] == c and r[3] == arm)
            print(f"   {arm:8s} " + "  ".join(s) + f"  wrong {wrong}")


def crossing(xs, fail, target):
    for i in range(len(xs) - 1):
        if fail[i] >= target > fail[i + 1]:
            return xs[i] + (fail[i] - target) / (fail[i] - fail[i + 1]) * (xs[i + 1] - xs[i])
    return float("nan")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--n", type=int, default=400, help="codewords a point (data arms: a quarter)")
    ap.add_argument("--lo", type=float, default=-3.0)
    ap.add_argument("--hi", type=float, default=10.0)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--arms", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20261124)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--e2e", action="store_true", help="bursts through the receiver (--lo/--hi/--step: SNR in 2500 Hz)")
    ap.add_argument("--trials", type=int, default=200, help="e2e: bursts a point")
    ap.add_argument("--chans", nargs="*", default=list(E2E_CHANS))
    a = ap.parse_args()
    if a.e2e:
        return e2e(a)
    names = a.arms or list(arms())
    grid = [float(x) for x in np.arange(a.lo, a.hi + 1e-9, a.step)]
    jobs = [(m, f, e, max(50, a.n // 4) if m.startswith("data") else a.n, a.seed)
            for m in names for f in (False, True) for e in grid]
    with Pool(a.jobs) as p:
        res = p.map(point, jobs, chunksize=1)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        with open(a.out, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["arm", "channel", "esn0_db", "trials", "ok", "wrong"])
            w.writerows([m, "ray" if f else "awgn", e, n, ok, wr] for m, f, e, n, ok, wr in res)
    print("10% failure Es/N0 per tone, dB (SNR in 2500 Hz is 20 dB lower); 50% in brackets; wrong = CRC passes on a wrong payload")
    for m in names:
        s = []
        for f in (False, True):
            r = [x for x in res if x[0] == m and x[1] == f]
            fail = [1 - x[4] / x[3] for x in r]
            s.append(f"{'ray' if f else 'awgn'} {crossing(grid, fail, 0.1):6.2f} [{crossing(grid, fail, 0.5):6.2f}] "
                     f"wrong {sum(x[5] for x in r)}/{sum(x[3] for x in r)}")
        print(f"  {m:10s} " + "   ".join(s))


if __name__ == "__main__":
    main()
