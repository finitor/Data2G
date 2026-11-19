"""Paired, sequential session-retry study using the existing native Lab CLI.

Keep incomplete cases, stdout and progress logs. Only the caller's retry
policy changes; both arms use identical channel/noise/payload seeds. Once
their TX schedules diverge they sample different parts of the shared
continuous fading/noise timeline. This is not a fixed-audio decoder test.
"""

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = {"natural": (), "connect": ("A:CONNECT:1", "A:CONNECT:2"),
             "connect_ack": ("B:CONNECT_ACK:1", "B:CONNECT_ACK:2"),
             "disc": ("A:DISC:1", "A:DISC:2"), "disc_ack": ("B:DISC_ACK:1", "B:DISC_ACK:2"),
             "connect_ack_after_loss": ("A:CONNECT:1", "B:CONNECT_ACK:1"),
             "disc_ack_after_loss": ("A:DISC:1", "B:DISC_ACK:1")}


def exposure(record, scenario, arm):
    """Require the selected policy decision *after* all requested erasures.

    Lost ACKs can occur on later caller attempts after natural failures:
    reaching caller occurrence 3 alone does not establish this condition.
    """
    target = "DISC" if scenario.startswith("disc") else "CONNECT"
    expected = "fsk8r50-r1/3" if arm == "alternating_cpm" else "fsk16r25-r1/2"
    trace = record["transmission_trace"]
    changed = [t for t in trace if t["endpoint"] == "A" and t["frame"] == target
               and t["occurrence"] >= 3 and t["occurrence"] % 2 == 1 and not t["suppressed"]]
    forced = [t["channel_first_sample"] + t["samples"] for t in trace if t["suppressed"]]
    last_loss = max(forced, default=0)
    opportunity = next((t for t in changed if t["mode"] == expected and t["channel_first_sample"] >= last_loss), None)
    eligible = record["suppression_plan_applied"] and opportunity is not None
    closure_confirmed = record["disconnected"] and "A DISCONNECTED CLIENT" in record["events"]
    recovered = closure_confirmed if scenario.startswith("disc") else record["connected"]
    end = record["simulated_s"] if scenario.startswith("disc") else record["connect_s"]
    start = opportunity["channel_first_sample"] / record["sample_rate"] if opportunity else None
    return {"eligible": eligible, "plan_applied": record["suppression_plan_applied"],
            "closure_confirmed": closure_confirmed,
            "confirmed_complete": record["outcome"] == "complete" and closure_confirmed,
            "policy_opportunity": opportunity, "stage_recovered": eligible and recovered,
            "stage_recovery_s": end - start if eligible and recovered else None}


