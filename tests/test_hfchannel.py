"""data2g.hfchannel: the fading simulator's Doppler spread."""

import numpy as np
import pytest
from scipy import signal

from data2g.config import FS
from data2g.hfchannel import FADING_PRESETS, _gaussian_taps, fading


@pytest.mark.parametrize("spread", [0.1, 1.0, 2.0])
def test_gaussian_taps_match_f1487_spread(spread):
    """F.1487 defines the frequency spread as 2 sigma of a Gaussian
    Doppler spectrum. The SSTVAE generator this replaced read 3.0 Hz
    at a 2 Hz setting."""
    g = _gaussian_taps(int(FS * 600 / spread), spread, np.random.default_rng(1))[::40]
    P = np.abs(np.fft.fft(g)) ** 2
    f = np.fft.fftfreq(len(g), 40 / FS)
    two_sigma = 2 * np.sqrt(np.sum(P * f**2) / np.sum(P))
    assert abs(two_sigma / spread - 1) < 0.05
    assert abs(np.mean(np.abs(g) ** 2) - 1) < 0.1  # unit power in expectation only


@pytest.mark.parametrize("name, doppler, delay_ms", [("mpa", 0.25, 2.0), ("mpl", 0.3, 3.5)])
def test_onair_presets_render(name, doppler, delay_ms):
    """The on-air presets, through fading() itself: the second path at the
    intended delay, and the fade at the intended Doppler (2 sigma)."""
    p = FADING_PRESETS[name]
    assert (p.doppler_hz, p.delay_ms) == (doppler, delay_ms)
    rng = np.random.default_rng(3)
    # delay: per-second cross-correlation power of white noise against its faded copy
    x = rng.normal(size=FS * 60)
    zx, zy = signal.hilbert(x), signal.hilbert(fading(x, name, seed=4))
    lags = np.arange(64)
    pw = [np.sum(np.abs((zy[k:] * np.conj(zx[:len(zx) - k]))[:FS * 59].reshape(59, FS).sum(1)) ** 2) for k in lags]
    assert set(np.argsort(pw)[-2:]) == {0, round(delay_ms * 1e-3 * FS)}
    # Doppler: a 1500 Hz tone's complex gain, its spectrum's 2 sigma
    t = np.arange(int(FS * 600 / doppler))
    g = (signal.hilbert(fading(np.cos(2 * np.pi * 1500 * t / FS), name, seed=5)) * np.exp(-2j * np.pi * 1500 * t / FS))[::40]
    P = np.abs(np.fft.fft(g)) ** 2
    f = np.fft.fftfreq(len(g), 40 / FS)
    m = np.abs(f) < 5  # the fade, not the Hilbert transform's edge leakage
    assert abs(2 * np.sqrt(np.sum((P * f**2)[m]) / np.sum(P[m])) / doppler - 1) < 0.1
