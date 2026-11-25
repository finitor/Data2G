"""Physical checks of the continuous audio adapter, before measurements."""
import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
import json
import numpy as np
from scipy import signal
from stream_channel import StreamingChannel, FS, BLOCK, POWER


def render(ch, x):
    out = []
    for k in range(0, len(x), BLOCK):
        out.append(ch.process([x[k:k+BLOCK], x[k:k+BLOCK]])[0])
    return np.concatenate(out)


def main():
    seconds, seed = 8, 123499
    t = np.arange(seconds*FS)/FS
    x = np.sqrt(2*POWER)*np.cos(2*np.pi*1500*t)
    results = {}
    for dop, delay in [(0, 0), (1, 7), (30, 7)]:
        ch = StreamingChannel(dop, delay, 0, seed)
        y = render(ch, x)
        noise = np.random.default_rng(np.random.SeedSequence([seed, 7000000, 0])).normal(0, ch.sigma, len(x))
        # Exact analytic signal of the steady input, with the FIR's fixed delay.
        source_t = np.maximum(t-ch.hdelay/FS, 0)
        z = np.sqrt(2*POWER)*np.exp(2j*np.pi*1500*(t-ch.hdelay/FS))
        if dop:
            g = [np.interp(source_t*ch.original.rate, np.arange(len(v)), v.real)+
                 1j*np.interp(source_t*ch.original.rate, np.arange(len(v)), v.imag) for v in ch.original.g]
            z = z*(g[0]+np.exp(-2j*np.pi*1500*delay/1000)*g[1])/np.sqrt(2)
        expected = (z*np.exp(2j*np.pi*4.5*t)).real
        trim = slice(FS//4, -FS//4)
        relerr = float(np.linalg.norm((y-noise-expected)[trim])/np.linalg.norm(expected[trim]))
        assert relerr < 0.001, (dop, delay, relerr)
        assert np.array_equal(y, render(StreamingChannel(dop, delay, 0, seed), x))
        sigma_ratio = float(np.var(noise)/ch.sigma**2)
        assert abs(sigma_ratio-1) < 0.01
        results[f"dop{dop}-delay{delay}"] = dict(relative_signal_error=relerr, noise_variance_ratio=sigma_ratio)
    clean = StreamingChannel(0, 0, 0, seed)
    qrm = StreamingChannel(0, 0, 0, seed, carrier=True)
    a, b = render(clean, x), render(qrm, x)
    q = b-a
    power = float(np.mean(q*q))
    inr = 10*np.log10(power/(clean.sigma**2*50/(FS/2)))
    assert abs(inr-12) < 0.001
    results["carrier_inr_db"] = inr
    for cdop in (1.0, 10.0):  # the fading carrier: the same mean power, over a longer span
        n = 120*FS
        z0 = np.zeros(n)
        qf = render(StreamingChannel(0, 0, 0, seed, carrier=cdop), z0) - render(StreamingChannel(0, 0, 0, seed), z0)
        finr = 10*np.log10(float(np.mean(qf*qf))/(clean.sigma**2*50/(FS/2)))
        assert abs(finr-12) < 1.5, (cdop, finr)
        results[f"carrier_fade{cdop:g}_mean_inr_db"] = finr
    # FIR passband accuracy at every modem's occupied audio range.
    f, h = signal.freqz(clean.h, worN=65536, fs=FS)
    error = np.max(np.abs(abs(h[(f>=275)&(f<=2800)])-1))
    assert error < 0.01
    results["hilbert_passband_max_amplitude_error"] = float(error)
    results["stream_delay_s"] = clean.hdelay/FS
    # Frequency drift: a +0.1 Hz/s ramp on top of the 4.5 Hz offset, against the exact chirp.
    y = render(StreamingChannel(0, 0, 0, seed, cfo_rate=0.1), x)
    z = np.sqrt(2*POWER)*np.exp(2j*np.pi*(1500*(t-clean.hdelay/FS)+4.5*t+0.05*t*t))
    trim = slice(FS//4, -FS//4)
    noise = np.random.default_rng(np.random.SeedSequence([seed, 7000000, 0])).normal(0, clean.sigma, len(x))
    drift_err = float(np.linalg.norm((y-noise-z.real)[trim])/np.linalg.norm(z.real[trim]))
    assert drift_err < 0.001, drift_err
    results["drift_relative_signal_error"] = drift_err
    # Clock skew: each receiver hears the other's tone time-scaled by the clocks' ratio.
    ppm, n = 100.0, 60*FS
    tt = np.arange(n)/FS
    tone = np.sqrt(2*POWER)*np.cos(2*np.pi*1500*tt)
    ch = StreamingChannel(0, 0, 60, seed, cfo=0.0, ppm=ppm)
    outs = [ch.process([tone[k:k+BLOCK], tone[k:k+BLOCK]]) for k in range(0, n, BLOCK)]
    for dest, ratio in ((1, 1/(1+ppm*1e-6)), (0, 1+ppm*1e-6)):
        y = np.concatenate([o[dest] for o in outs])
        lead = ch.skew[1-dest].lead
        pos = (tt*FS-ch.hdelay)*ratio-lead  # the source sample each output sample is
        expected = np.sqrt(2*POWER)*np.cos(2*np.pi*1500*pos/FS)*(pos >= 0)
        ok = slice(int(lead+ch.hdelay)+FS, None)
        err = float(np.linalg.norm((y-expected)[ok])/np.linalg.norm(expected[ok]))
        assert err < 0.01, (dest, err)  # over a 60 dB noise floor
        results[f"clock_skew_to{dest}_relative_error"] = err
    # Interference: qrm-noise's band noise at +20 dB over the floor in its 500 Hz, 30% of the time.
    z0 = np.zeros(120*FS)
    ch = StreamingChannel(0, 0, 0, seed, qrm=("noise", 1500.0, 500.0, 20.0, 3.0, 0.3), horizon=180)
    q = render(ch, z0)-render(StreamingChannel(0, 0, 0, seed), z0)
    f, pq = signal.welch(q, fs=FS, nperseg=8192)
    band = (f > 1300) & (f < 1700)
    floor = clean.sigma**2/(FS/2)
    on = float(np.mean(np.abs(q) > 1e-9))
    inr = 10*np.log10(np.mean(pq[band])/on/floor)  # one-sided densities, the QRM's over its on time
    assert 0.15 < on < 0.5 and abs(inr-20) < 1.5, (on, inr)
    results["qrm_noise_on_fraction"], results["qrm_noise_inr_db"] = on, float(inr)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
