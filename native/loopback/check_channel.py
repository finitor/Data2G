"""Compare native fading to the existing Python reference with the same draws.

Run with the project's Python environment:
    python native/loopback/check_channel.py native/build-loopback/data2g-loopback
This does not train models or change generated tables.
"""
import json
import math
from pathlib import Path
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from data2g import hfchannel
from data2g.config import FS


class Random:
    def __init__(self, seed):
        self.state = seed

    def uniform(self):
        mask = (1 << 64) - 1
        self.state = (self.state + 0x9e3779b97f4a7c15) & mask
        z = self.state
        z = ((z ^ (z >> 30)) * 0xbf58476d1ce4e5b9) & mask
        z = ((z ^ (z >> 27)) * 0x94d049bb133111eb) & mask
        z ^= z >> 31
        return ((z >> 11) + .5) * 2**-53

    def normal(self, size):
        def one():
            u, v = self.uniform(), self.uniform()
            return math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * v)
        return np.fromiter((one() for _ in range(size)), dtype=float, count=size)


def main():
    for name, spread, delay_ms in [('mpg', .1, .5), ('mpp', 1, 2), ('mpd', 2, 4), ('nvis', 1, 7), ('hilat', 30, 7)]:
        horizon, seed = 10, 17
        native = json.loads(subprocess.check_output([sys.argv[1], '--channel-probe', '--channel', name,
                                                    '--horizon', str(horizon), '--seed', str(seed), '--cfo', '4.5']))
        rng = Random(seed)
        # At sample indices whose tap coordinate is integral, the Python
        # audio-rate interpolation is exactly the original low-rate tap.
        count = (horizon + 60) * FS
        rate = native['rate']
        indices = np.arange(count)
        exact = np.flatnonzero(np.isclose(indices * rate / FS, np.round(indices * rate / FS), atol=1e-10, rtol=0))
        tap_indices = np.round(exact * rate / FS).astype(int)
        gains = []
        delay = int(round(delay_ms * .001 * FS))
        times = 24017 + np.arange(FS + delay)
        for path in range(2):
            expected = hfchannel._gaussian_taps(count, spread, rng)
            pairs = np.array(native['taps'][path])
            actual = pairs[:, 0] + 1j * pairs[:, 1]
            np.testing.assert_allclose(actual[tap_indices], expected[exact], atol=2e-11, rtol=2e-11)
            gains.append(expected[times])
        audio = np.zeros(FS)
        i = np.arange(100, FS - 100)
        audio[i] = np.cos(2 * np.pi * 1000 * i / FS) + .3 * np.sin(2 * np.pi * 1555 * i / FS)
        z = hfchannel._analytic(audio) / np.sqrt(hfchannel.active_power(audio))
        y = (np.pad(z, (0, delay)) * gains[0] + np.pad(z, (delay, 0)) * gains[1]) / np.sqrt(2)
        y *= np.exp(2j * np.pi * np.remainder(4.5 * times / FS, 1))
        np.testing.assert_allclose(native['rendered'], y.real, atol=2e-10, rtol=2e-10)
        print(f'{name}: continuous taps, delayed audio, mean power and CFO match Python reference')


if __name__ == '__main__':
    main()
