"""Sequential before/after DISC timer study; shipped retry modes in both arms."""
import argparse
import hashlib
import json
import platform
import subprocess
from pathlib import Path


PLANS = {"natural": (), "disc": ("A:DISC:1", "A:DISC:2"),
         "disc_ack": ("B:DISC_ACK:1", "B:DISC_ACK:2"),
         "mixed": ("A:DISC:1", "B:DISC_ACK:1")}
CELLS = [("natural", "clean", 30, range(101, 103)),
         ("natural", "awgn", -12, range(101, 105)),
         ("natural", "mpp", -8, range(101, 105)),
         ("natural", "awgn", -14, range(201, 209)),
         ("mixed", "awgn", -12, range(101, 105)),
         ("mixed", "mpp", -8, range(101, 105)),
         ("disc", "awgn", -12, range(101, 103)),
         ("disc_ack", "awgn", -12, range(101, 103))]


def prefix(record):
    for i, tx in enumerate(record["transmission_trace"]):
        if tx["endpoint"] == "A" and tx["frame"] == "DISC":
            return record["transmission_trace"][:i + 1]
    return None


def overlaps(record):
    trace = record["transmission_trace"]
    return [{"disc": a, "ack": b,
             "overlap_s": (min(a["channel_first_sample"] + a["samples"], b["channel_first_sample"] + b["samples"])
                           - max(a["channel_first_sample"], b["channel_first_sample"])) / record["sample_rate"]}
            for a in trace if a["endpoint"] == "A" and a["frame"] == "DISC" and a["occurrence"] > 1
            for b in trace if b["endpoint"] == "B" and b["frame"] == "DISC_ACK"
            if a["channel_first_sample"] < b["channel_first_sample"] + b["samples"]
            and b["channel_first_sample"] < a["channel_first_sample"] + a["samples"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--before", type=Path, required=True)
    ap.add_argument("--after", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    binaries = {arm: getattr(args, arm).resolve(strict=True) for arm in ("before", "after")}
    args.output.mkdir(parents=True, exist_ok=False)
    metadata = {"platform": platform.platform(),
                "binary_sha256": {arm: hashlib.sha256(p.read_bytes()).hexdigest() for arm, p in binaries.items()},
                "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "limits": ["64 random bytes each way; 180-second virtual-time horizon",
                           "unit active mean power; SNR in 2500 Hz, not PEP matched",
                           "Gaussian noise/fading; no impulsive atmospheric noise or RF hardware",
                           "production DD wall-time budget; sequential unpaced engines",
                           "matching seeds, not identical received audio after schedules diverge"]}
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    pairs = []
    for scenario, channel, snr, seeds in CELLS:
        for seed in seeds:
            records, rows = {}, {}
            arms = ("before", "after") if len(pairs) % 2 == 0 else ("after", "before")
            for arm in arms:
                name = f"{scenario}_{channel}_{snr}_{seed}_{arm}"
                cmd = [str(binaries[arm]), "--channel", channel, "--snr", str(snr), "--seed", str(seed),
                       "--threads", "1", "--cfo", "4.5", "--bytes", "64", "--horizon", "180"]
                for loss in PLANS[scenario]:
                    cmd += ["--suppress", loss]
                with (args.output / f"{name}.json").open("w") as out, (args.output / f"{name}.log").open("w") as err:
                    result = subprocess.run(cmd, stdout=out, stderr=err, timeout=600)
                r = json.loads((args.output / f"{name}.json").read_text())
                if result.returncode not in (0, 1) or r["caller_retry_policy"] != "shipped":
                    raise RuntimeError(f"invalid trial: {name}, exit {result.returncode}")
                row = {k: r[k] for k in ("outcome", "connected", "delivered", "acknowledged", "disconnected",
                                         "connect_s", "delivery_s", "ack_s", "simulated_s", "suppression_plan_applied")}
                row.update(command=cmd, exit_code=result.returncode,
                           confirmed_complete=r["outcome"] == "complete" and "A DISCONNECTED CLIENT" in r["events"],
                           ack_overlaps=overlaps(r))
                records[arm], rows[arm] = r, row
                print(f"{name}: confirmed={row['confirmed_complete']}, end={r['simulated_s']:g}s, overlaps={len(row['ack_overlaps'])}", flush=True)
            pair = {"scenario": scenario, "channel": channel, "snr_db": snr, "seed": seed,
                    "first_disc_prefix_matches": prefix(records["before"]) is not None
                    and prefix(records["before"]) == prefix(records["after"]),
                    "full_trace_matches": records["before"]["transmission_trace"] == records["after"]["transmission_trace"],
                    "arms": rows}
            pairs.append(pair)
            with (args.output / "pairs.jsonl").open("a") as out:
                out.write(json.dumps(pair) + "\n")
    summary = []
    for scenario, channel, snr, _ in CELLS:
        group = [p for p in pairs if (p["scenario"], p["channel"], p["snr_db"]) == (scenario, channel, snr)]
        summary.append({"scenario": scenario, "channel": channel, "snr_db": snr, "pairs": len(group),
                        "prefix_matches": sum(p["first_disc_prefix_matches"] for p in group),
                        "full_trace_matches": sum(p["full_trace_matches"] for p in group),
                        "arms": {arm: {"confirmed_complete": sum(p["arms"][arm]["confirmed_complete"] for p in group),
                                       "plans_applied": sum(p["arms"][arm]["suppression_plan_applied"] for p in group),
                                       "pairs_with_overlap": sum(bool(p["arms"][arm]["ack_overlaps"]) for p in group)}
                                 for arm in ("before", "after")}})
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
