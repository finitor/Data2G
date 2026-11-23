"""Read-only exposure audit of saved session traces, without rerunning DSP.

python scripts/audit_session_overlap.py saved-sessions.jsonl --out audit.json
No sender labels are needed: any overlapping transmissions violate the
ideal carrier-sense model used for these particular traces. This does not
infer the cause of every overlap, nor revised session outcomes.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('input', type=Path)
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    groups = defaultdict(lambda: dict(sessions=0, overlap_sessions=0, overlap_pairs=0, affected=[]))
    for line in a.input.read_text().splitlines():
        row = json.loads(line)
        arm = groups[row['arm']]
        arm['sessions'] += 1
        spans = row['trace']
        pairs = [(j, i) for i, x in enumerate(spans) for j, y in enumerate(spans[:i])
                 if x['start'] < y['end'] and y['start'] < x['end']]
        if pairs:
            arm['overlap_sessions'] += 1
            arm['overlap_pairs'] += len(pairs)
            arm['affected'].append(dict(point=row['point'], seed=row['seed'], pairs=pairs))
    out = dict(input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(), arms=dict(groups))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=2) + '\n')
    for arm, counts in groups.items():
        print(repr(arm), {k:v for k,v in counts.items() if k != 'affected'})


if __name__ == '__main__':
    main()
