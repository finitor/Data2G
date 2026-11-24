"""All arms against off: mean session time per cell (unfinished 179.5 s), completions, and the spread ceiling's count."""
import collections, json, sys
import splits as S
from analyze import ORDER, LABEL
ARMS = ["on", "gate-6s6", "caller-6s6", "caller-6s6m", "both-6s6", "both-6s6m"]
NAME = {"on": "always on", "gate-6s6": "each decides", "caller-6s6": "caller decides", "caller-6s6m": "caller + est. fix",
        "both-6s6": "two bits", "both-6s6m": "two bits + est. fix", "offm": "off + est. fix", "offp": "off, Python est."}
out = {}
# control: the Python estimator unchanged against off
o, p = S.load("off", "normal"), S.load("offp", "normal")
same = sum(S.t(p[k]) == S.t(o[k]) and p[k]["complete"] == o[k]["complete"] for k in p)
print(f"control offp vs off: {same}/{len(p)} sessions identical; max |dt| {max(abs(S.t(p[k])-S.t(o[k])) for k in p):.2f} s")
for cond, arms in [("lost", ARMS), ("normal", ARMS+["offm", "offp"]), ("qrm-first", ARMS), ("qrm-noise", ARMS), ("qrm-fsk", ARMS)]:
    off = S.load("off", cond)
    data = {a: S.load(a, cond) for a in arms}
    print(f"\n## {cond}\n\n| Channel | n | off mean (done) | " + " | ".join(NAME[a] for a in arms) + " |\n|---|---:|---:|" + "---:|"*len(arms))
    for pt in ORDER:
        keys = sorted(k for k in off if k[0] == pt and all(k in d for d in data.values()))
        if not keys:
            continue
        m0 = sum(S.t(off[k]) for k in keys)/len(keys)
        cells = []
        for a in arms:
            d = data[a]
            dm = sum(S.t(d[k]) for k in keys)/len(keys)-m0
            done = sum(d[k]["complete"] for k in keys)
            out[f"{cond}|{pt}|{a}"] = dict(n=len(keys), dmean=dm, done=done)
            cells.append(f"{dm:+.1f} ({done})")
        out[f"{cond}|{pt}|off"] = dict(n=len(keys), mean=m0, done=sum(off[k]["complete"] for k in keys))
        print(f"| {LABEL[pt]} | {len(keys)} | {m0:.1f} ({sum(off[k]['complete'] for k in keys)}) | " + " | ".join(cells) + " |")
# the spread ceiling in connect-frame readings, caller side, native against the fixed Python estimator
print("\n## 12 Hz readings of the connect frame (first try lost, both seed sets): native estimator -> with the fix\n")
a, b = S.load("caller-6s6", "lost"), S.load("caller-6s6m", "lost")
c = collections.defaultdict(lambda: [0, 0, 0])
for k in a:
    if k in b:
        for i in a[k]["dec"]:
            if i in b[k]["dec"]:
                v = c[k[0]]; v[0] += 1; v[1] += (a[k]["dec"][i][2] or 0) >= 11.99; v[2] += (b[k]["dec"][i][2] or 0) >= 11.99
print(" | ".join(f"{LABEL[p]}: {c[p][1]}->{c[p][2]}/{c[p][0]}" for p in ORDER if p in c))
json.dump(out, open(S.HERE/"summary-all-arms.json", "w"), indent=1)
