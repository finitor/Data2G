"""Tables for the robust-start study: per condition and point, each arm against `off`."""
import json, re, statistics as st, sys
from pathlib import Path
import os
HERE = Path(os.environ.get("ROBUST_START_OUT", "robust-start-results")).resolve()
ORDER = ["awgn+20", "awgn+5", "awgn+0", "awgn-4", "awgn-8", "awgn-12", "awgn-14", "mpp+2", "mpp-2", "mpp-6", "mpp-8", "mpp-10",
         "nvis-8", "nvis-10", "flutter+0", "hilat+0"]
LABEL = {"awgn+20": "AWGN +20 dB", "awgn+5": "AWGN +5 dB", "awgn+0": "AWGN 0 dB", "awgn-4": "AWGN −4 dB", "awgn-8": "AWGN −8 dB",
         "awgn-12": "AWGN −12 dB", "awgn-14": "AWGN −14 dB", "mpp+2": "2 ms / 1 Hz, +2 dB", "mpp-2": "2 ms / 1 Hz, −2 dB",
         "mpp-6": "2 ms / 1 Hz, −6 dB", "mpp-8": "2 ms / 1 Hz, −8 dB", "mpp-10": "2 ms / 1 Hz, −10 dB", "nvis-8": "7 ms / 1 Hz, −8 dB",
         "nvis-10": "7 ms / 1 Hz, −10 dB", "flutter+0": "7 ms / 10 Hz, 0 dB", "hilat+0": "7 ms / 30 Hz, 0 dB"}
LIMIT, DIAL = 179.5, 0.5
PAT = re.compile(r"t=([\d.]+) i=(\d) data2g\.session: robust start \((\w+)\): connect frame (\S+), snr_est (\S+), spread_est (\S+) -> (.+)")


SEED0 = 125000


def load(arm, cond):
    d = HERE/f"{arm}-{cond}"
    out = {}
    for p in sorted(d.glob("sessions*.jsonl")):
        for s in p.read_text().splitlines():
            r = json.loads(s)
            if not SEED0 <= r["seed"] < SEED0+8:
                continue
            r["readings"] = [dict(i=int(m[1]), mode=m[3], snr=float(m[4]) if m[4] != "none" else None,
                                  spread=float(m[5]) if m[5] != "none" else None, robust=m[6] == "robust floor")
                             for m in PAT.findall((d/"sessions"/r["log"]).read_text())]
            assert not r["status"][7]
            out[(r["point"][0], r["seed"])] = r
    return out


def t(r):
    return r["acknowledged_at"]-DIAL if r["complete"] else LIMIT


def summarize(rs):
    done = [t(r) for r in rs if r["complete"]]
    return dict(n=len(rs), connected=sum(r["connected"] for r in rs), completed=len(done),
                median=st.median(done) if done else None, mean=st.mean(t(r) for r in rs),
                via_retry=sum(bool(r["readings"]) for r in rs))


def cell(s):
    return f"{s['completed']}/{s['n']}; " + (f"{s['median']:.1f}" if s["median"] is not None else "—") + f"; {s['mean']:.1f}"


def main():
    global SEED0
    args = sys.argv[1:]
    conds = ("lost", "normal")
    while args and args[0].startswith("--"):
        k, v = args.pop(0), args.pop(0)
        if k == "--seed":
            SEED0 = int(v)
        elif k == "--conds":
            conds = tuple(v.split(","))
    arms = args or ["off", "on"]
    TITLE = {"lost": "First CONNECT lost (blanked)", "normal": "Normal", "qrm-first": "QRM burst over the first CONNECT only (callee)",
             "qrm-noise": "Bursty band noise all session (both receivers)", "qrm-fsk": "Bursty FSK-like QRM all session (both receivers)"}
    out = {}
    for cond in conds:
        data = {a: load(a, cond) for a in arms if (HERE/f"{a}-{cond}").exists()}
        if "off" not in data:
            continue
        print(f"\n## {TITLE[cond]}\n")
        print("Completed of 8; median s among completions; mean s with unfinished counted as 179.5. Then, against off per seed: faster / slower by more than 5 s, gained / lost.\n")
        print("| Channel | connected by a retry (off) | " + " | ".join(f"{a}" + ("" if a == "off" else f" | {a} vs off") for a in data) + " |")
        print("|---|---:|" + "---:|"*(2*len(data)-1))
        for n in ORDER:
            base = [r for (p, s), r in sorted(data["off"].items()) if p == n]
            if not base:
                continue
            cells = [f"{summarize(base)['via_retry']}/{len(base)}"]
            for a, d in data.items():
                rs = [r for (p, s), r in sorted(d.items()) if p == n]
                if len(rs) != len(base):
                    cells += ["incomplete"] + ([] if a == "off" else [""])
                    continue
                sm = summarize(rs)
                out[(cond, n, a)] = sm
                cells.append(cell(sm))
                if a != "off":
                    dt = [t(x)-t(y) for x, y in zip(rs, base)]
                    cells.append(f"{sum(v < -5 for v in dt)} / {sum(v > 5 for v in dt)}, {sum(x['complete'] and not y['complete'] for x, y in zip(rs, base))} / {sum(y['complete'] and not x['complete'] for x, y in zip(rs, base))}; Δmean {sm['mean']-summarize(base)['mean']:+.1f}")
            print(f"| {LABEL[n]} | " + " | ".join(cells) + " |")
    # the connect frame's readings, from the off arm (both conditions): what a gate would see
    print("\n## Connect-frame readings when a retry made the link (off arm)\n")
    print("| Channel | condition | sides read | snr_est min / median / max | spread_est min / median / max |\n|---|---|---:|---:|---:|")
    for cond in conds:
        if not (HERE/f"off-{cond}").exists():
            continue
        d = load("off", cond)
        for n in ORDER:
            rd = [x for (p, s), r in d.items() if p == n for x in r["readings"]]
            if rd:
                sn, sp = sorted(x["snr"] for x in rd), sorted(x["spread"] for x in rd)
                print(f"| {LABEL[n]} | {cond} | {len(rd)} | {sn[0]:.1f} / {st.median(sn):.1f} / {sn[-1]:.1f} | {sp[0]:.1f} / {st.median(sp):.1f} / {sp[-1]:.1f} |")
    (HERE/f"summary-{SEED0}-{'+'.join(conds)}.json").write_text(json.dumps({"|".join(k): v for k, v in out.items()}, indent=1)+"\n")


if __name__ == "__main__":
    main()
