"""scripts/stream_session: two live Engines over the streaming channel (native DSP).

A smoke test of the study harness: one trial as a study runs it, in its own
process (run_sessions.py). What the harness finds is tested where it lives,
in process (a carrier read as a CW ID: tests/test_cwid.py).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

RUN = Path(__file__).parents[1] / "scripts/stream_session/run_sessions.py"


def trial(tmp_path, point, seed, horizon=180):
    """One trial's row (run_sessions.run)."""
    out = tmp_path / "sessions"
    subprocess.run([sys.executable, str(RUN), "--points", point, "--trials", "1", "--seed", str(seed),
                    "--horizon", str(horizon), "--directory", str(out)], check=True, capture_output=True, timeout=600)
    return json.loads((out / f"data2g-{point}-{seed}.json").read_text())


@pytest.mark.hf_only("the channel points and the 2400 Hz cap are HF's")
def test_a_clean_session_completes_and_closes(native, tmp_path):
    """64 bytes each way at +20 dB: both exact messages delivered and
    acknowledged, then a confirmed disconnect."""
    row = trial(tmp_path, "clean", 125000)
    assert row["complete"] and row["delivered"] == [64, 64] and row["close_confirmed"]
    assert row["acknowledged_at"] < 15
