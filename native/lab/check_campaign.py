"""Compare the native CPM campaign grid with the public study's actual function.

Only its AST function is evaluated; no study, training, or Python modem runs.
Usage: python native/lab/check_campaign.py path/to/data2g-lab
"""
import ast
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

root = Path(__file__).resolve().parents[2]
source = ast.parse((root / 'scripts/cpm_floor_study.py').read_text())
function = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'e2e_grid')
namespace = {'np': np}
exec(compile(ast.Module(body=[function], type_ignores=[]), 'e2e_grid', 'exec'), namespace)
rows = [json.loads(line) for line in subprocess.check_output(
    [sys.argv[1], '--list-campaign', 'cpm_floor', '--trials', '2', '--seed', '50000'], text=True).splitlines()]
assert len(rows) == 1116
modes = list(dict.fromkeys(row['fixed_mode'] for row in rows))
assert len(modes) == 6
channels = ['awgn', 'mpg', 'mpp', 'mpd', 'flutter', 'nvis', 'hilat']
expected = [(mode, channel, float(snr), seed) for mode in modes for channel in channels
            for snr in namespace['e2e_grid'](mode, channel) for seed in [50000, 50001]]
assert [(r['fixed_mode'], r['channel'], r['snr_db'], r['seed']) for r in rows] == expected
assert all(r['cfo_hz'] == 4.5 and r['workload_kind'] == 'cpm_receiver_burst' for r in rows)
for plan, count, channels in [('hf_sessions', 560, 10), ('hf_extreme', 224, 4)]:
    cases = [json.loads(line) for line in subprocess.check_output([sys.argv[1], '--list-campaign', plan], text=True).splitlines()]
    assert len(cases) == count
    assert len({r['channel'] for r in cases}) == channels
    assert len({r['fixed_mode'] for r in cases}) == 7
print('CPM grid matches public e2e_grid for all six modes, seven channels and paired seeds; HF session matrices complete')