def matching_prefix(a, b, scenario):
    """Verify paired channel history and start time before the first changed decision."""
    target = "DISC" if scenario.startswith("disc") else "CONNECT"
    def prefix(r):
        for i, t in enumerate(r["transmission_trace"]):
            if t["endpoint"] == "A" and t["frame"] == target and t["occurrence"] == 3:
                return r["transmission_trace"][:i], t["channel_first_sample"]
        return None
    pa, pb = prefix(a), prefix(b)
    return pa is not None and pb is not None and pa == pb


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True, help="new result directory")
    ap.add_argument("--channels", nargs="+", default=["hilat-d"])
    ap.add_argument("--snrs", nargs="+", type=float, default=[0, 12])
    ap.add_argument("--first-seed", type=int, default=1)
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--horizon", type=int, default=180)
    ap.add_argument("--scenario", choices=SCENARIOS, default="natural")
    args = ap.parse_args()
    if args.seeds < 1 or args.first_seed < 0:
        ap.error("positive seed count and nonnegative first seed required")
    binary = args.binary.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    # Hash actual sources, including study files, even in an uncommitted tree.
    sources = sorted(p for base in ("native/core", "native/lab")
                     for p in (ROOT / base).rglob("*")
                     if p.is_file() and p.suffix in (".cpp", ".hpp", ".py", ".txt"))
    metadata = {
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "platform": platform.platform(),
        "settings": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "limits": ["mean-power normalized, SNR in 2500 Hz; not PEP matched",
                   "synchronous engines, production DD wall-time budget; not live deadlines",
                   "64 random bytes each direction; short sessions, not sustained throughput",
                   "forced-loss scenarios measure conditional recovery, not natural-loss reliability",
                   "Gaussian fading and white noise; no impulsive atmospheric noise or RF hardware"],
    }
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    rows = []
    pairs = []
    ordinal = 0
    for channel in args.channels:
        for snr in args.snrs:
            for seed in range(args.first_seed, args.first_seed + args.seeds):
                arms = ("shipped", "alternating_cpm") if ordinal % 2 == 0 else ("alternating_cpm", "shipped")
                ordinal += 1
                records, pair_rows = {}, {}
                for arm in arms:
                    label = f"{args.scenario}_{channel}_{snr:g}_{seed}_{arm}"
                    cmd = [str(binary), "--channel", channel, "--snr", str(snr), "--seed", str(seed),
                           "--horizon", str(args.horizon), "--cfo", "4.5", "--bytes", "64", "--threads", "1"]
                    if arm == "alternating_cpm":
                        cmd.append("--alternate-retries")
                    for suppression in SCENARIOS[args.scenario]:
                        cmd += ["--suppress", suppression]
                    with (args.output / (label + ".json")).open("w") as out, (args.output / (label + ".log")).open("w") as log:
                        result = subprocess.run(cmd, stdout=out, stderr=log, timeout=600)
                    record = json.loads((args.output / (label + ".json")).read_text())
                    if result.returncode not in (0, 1) or record["caller_retry_policy"] != arm:
                        raise RuntimeError(f"invalid study result: {label}, exit {result.returncode}")
                    row = {k: record[k] for k in ("channel", "snr_db", "seed", "caller_retry_policy", "outcome",
                                                  "connected", "delivered", "acknowledged", "disconnected",
                                                  "connect_s", "delivery_s", "ack_s", "simulated_s")}
                    row["command"] = cmd
                    row["exit_code"] = result.returncode
                    row["scenario"] = args.scenario
                    row.update(exposure(record, args.scenario, arm))
                    records[arm], pair_rows[arm] = record, row
                    rows.append(row)
                    with (args.output / "cases.jsonl").open("a") as index:
                        index.write(json.dumps(row) + "\n")
                    print(f"{label}: {record['outcome']}, eligible={row['eligible']}, connect={record['connect_s']:g}s, end={record['simulated_s']:g}s", flush=True)
                pair = {"scenario": args.scenario, "channel": channel, "snr_db": snr, "seed": seed,
                        "prefix_matches": matching_prefix(records["shipped"], records["alternating_cpm"], args.scenario),
                        "both_eligible": all(r["eligible"] for r in pair_rows.values())}
                pair["conditional_comparison_valid"] = pair["prefix_matches"] and pair["both_eligible"]
                pair["arms"] = {arm: {k: row[k] for k in ("eligible", "stage_recovered", "stage_recovery_s", "outcome", "confirmed_complete")}
                                for arm, row in pair_rows.items()}
                pairs.append(pair)
                with (args.output / "pairs.jsonl").open("a") as index:
                    index.write(json.dumps(pair) + "\n")
    summary = []
    for channel in args.channels:
        for snr in args.snrs:
            for arm in ("shipped", "alternating_cpm"):
                group = [r for r in rows if (r["channel"], r["snr_db"], r["caller_retry_policy"]) == (channel, snr, arm)]
                complete = [r for r in group if r["outcome"] == "complete"]
                summary.append({"scenario": args.scenario, "channel": channel, "snr_db": snr, "arm": arm, "n": len(group),
                                "connected": sum(r["connected"] for r in group),
                                "delivered": sum(r["delivered"] for r in group), "complete": len(complete),
                                "eligible": sum(r["eligible"] for r in group),
                                "confirmed_complete": sum(r["confirmed_complete"] for r in group),
                                "stage_recovered_eligible": sum(r["stage_recovered"] for r in group),
                                "median_end_s_complete_only": statistics.median(r["simulated_s"] for r in complete) if complete else None})
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.output / "pair-summary.json").write_text(json.dumps({
        "pairs": len(pairs), "valid_conditional_pairs": sum(p["conditional_comparison_valid"] for p in pairs),
        "by_arm_on_valid_pairs": {arm: {
            "stage_recovered": sum(p["arms"][arm]["stage_recovered"] for p in pairs if p["conditional_comparison_valid"]),
            "complete": sum(p["arms"][arm]["outcome"] == "complete" for p in pairs if p["conditional_comparison_valid"])}
            for arm in ("shipped", "alternating_cpm")}}, indent=2) + "\n")


if __name__ == "__main__":
    main()
