"""Run/analyze a fixed natural-loss weak-channel matrix using the existing Lab.

All attempts count. First CONNECT and DISC policy opportunities are tracked
jointly; unchanged early paths must match, including wholly unexposed pairs.
Raw execution-time indexes are retained unchanged.
"""
import argparse
import hashlib
import json
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CELLS = (("awgn", -16, 2001), ("awgn", -14, 2101), ("mpp", -12, 2201), ("mpp", -8, 2301))
SEEDS = 32
ARMS = ("shipped", "alternating_cpm")
INPUTS = ("channel", "snr_db", "seed", "bytes_each_way", "horizon_s", "cfo_hz", "bandwidth_cap",
          "sample_rate", "pool_threads", "dd_enabled", "dd_budget_s")
PROTOCOL = ("outcome", "connected", "delivered", "acknowledged", "disconnected", "connect_s", "delivery_s",
            "ack_s", "simulated_s", "verified_at_a", "verified_at_b", "acknowledged_ab_bytes",
            "acknowledged_ba_bytes", "a_tx_bursts", "b_tx_bursts", "a_heard", "b_heard", "a_lost", "b_lost", "events")


def opportunities(record):
    return [(i, t) for i, t in enumerate(record["transmission_trace"])
            if t["endpoint"] == "A" and t["frame"] in ("CONNECT", "DISC")
            and t["occurrence"] >= 3 and t["occurrence"] % 2 == 1]


def classify_pair(a, b):
    if any(a[k] != b[k] for k in INPUTS):
        raise ValueError("paired inputs differ")
    selected = []
    for r, arm in zip((a, b), ARMS):
        if r["caller_retry_policy"] != arm or r["suppression_plan"] or r["suppressed_bursts"]:
            raise ValueError("not an unsuppressed natural-loss paired arm")
        if any(t["suppressed"] for t in r["transmission_trace"]):
            raise ValueError("suppressed transmission in natural-loss trial")
        choices = opportunities(r)
        expected = "fsk16r25-r1/2" if arm == "shipped" else "fsk8r50-r1/3"
        if any(t["mode"] != expected for _, t in choices):
            raise ValueError("unexpected retry policy mode")
        selected.append(choices)
    x, y = selected
    first_phase = x[0][1]["frame"] if x else (y[0][1]["frame"] if y else None)
    if not x and not y:
        identical = (a["transmission_trace"] == b["transmission_trace"] and all(a[k] == b[k] for k in PROTOCOL))
        status = "unexposed_identical" if identical else "unexposed_mismatch"
    elif not x or not y:
        status = "prechange_mismatch"
    else:
        (ia, ta), (ib, tb) = x[0], y[0]
        tag = lambda t: (t["frame"], t["occurrence"], t["channel_first_sample"])
        matched = a["transmission_trace"][:ia] == b["transmission_trace"][:ib] and tag(ta) == tag(tb)
        status = "exposed_prefix_matched" if matched else "prechange_mismatch"
    return dict(status=status, first_phase=first_phase,
                exposure={arm: {frame.lower(): sum(t["frame"] == frame for _, t in choices)
                                for frame in ("CONNECT", "DISC")}
                          for arm, choices in zip(ARMS, selected)})


def outcome(record):
    confirmed = record["disconnected"] and "A DISCONNECTED CLIENT" in record["events"]
    complete = record["outcome"] == "complete"
    return dict(outcome=record["outcome"], connected=record["connected"], delivered=record["delivered"],
                acknowledged=record["acknowledged"], complete=complete, confirmed_complete=complete and confirmed,
                connect_s=record["connect_s"], simulated_s=record["simulated_s"],
                capped_connection_wait_s=record["connect_s"] if record["connected"] else record["horizon_s"],
                capped_confirmed_completion_wait_s=record["simulated_s"] if complete and confirmed else record["horizon_s"],
                delivered_bytes=record["verified_at_a"] + record["verified_at_b"])


def summarize(pairs):
    out = dict(pairs=len(pairs), classification=dict(Counter(p["status"] for p in pairs)),
               first_exposed_phase=dict(Counter(p["first_phase"] for p in pairs if p["status"] == "exposed_prefix_matched")))
    for arm in ARMS:
        rows = [p["arms"][arm] for p in pairs]
        out[arm] = {k: sum(r[k] for r in rows) for k in ("connected", "delivered", "acknowledged", "complete", "confirmed_complete", "delivered_bytes")}
        out[arm].update({k: statistics.mean(r[k] for r in rows)
                         for k in ("capped_connection_wait_s", "capped_confirmed_completion_wait_s")})
    out["discordant"] = {}
    for metric in ("connected", "confirmed_complete"):
        out["discordant"][metric] = {"candidate_only": sum(p["arms"][ARMS[1]][metric] and not p["arms"][ARMS[0]][metric] for p in pairs),
                                     "shipped_only": sum(p["arms"][ARMS[0]][metric] and not p["arms"][ARMS[1]][metric] for p in pairs)}
    for metric, flag in (("connect_s", "connected"), ("simulated_s", "confirmed_complete")):
        values = [p["arms"][ARMS[1]][metric] - p["arms"][ARMS[0]][metric] for p in pairs
                  if all(p["arms"][arm][flag] for arm in ARMS)]
        out[metric + "_paired_delta"] = dict(n=len(values), median=statistics.median(values) if values else None,
                                              min=min(values) if values else None, max=max(values) if values else None)
    return out


