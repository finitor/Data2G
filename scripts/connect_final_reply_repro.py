"""DSP-free late CONNECT_ACK reproduction; optional --root tests another checkout."""

import argparse
import json
from pathlib import Path
import random
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--expect-connected", action="store_true")
    args = ap.parse_args()
    sys.path[:0] = [str(args.root), str(args.root / "tests")]
    from data2g.arq import policy as G, session as S
    from test_arq import FakeRx

    def rx(burst):
        return FakeRx(burst, random.Random(3), 0, {}, {"mismatch": 0})

    a = S.Session("W1AW", G.GearShifter(), rng=random.Random(1))
    a.connect_tries = 2
    a.connect("K2XYZ", 2, 0)
    a.on_tx_end(a.poll(0), 0)
    a.poll(a.next_event())  # first CONNECT lost; retry waits its normal jitter
    end = a.next_event()
    request = a.poll(end)
    a.on_tx_end(request, end)
    deadline = a.next_event() - end
    b = S.Session("K2XYZ", G.GearShifter())
    b.listen()
    b.on_rx(rx(request), end)
    ack = b.poll(end)
    a.poll(end + 3.5)
    at_short_deadline = a.state
    a.on_header(ack.submode, len(ack.slots), end + 4.34)
    a.on_rx(rx(ack), end + 5.24)
    print(json.dumps(dict(mode=request.submode, final_wait_s=deadline,
                          at_short_deadline=at_short_deadline, after_ack=a.state,
                          reason=a.close_reason), indent=2))
    if args.expect_connected:
        assert a.state == S.CONNECTED


if __name__ == "__main__":
    main()
