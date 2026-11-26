"""Streaming adapter for phy_session.ContinuousChannel's existing tap process.

The finite Hilbert filter adds latency; it does not regenerate or normalize
fades per block/burst.  Noise is continuous, in 2500 Hz, against one of two
references (the endpoint sends bursts to match):
  DATA2G_PEP_REF_DB unset  mean power 0.01: every burst is rescaled to it, so this is
                           hfchannel.awgn's SNR, the test suite's
  DATA2G_PEP_REF_DB=5      PEP-fair (upstream AGENTS.md section 11): bursts keep the
                           engine's full-scale envelope peak (1), and the noise is against
                           that peak less REF dB, as phy_session.floor_sigma sets it
The adapter runs at 48 kHz, in 10 ms blocks.

Options a point can add (run_sessions.POINTS' sixth element):
  cfo, cfo_rate  frequency offset each way (Hz) and its drift (Hz/s)
  ppm            the second station's sample clock this many ppm fast against the
                 first's: each receiver hears the other's audio time-scaled
  qrm            data2g.interference at each receiver: a preset name or
                 (kind, centre Hz, width Hz, dB over the floor, mean episode s, duty)

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
PEP_REF_DB = float(os.environ["DATA2G_PEP_REF_DB"]) if os.environ.get("DATA2G_PEP_REF_DB") else None
# The signal power the cell's SNR is against: the bursts' mean power, or a full-scale
# peak's (envelope 1: power 0.5) less PEP_REF_DB.
S_POWER = POWER if PEP_REF_DB is None else 0.5 / 10**(PEP_REF_DB/10)
# The interfering tone: its (mean) power over the noise in 50 Hz, as data2g.interference's
# Qrm("carrier", ...) defines one (CARRIER_REF_HZ). Generated here, not rendered by that module:
# it runs at the modem's 8 kHz, and this tone's phase and seeds are what the recorded studies used.
CARRIER_HZ, CARRIER_INR_DB = 1573.4, 12.0


class ClockSkew:
    """One path's sample-clock error: output sample n is the input at n*ratio - lead
    (4-point cubic interpolation; the audio is band-limited to 3.6 kHz at 48 kHz).
    A ratio over 1 reads ahead of the samples received, so `lead` holds the read
    point behind them for HORIZON: a propagation delay that shrinks from lead/FS to
    zero. A ratio under 1 needs none; its delay grows from zero instead."""

    def __init__(self, ratio):
        self.ratio = ratio
        self.lead = int(np.ceil(max(ratio-1, 0)*HORIZON*FS))+4
        self.buf = np.zeros(self.lead+4)  # silence before the session
        self.base = -len(self.buf)  # input index of buf[0]
        self.n = 0  # output samples so far

    def process(self, x):
        self.buf = np.concatenate([self.buf, x])
        pos = (self.n+np.arange(len(x)))*self.ratio-self.lead
        k = np.floor(pos).astype(np.int64)
        f = pos-k
        i = k-self.base
        assert i[0] >= 1 and i[-1]+2 < len(self.buf), "clock skew ran past its lead: raise HORIZON"
        p0, p1, p2, p3 = (self.buf[i+d] for d in (-1, 0, 1, 2))
        y = p1+0.5*f*(p2-p0+f*(2*p0-5*p1+4*p2-p3+f*(3*(p1-p2)+p3-p0)))
        self.n += len(x)
        drop = max(0, int(k[-1])-1-self.base-8)
        self.buf, self.base = self.buf[drop:], self.base+drop
        return y


def interference(qrm, seed, sigma, horizon):
    """Each receiver's interference at 48 kHz from data2g.interference (the pinned channel
    checkout's), rendered at its 8 kHz against the same floor density and raised to 48 kHz.
    The seeds and render are run_gate.py's and the short-control study's, so qrm-noise replays them."""
    from data2g import interference as I

    spec = I.PRESETS[qrm] if isinstance(qrm, str) else I.Spec(qrm=(I.Qrm(*qrm),))
    sigma8 = sigma*np.sqrt((I.FS/2)/(FS/2))
    length = max(250.0, horizon+70.0)
    out = []
    for dest in range(2):
        it = I.Interference(spec, seed*10+7+dest, length)
        y = it.render(0.0, int(length*I.FS), sigma8)
        out.append(signal.resample_poly(y, FS//I.FS, 1, window=("kaiser", 8.6)))
    return out


class StreamingChannel:
    def __init__(self, dop, delay_ms, snr, seed, carrier=False, cfo=4.5, cfo_rate=0.0, ppm=0.0, qrm=None,
                 horizon=180.0):
        self.original = ContinuousChannel("comparison", snr, seed, HORIZON,
                                          doppler=dop, delay_ms=delay_ms)
        # Cache exactly the arrays np.interp otherwise copies every 10 ms.
        self.tap_grid = np.arange(len(self.original.g[0]), dtype=np.float64) if dop else None
        self.tap_parts = [(np.ascontiguousarray(g.real), np.ascontiguousarray(g.imag))
                          for g in self.original.g] if dop else []
        self.dop, self.cfo, self.cfo_rate = dop, cfo, cfo_rate
        # station 1's clock ppm fast: it hears station 0 slowed, station 0 hears it sped up
        k = 1+ppm*1e-6
        self.skew = [ClockSkew(1/k), ClockSkew(k)] if ppm else None  # by source
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
        self.sigma = np.sqrt(S_POWER * (FS / 2) / 2500 / 10**(snr/10))
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
        self.qrm = interference(qrm, seed, self.sigma, horizon) if qrm else None

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
            if self.skew:
                x = self.skew[source].process(x)
            im, self.zi[source] = signal.lfilter(self.h, [1.0], x, zi=self.zi[source])
            r = np.concatenate([self.real_history[source], x])
            self.real_history[source] = r[-self.hdelay:].copy()
            z = r[:n] + 1j*im
            if self.dop:
                delayed = np.concatenate([self.echo_history[source], z])
                self.echo_history[source] = delayed[-self.delay:].copy() if self.delay else np.array([], complex)
                z = (z*gs[0] + delayed[:n]*gs[1])/np.sqrt(2)
            z *= np.exp(2j*np.pi*(self.cfo*t+0.5*self.cfo_rate*t*t))
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
            if self.qrm is not None:
                y = y+self.qrm[dest][self.n:self.n+n]
            result.append(y)
        self.n += n
        return result[::-1]
