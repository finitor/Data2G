"""The gate-6s6 sessions where the two stations decided differently, and the same sessions in other arms."""
import json, re, sys
from pathlib import Path
import os
HERE = Path(os.environ.get("ROBUST_START_OUT", "robust-start-results")).resolve()
PAT = re.compile(r"i=(\d) data2g\.session: robust start \((\w+)\): connect frame (\S+), snr_est (\S+), spread_est (\S+) -> (.+)")
FOLLOW = re.compile(r"i=(\d) data2g\.session: robust start \(caller\): first burst (\S+) -> (.+)")
CONDS = ["lost", "normal", "qrm-first", "qrm-noise", "qrm-fsk"]
LIMIT, DIAL = 179.5, 0.5


def load(arm, cond):
    d, out = HERE/f"{arm}-{cond}", {}
    for p in sorted(d.glob("sessions*.jsonl")):
        for s in p.read_text().splitlines():
            r = json.loads(s)
            text = (d/"sessions"/r["log"]).read_text()
            r["dec"] = {int(m[0]): (m[5], float(m[3]) if m[3] != "none" else None, float(m[4]) if m[4] != "none" else None) for m in PAT.findall(text)}
            r["follow"] = [(m[1], m[2]) for m in FOLLOW.findall(text)]
            out[(r["point"][0], r["seed"])] = r
    return out


def t(r):
    return r["acknowledged_at"]-DIAL if r["complete"] else LIMIT


def splits():
    out, linked = [], 0
    for cond in CONDS:
        for k, r in sorted(load("gate-6s6", cond).items()):
            linked += len(r["dec"]) == 2
            if len(r["dec"]) == 2 and len({v[0] for v in r["dec"].values()}) == 2:
                out.append((cond, *k))
    return out, linked


if __name__ == "__main__":
    sp, linked = splits()
    if sys.argv[1:] == ["list"]:
        print(len(sp), "of", linked, file=sys.stderr)
        for c, p, s in sp:
            print(c, p, s)
        sys.exit()
    arms = ["off", "on", "gate-6s6", "caller-6s6"]
    data = {(a, c): load(a, c) for a in arms for c in CONDS if (HERE/f"{a}-{c}").exists()}
    print("| Condition | Channel | Seed | caller read (SNR dB, spread Hz) | callee read | caller decided | callee's first burst | off | on | gate | caller-decides |")
    print("|---|---|---:|---|---|---|---|---:|---:|---:|---:|")
    tot = {a: [] for a in arms}
    for c, p, s in sp:
        rs = {a: data.get((a, c), {}).get((p, s)) for a in arms}
        g, n = rs["gate-6s6"], rs["caller-6s6"]
        cells = [(f"{t(r):.1f}" if r["complete"] else "fail") if r else "?" for r in rs.values()]
        for a, r in rs.items():
            if r:
                tot[a].append(t(r))
        rd = lambda i: f"{g['dec'][i][1]:.1f}, {g['dec'][i][2]:.1f}"
        nd = n["dec"].get(0, ("?",))[0] if n else "?"
        fl = "; ".join(f"{m} ({d})" for m, d in n["follow"]) if n else "?"
        print(f"| {c} | {p} | {s} | {rd(0)} | {rd(1)} | {nd} | {fl or 'none heard'} | " + " | ".join(cells) + " |")
    print()
    for a, v in tot.items():
        print(f"{a}: n={len(v)} mean {sum(v)/max(len(v),1):.1f} s, unfinished {sum(x >= LIMIT for x in v)}")
