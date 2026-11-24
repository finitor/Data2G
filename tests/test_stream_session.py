"""scripts/stream_session: two live Engines over the streaming channel (native DSP).

Whole sessions on one sample clock, so what only a live audio path shows is
under test: carrier sense, CW ID sense and the timers against air time.
Each trial is its own process (run_sessions.py), as a study runs it.
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


@pytest.mark.hf_only("the channel points and the 2400 Hz cap are HF's")
@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="CwSense reads a weak or fading carrier near the centre as a CW ID (#302)")
def test_a_session_completes_under_a_fading_carrier(native, tmp_path):
    """2 ms / 1 Hz fading at -6 dB with an unkeyed 1573.4 Hz carrier, itself
    fading at 1 Hz, at a mean 12 dB over the noise in 50 Hz. CwSense reads
    it as a CW ID a couple of hundred times in three minutes; each reading
    holds transmission and moves the reply deadline on (Session.on_cw), so
    retries never go out: 1 of 8 seeds completed, and none at 10 Hz. With
    the carrier rejected this seed completes at 70 s."""
    row = trial(tmp_path, "carrier-fade1", 125007, horizon=120)
    assert row["delivered"] == [64, 64] and row["complete"]
