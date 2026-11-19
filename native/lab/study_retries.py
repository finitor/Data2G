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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True, help="new result directory")
    ap.add_argument("--channels", nargs="+", default=["hilat-d"])
    ap.add_argument("--snrs", nargs="+", type=float, default=[0, 12])
    ap.add_argument("--first-seed", type=int, default=1)
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--horizon", type=int, default=180)
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
                   "Gaussian fading and white noise; no impulsive atmospheric noise or RF hardware"],
    }
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    rows = []
    ordinal = 0
    for channel in args.channels:
        for snr in args.snrs:
            for seed in range(args.first_seed, args.first_seed + args.seeds):
                arms = ("shipped", "alternating_cpm") if ordinal % 2 == 0 else ("alternating_cpm", "shipped")
                ordinal += 1
                for arm in arms:
                    label = f"{channel}_{snr:g}_{seed}_{arm}"
                    cmd = [str(binary), "--channel", channel, "--snr", str(snr), "--seed", str(seed),
                           "--horizon", str(args.horizon), "--cfo", "4.5", "--bytes", "64", "--threads", "1"]
                    if arm == "alternating_cpm":
                        cmd.append("--alternate-retries")
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
                    rows.append(row)
                    with (args.output / "cases.jsonl").open("a") as index:
                        index.write(json.dumps(row) + "\n")
                    print(f"{label}: {record['outcome']}, connect={record['connect_s']:g}s, end={record['simulated_s']:g}s", flush=True)
    summary = []
    for channel in args.channels:
        for snr in args.snrs:
            for arm in ("shipped", "alternating_cpm"):
                group = [r for r in rows if (r["channel"], r["snr_db"], r["caller_retry_policy"]) == (channel, snr, arm)]
                complete = [r for r in group if r["outcome"] == "complete"]
                summary.append({"channel": channel, "snr_db": snr, "arm": arm, "n": len(group),
                                "connected": sum(r["connected"] for r in group),
                                "delivered": sum(r["delivered"] for r in group), "complete": len(complete),
                                "median_end_s_complete_only": statistics.median(r["simulated_s"] for r in complete) if complete else None})
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
