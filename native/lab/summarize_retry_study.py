"""Reanalyze retained raw reports, preserving the original execution indexes.

Usage: python3 native/lab/summarize_retry_study.py RAW_ROOT NEW_OUTPUT
Both original and subsequent mixed request/ACK scenarios use one analysis
version. No modem execution is performed. Copies of the raw runs remain
the authority for execution identity and outcomes.
"""
import argparse
import hashlib
import json
import statistics
import subprocess
from pathlib import Path

from study_retries import SCENARIOS, exposure, matching_prefix


def median(values):
    return statistics.median(values) if values else None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_root", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows, pairs, executions = [], [], {}
    for folder in sorted(args.raw_root.iterdir()):
        if not folder.is_dir() or not (folder / "metadata.json").exists():
            continue
        executions[folder.name] = json.loads((folder / "metadata.json").read_text())
        records = {}
        for line in (folder / "cases.jsonl").read_text().splitlines():
            old = json.loads(line)
            scenario, channel, snr, seed, arm = (old[k] for k in ("scenario", "channel", "snr_db", "seed", "caller_retry_policy"))
            name = f"{scenario}_{channel}_{snr:g}_{seed}_{arm}.json"
            record = json.loads((folder / name).read_text())
            requested = [dict(zip(("endpoint", "frame", "occurrence"), (p.split(":")[0], p.split(":")[1], int(p.split(":")[2]))))
                         for p in SCENARIOS[scenario]]
            actual = [{k: p[k] for k in ("endpoint", "frame", "occurrence")} for p in record["suppression_plan"]]
            if requested != actual or record["caller_retry_policy"] != arm:
                raise ValueError(f"scenario or policy mismatch: {folder / name}")
            row = dict(old)
            row.update(exposure(record, scenario, arm))
            row["raw_report"] = str(Path(folder.name) / name)
            rows.append(row)
            records.setdefault((scenario, channel, snr, seed), {})[arm] = (record, row)
        for key, arms in records.items():
            if set(arms) != {"shipped", "alternating_cpm"}:
                raise ValueError(f"missing paired arm: {folder} {key}")
            valid = (all(v[1]["eligible"] for v in arms.values())
                     and matching_prefix(arms["shipped"][0], arms["alternating_cpm"][0], key[0]))
            pairs.append(dict(zip(("scenario", "channel", "snr_db", "seed"), key),
                              conditional_comparison_valid=valid,
                              arms={arm: row for arm, (_, row) in arms.items()}))
    cells = []
    for key in sorted({(p["scenario"], p["channel"], p["snr_db"]) for p in pairs}):
        group = [p for p in pairs if (p["scenario"], p["channel"], p["snr_db"]) == key]
        valid = [p for p in group if p["conditional_comparison_valid"]]
        cell = dict(zip(("scenario", "channel", "snr_db"), key), pairs=len(group), valid_conditional_pairs=len(valid))
        cell["valid_pairs_with_retry_overlapping_erased_tx"] = sum(
            any(r["opportunity_overlaps_suppressed_tx"] for r in p["arms"].values()) for p in valid)
        for arm in ("shipped", "alternating_cpm"):
            arm_rows = [p["arms"][arm] for p in group]
            cell[arm] = {"connected_all": sum(r["connected"] for r in arm_rows),
                         "complete_all": sum(r["outcome"] == "complete" for r in arm_rows),
                         "confirmed_complete_all": sum(r["confirmed_complete"] for r in arm_rows),
                         "stage_recovered_valid": sum(p["arms"][arm]["stage_recovered"] for p in valid)}
        cell["median_stage_delta_candidate_minus_shipped_s"] = median([
            p["arms"]["alternating_cpm"]["stage_recovery_s"] - p["arms"]["shipped"]["stage_recovery_s"]
            for p in valid if all(r["stage_recovered"] for r in p["arms"].values())])
        cell["median_end_delta_both_confirmed_complete_s"] = median([
            p["arms"]["alternating_cpm"]["simulated_s"] - p["arms"]["shipped"]["simulated_s"]
            for p in valid if all(r["confirmed_complete"] for r in p["arms"].values())])
        cells.append(cell)
    for name, data in (("cases", rows), ("pairs", pairs)):
        (args.output / (name + ".jsonl")).write_text("".join(json.dumps(r) + "\n" for r in data))
    (args.output / "summary.json").write_text(json.dumps(cells, indent=2) + "\n")
    analysis = {"analysis_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "analysis_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in (Path(__file__), Path(__file__).with_name("study_retries.py"))},
                "executions": executions}
    (args.output / "metadata.json").write_text(json.dumps(analysis, indent=2) + "\n")
    print(f"Reanalyzed {len(rows)} sessions / {len(pairs)} pairs; valid conditional pairs: {sum(p['conditional_comparison_valid'] for p in pairs)}")
    for c in cells:
        print(c["scenario"], c["channel"], c["snr_db"], "valid", c["valid_conditional_pairs"],
              "stage", c["shipped"]["stage_recovered_valid"], c["alternating_cpm"]["stage_recovered_valid"],
              "complete", c["shipped"]["complete_all"], c["alternating_cpm"]["complete_all"],
              "confirmed", c["shipped"]["confirmed_complete_all"], c["alternating_cpm"]["confirmed_complete_all"])


if __name__ == "__main__":
    main()
