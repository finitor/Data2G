"""Streaming adapter for phy_session.ContinuousChannel's existing tap process.

The finite Hilbert filter adds latency; it does not regenerate or normalize
fades per block/burst.  Noise is continuous and referenced to normalized TX
power 0.01 in 2500 Hz. The adapter runs at 48 kHz, in 10 ms blocks.

The channel generator is imported from STREAM_SESSION_CHANNEL (a Data2G
checkout; default: this one), so a study can pin the channel to one revision
while it changes the modem (endpoint_data2g.py: STREAM_SESSION_MODEM).
"""
import os
import sys
from pathlib import Path
import numpy as np
from scipy import signal

D2G = Path(os.environ.get("STREAM_SESSION_CHANNEL") or Path(__file__).resolve().parents[2])
sys.path[:0] = [str(D2G), str(D2G / "scripts")]
from phy_session import ContinuousChannel

FS, BLOCK, POWER, HORIZON = 48000, 480, 0.01, 240.0
# The interfering tone: its (mean) power over the noise in 50 Hz, as data2g.interference's
# Qrm("carrier", ...) defines one (CARRIER_REF_HZ). Generated here, not rendered by that module:
# it runs at the modem's 8 kHz, and this tone's phase and seeds are what the recorded studies used.
CARRIER_HZ, CARRIER_INR_DB = 1573.4, 12.0


class StreamingChannel:
    def __init__(self, dop, delay_ms, snr, seed, carrier=False, cfo=4.5):
        self.original = ContinuousChannel("comparison", snr, seed, HORIZON,
                                          doppler=dop, delay_ms=delay_ms)
        # Cache exactly the arrays np.interp otherwise copies every 10 ms.
        self.tap_grid = np.arange(len(self.original.g[0]), dtype=np.float64) if dop else None
        self.tap_parts = [(np.ascontiguousarray(g.real), np.ascontiguousarray(g.imag))
                          for g in self.original.g] if dop else []
        self.dop, self.cfo = dop, cfo
        self.delay = round(delay_ms * FS / 1000)
        self.n = 0
        # carrier: False, True (a steady tone) or a Doppler spread in Hz as a float (the tone
        # itself fades: one Rayleigh path per receiver, unit mean power, from the same generator
        # and Doppler convention as the signal's taps, independently seeded)
        self.carrier = bool(carrier)
        self.cdop = 0.0 if isinstance(carrier, bool) else float(carrier)
        if self.cdop:
            self.cfade = [ContinuousChannel("comparison", snr, seed + 5000000 + i, HORIZON, doppler=self.cdop, delay_ms=0.0)
                          for i in range(2)]
            self.cgrid = np.arange(len(self.cfade[0].g[0]), dtype=np.float64)
        self.sigma = np.sqrt(POWER * (FS / 2) / 2500 / 10**(snr/10))
        self.rng = [np.random.default_rng(np.random.SeedSequence([seed, 7000000, i])) for i in range(2)]
        self.phase = [np.random.default_rng(seed+9000000+i).uniform(0, 2*np.pi) for i in range(2)]
        k = np.arange(-256, 257)
        self.h = np.zeros(len(k))
        odd = k % 2 != 0
        self.h[odd] = 2/(np.pi*k[odd])
        self.h *= np.kaiser(len(k), 8.6)
        self.hdelay = 256
        self.zi = [np.zeros(len(self.h)-1) for _ in range(2)]
        self.real_history = [np.zeros(self.hdelay) for _ in range(2)]
        self.echo_history = [np.zeros(self.delay, complex) for _ in range(2)]

    def process(self, outputs):
        n = len(outputs[0])
        t = (self.n + np.arange(n))/FS
        source_time = np.maximum(t-self.hdelay/FS, 0)
        if self.dop:
            tl = source_time*self.original.rate
            gs = [np.interp(tl, self.tap_grid, real) +
                  1j*np.interp(tl, self.tap_grid, imag) for real, imag in self.tap_parts]
        result = []
        for source in range(2):
            x = np.asarray(outputs[source])
            im, self.zi[source] = signal.lfilter(self.h, [1.0], x, zi=self.zi[source])
            r = np.concatenate([self.real_history[source], x])
            self.real_history[source] = r[-self.hdelay:].copy()
            z = r[:n] + 1j*im
            if self.dop:
                delayed = np.concatenate([self.echo_history[source], z])
                self.echo_history[source] = delayed[-self.delay:].copy() if self.delay else np.array([], complex)
                z = (z*gs[0] + delayed[:n]*gs[1])/np.sqrt(2)
            z *= np.exp(2j*np.pi*self.cfo*t)
            dest = 1-source
            y = z.real + self.rng[dest].normal(0, self.sigma, n)
            if self.carrier:
                amp = np.sqrt(2*self.sigma**2 * 50/(FS/2) * 10**(CARRIER_INR_DB/10))
                if self.cdop:
                    g = self.cfade[dest].g[0]
                    tc = t*self.cfade[dest].rate
                    gc = np.interp(tc, self.cgrid, g.real) + 1j*np.interp(tc, self.cgrid, g.imag)
                    y += amp*(gc*np.exp(1j*(2*np.pi*CARRIER_HZ*t+self.phase[dest]))).real
                else:
                    y += amp*np.cos(2*np.pi*CARRIER_HZ*t+self.phase[dest])
            result.append(y)
        self.n += n
        return result[::-1]