def run(binary, output):
    output.mkdir(parents=True, exist_ok=False)
    plan = dict(head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), seeds_per_cell=SEEDS,
                scenario="natural", bytes_each_way=64, horizon_s=180, cfo_hz=4.5, pool_threads=1,
                cells=[dict(channel=c, snr_db=s, first_seed=n) for c, s, n in CELLS])
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    for channel, snr, seed in CELLS:
        subprocess.run([sys.executable, str(ROOT / "native/lab/study_retries.py"), "--binary", str(binary),
                        "--output", str(output / f"{channel}_{snr}"), "--scenario", "natural", "--channels", channel,
                        "--snrs", str(snr), "--first-seed", str(seed), "--seeds", str(SEEDS)], cwd=ROOT, check=True)


def analyze(raw, output):
    output.mkdir(parents=True, exist_ok=False)
    pairs, cells, executions = [], [], {}
    plan = json.loads((raw / "plan.json").read_text())
    expected_cells = [dict(channel=c, snr_db=s, first_seed=n) for c, s, n in CELLS]
    if plan["cells"] != expected_cells or plan["seeds_per_cell"] != SEEDS:
        raise ValueError("plan differs from fixed matrix")
    for channel, snr, seed in CELLS:
        folder = raw / f"{channel}_{snr}"
        meta = json.loads((folder / "metadata.json").read_text())
        executions[folder.name] = meta
        settings = meta["settings"]
        if (settings["scenario"], settings["first_seed"], settings["seeds"]) != ("natural", seed, SEEDS):
            raise ValueError("execution differs from fixed matrix")
        if meta["binary_sha256"] != plan["binary_sha256"]:
            raise ValueError("binary changed within study")
        cell_pairs = []
        for case_seed in range(seed, seed + SEEDS):
            records = {arm: json.loads((folder / f"natural_{channel}_{snr}_{case_seed}_{arm}.json").read_text()) for arm in ARMS}
            a, b = (records[arm] for arm in ARMS)
            if (a["channel"], a["snr_db"], a["seed"]) != (channel, snr, case_seed):
                raise ValueError("record differs from requested point")
            expected = dict(bytes_each_way=64, horizon_s=180, cfo_hz=4.5, bandwidth_cap=2,
                            sample_rate=8000, pool_threads=1, dd_enabled=True, dd_budget_s=1)
            if any(a[k] != v for k, v in expected.items()):
                raise ValueError("record differs from declared study settings")
            pair = dict(channel=channel, snr_db=snr, seed=case_seed, **classify_pair(a, b),
                        arms={arm: outcome(r) for arm, r in records.items()},
                        raw_reports={arm: str(Path(folder.name) / f"natural_{channel}_{snr}_{case_seed}_{arm}.json") for arm in ARMS})
            pairs.append(pair); cell_pairs.append(pair)
        cells.append(dict(channel=channel, snr_db=snr, first_seed=seed, **summarize(cell_pairs)))
    (output / "pairs.jsonl").write_text("".join(json.dumps(p) + "\n" for p in pairs))
    (output / "summary.json").write_text(json.dumps(cells, indent=2) + "\n")
    (output / "metadata.json").write_text(json.dumps(dict(plan=plan, executions=executions,
        analysis_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        analysis_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()), indent=2) + "\n")
    for c in cells:
        print(c["channel"], c["snr_db"], c["classification"], "first phase", c["first_exposed_phase"],
              "connected", c[ARMS[0]]["connected"], c[ARMS[1]]["connected"],
              "confirmed complete", c[ARMS[0]]["confirmed_complete"], c[ARMS[1]]["confirmed_complete"], flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    execute = sub.add_parser("run")
    execute.add_argument("--binary", type=Path, required=True)
    execute.add_argument("--output", type=Path, required=True)
    report = sub.add_parser("analyze")
    report.add_argument("raw", type=Path)
    report.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.action == "run":
        run(args.binary.resolve(strict=True), args.output.resolve())
    else:
        analyze(args.raw, args.output)


if __name__ == "__main__":
    main()
