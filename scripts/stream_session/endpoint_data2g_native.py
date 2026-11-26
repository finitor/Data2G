"""Both Data2G stations as the native engine runs them (native.engine.Engine: C++ engine, session, ARQ,
policy and DSP, the engine data2g-host runs), over the same pipe protocol as endpoint_data2g.py.

Stations are stepped synchronously (no decode worker thread) so each station's CPU is the thread time
of its own step calls. PEP-fair only: bursts go out as the engine makes them, at full-scale peak
(DATA2G_PEP_REF_DB must be set; there is no mean-power rescale here).

STREAM_SESSION_CPU, if set, names a file for per-block CPU: little-endian uint64 nanoseconds, one row of
five per 10 ms block: station 0 and 1 engine step, station 0 and 1 rate conversion (48 <-> 8 kHz, the app's native Decimator and
Interpolator), and the
whole process over the block (a check that nothing ran on other threads).
"""
import os
import json
import struct
import sys
import time
from pathlib import Path
import numpy as np

D2G = Path(os.environ.get("STREAM_SESSION_MODEM") or Path(__file__).resolve().parents[2]).resolve()
BLOCK = 480
assert os.environ.get("DATA2G_PEP_REF_DB"), "the native endpoint is PEP-fair only"
sys.path[:0] = [str(D2G), str(D2G / "tests")]
import native_subs  # noqa: E402
native, why = native_subs.import_native()
assert native is not None, why
assert Path(native.__file__).resolve().is_relative_to(D2G), native.__file__
assert native.__profile__ == "hf", native.__profile__
native.set_threads(1)
CPU = os.environ.get("STREAM_SESSION_CPU")
DONE = {"closed", "listen", "idle"}


def main():
    seed = int(sys.argv[1])
    payload = [Path(p).read_bytes() for p in sys.argv[2:4]]
    cap = int(sys.argv[4]) if len(sys.argv) > 4 else 2  # the session's bandwidth cap code
    st = [native.engine.Engine("W1AW", seed=seed+1), native.engine.Engine("K2XYZ", seed=seed+2)]
    st[1].listen()
    # the native app's capture and playback rate conversion (native/core/audio/filters.hpp)
    down = [native.audio.Decimator(48000), native.audio.Decimator(48000)]
    up = [native.audio.Interpolator(48000), native.audio.Interpolator(48000)]
    connected, sent = [False]*2, [False]*2
    got = [bytearray(), bytearray()]
    keyed = [False, False]
    cpu = []
    tt, pt = time.thread_time_ns, time.process_time_ns
    while raw := sys.stdin.buffer.read(8+2*BLOCK*8):
        assert len(raw) == 8+2*BLOCK*8
        p0 = pt()
        cmd, = struct.unpack("<Q", raw[:8])
        if cmd == 2:
            st[0].connect("K2XYZ", cap)
        elif cmd == 1:
            st[0].session.disconnect()
        inputs = np.frombuffer(raw[8:], dtype="<f8").reshape(2, BLOCK)
        out, row = [], [0]*5
        for i, s in enumerate(st):
            t0 = tt()
            x8 = down[i](inputs[i])
            t1 = tt()
            x, ptt = s.step(x8)
            t2 = tt()
            y = up[i](np.asarray(x, dtype=float))
            t3 = tt()
            row[i], row[2+i] = t2-t1, (t1-t0)+(t3-t2)
            out.append(y)
            if bool(ptt) and not keyed[i]:
                print(json.dumps(dict(t=s.now, i=i, event="tx", mode=str(s.tx_submode))), file=sys.stderr, flush=True)
            keyed[i] = bool(ptt)
            ss = s.session
            connected[i] |= ss.state == "connected"
            if connected[i] and not sent[i]:
                ss.write(payload[i])
                sent[i] = True
            got[i].extend(ss.read())
            for ev in s.events():
                print(json.dumps(dict(t=s.now, i=i, event=ev)), file=sys.stderr, flush=True)
        pending = [int(bool(s.session._pending_write) or
                       (s.session.station is not None and s.session.station.tx.pending())) for s in st]
        values = [*map(int, connected), *map(len, got), *pending,
                  int(all(s.session.state in DONE for s in st)),
                  int(any(not payload[1-i].startswith(got[i]) for i in range(2)))]
        row[4] = pt()-p0
        cpu.append(row)
        sys.stdout.buffer.write(np.asarray(out, dtype="<f8").tobytes()+struct.pack("<8Q", *values))
        sys.stdout.buffer.flush()
    if CPU:
        np.asarray(cpu, dtype="<u8").tofile(CPU)


if __name__ == "__main__":
    main()
