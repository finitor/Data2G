"""Two live Python Engines with native DSP; binary paired audio endpoint.

Driven by run_sessions.py over pipes: per 10 ms block, a command word and
both stations' received audio in; both stations' transmitted audio and
eight status words out. The modem is imported from STREAM_SESSION_MODEM (a
Data2G checkout with native/build/python built; default: this one).
STREAM_SESSION_LOG=1 adds the modem's own log lines and each station's
receiver, CW-sense and timer state on change to stderr (the session log).
"""
import os
for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "DATA2G_THREADS"):
    os.environ[key] = "1"
import json
import struct
import sys
from pathlib import Path
import numpy as np
from scipy import signal
D2G = Path(os.environ.get("STREAM_SESSION_MODEM") or Path(__file__).resolve().parents[2]).resolve()
BLOCK = 480
PEP = bool(os.environ.get("DATA2G_PEP_REF_DB"))
sys.path[:0] = [str(D2G), str(D2G / "tests")]
import native_subs
native, why = native_subs.import_native()
assert native is not None, why
assert Path(native.__file__).resolve().is_relative_to(D2G), native.__file__
assert native.__profile__ == "hf", native.__profile__
native.set_threads(1)
native_subs.apply(native_subs.build(native, skip={"arq", "gear", "engine", "host"}))
from data2g.arq import engine as E, session as S, phy as PHY
PHY.DD_BUDGET_S = float("inf")  # simulated samples, no wall-clock CPU deadline model
LOG = bool(os.environ.get("STREAM_SESSION_LOG"))
_CUR = dict(i=-1, t=0.0)  # the station being stepped, for the log lines
_LAST = {}


def _log_setup():
    import logging

    class Ctx(logging.Filter):
        def filter(self, r):
            r.i, r.simt = _CUR["i"], _CUR["t"]
            return True

    h = logging.StreamHandler(sys.stderr)
    h.addFilter(Ctx())
    h.setFormatter(logging.Formatter("LOG t=%(simt).2f i=%(i)d %(name)s: %(message)s"))
    logging.getLogger().addHandler(h)
    logging.getLogger().setLevel(logging.INFO)


def _log_state(i, s, polled):
    """Station i's gating state, when it changes: logging only."""
    r, ss = s.receiver, s.session
    key = (str(ss.state), r.busy, r.channel_busy, bool(r.on_air), bool(s._cw_heard), s.now < s._hold,
           polled, ss._out is not None, ss._deadline is None, s.tx is not None)
    if _LAST.get(i) != key:
        _LAST[i] = key
        print(json.dumps(dict(t=round(s.now, 2), i=i, state=dict(
            session=str(ss.state), rx_busy=r.busy, channel_busy=r.channel_busy, on_air=bool(r.on_air),
            cw=bool(s._cw_heard), held=s.now < s._hold, polled=polled, out_queued=ss._out is not None,
            deadline=ss._deadline, due=ss._due, tx=s.tx is not None)), default=str), file=sys.stderr, flush=True)


class Engine(E.Engine):
    def _start_tx(self, bursts, t, main):
        super()._start_tx(bursts, t, main)
        # Mean-power SNR: equal active mean power, after the live engine's peak scaling.
        # PEP-fair (DATA2G_PEP_REF_DB set, stream_channel.py): the engine's full-scale peak as sent.
        a = self.tx[1]
        lo = np.flatnonzero(abs(a) > 1e-10)
        if len(lo) and not PEP:
            p = np.mean(a[lo[0]:lo[-1]+1]**2)
            self.tx[1] = a*np.sqrt(0.01/p)
        print(json.dumps(dict(t=t, event="tx", mode=main.submode)), file=sys.stderr, flush=True)


class Resampler:
    def __init__(self, up):
        self.up = up
        self.h = signal.firwin(193, 3600, fs=48000, window=("kaiser", 8.6))
        self.z = np.zeros(len(self.h)-1)

    def process(self, x):
        if self.up:
            a = np.zeros(len(x)*6)
            a[::6] = x
            a, self.z = signal.lfilter(self.h*6, [1.0], a, zi=self.z)
            return a
        a, self.z = signal.lfilter(self.h, [1.0], x, zi=self.z)
        return a[::6]


def main():
    seed = int(sys.argv[1])
    payload = [Path(p).read_bytes() for p in sys.argv[2:4]]
    cap = int(sys.argv[4]) if len(sys.argv) > 4 else 2  # the session's bandwidth cap code
    st = [Engine("W1AW", seed=seed+1), Engine("K2XYZ", seed=seed+2)]
    st[1].listen()
    if LOG:
        _log_setup()
    down = [Resampler(False), Resampler(False)]
    up = [Resampler(True), Resampler(True)]
    connected, sent = [False]*2, [False]*2
    got = [bytearray(), bytearray()]
    while raw := sys.stdin.buffer.read(8+2*BLOCK*8):
        assert len(raw) == 8+2*BLOCK*8
        cmd, = struct.unpack("<Q", raw[:8])
        if cmd == 2:
            st[0].connect("K2XYZ", cap)
        elif cmd == 1:
            st[0].session.disconnect()
        inputs = np.frombuffer(raw[8:], dtype="<f8").reshape(2, BLOCK)
        out = []
        for i, s in enumerate(st):
            # Production Engine.step guards Session.poll with tx is None.
            oldtx = s.tx
            original_poll = s.session.poll
            polled = [False]
            _CUR.update(i=i, t=s.now)

            def guard(t, s=s, oldtx=oldtx, poll=original_poll, polled=polled):
                assert oldtx is None, "polled during own transmitter activity"
                polled[0] = True
                return poll(t)
            s.session.poll = guard
            try:
                x, _ = s.step(down[i].process(inputs[i]))
            finally:
                s.session.poll = original_poll
            out.append(up[i].process(x))
            if LOG:
                _log_state(i, s, polled[0])
            connected[i] |= s.session.state == S.CONNECTED
            if connected[i] and not sent[i]:
                s.session.write(payload[i])
                sent[i] = True
            got[i].extend(s.session.read())
            for ev in s.events():
                print(json.dumps(dict(t=s.now, i=i, event=ev)), file=sys.stderr, flush=True)
        pending = [int(bool(s.session._pending_write) or
                       (s.session.station is not None and s.session.station.tx.pending())) for s in st]
        values = [*map(int, connected), *map(len, got), *pending,
                  int(all(s.session.state in (S.CLOSED, S.LISTEN, S.IDLE) for s in st)),
                  int(any(not payload[1-i].startswith(got[i]) for i in range(2)))]
        sys.stdout.buffer.write(np.asarray(out, dtype="<f8").tobytes()+struct.pack("<8Q", *values))
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
