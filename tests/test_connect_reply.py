"""The final CONNECT must not close while its late-header ACK is on air."""

import random

import pytest

from data2g.arq import burst as B
from data2g.arq import frames as F
from data2g.arq import policy as G
from data2g.arq import session as S

from test_arq_session import _rx


def last_connect(cap=2, tries=5, use_cpm=True, t_turn=1.0):
    a = S.Session("W1AW", G.GearShifter(use_cpm=use_cpm), t_turn=t_turn, rng=random.Random(1))
    a.connect_tries = tries
    a.connect("K2XYZ", cap, 0.0)
    now = 0.0
    for i in range(tries):
        request = a.poll(now)
        assert request is not None
        a.on_tx_end(request, now)
        old_deadline = now + t_turn + S.REPLY_START_S
        if i < tries - 1:
            # Earlier attempts retain their original timeout and 3–5 s retry jitter.
            assert a.next_event() == pytest.approx(old_deadline)
            assert a.poll(old_deadline) is None and a.state == S.CONNECTING
            now = a.next_event()
            assert old_deadline + 3 <= now <= old_deadline + 5
    return a, request, now, old_deadline


def answer(a, request, body=None):
    if body is None:
        body = F.ConnectAck(a._nonce, a.cap, 10).pack()
    ctl = F.Control(F.Core(ftype=F.SESSION), {F.T_SESS: body}).pack(a.policy.ctl_payload_bytes(request.submode))
    return B.TxBurst(request.submode, [B.Slot(B.ctl_mask(1, i, 0), 0, p) for i, p in enumerate(ctl)], 0, a.cap)


@pytest.mark.parametrize("cap", [0, 1, 2])
@pytest.mark.parametrize("tries,use_cpm", [(1, True), (2, True), (5, True), (2, False)])
def test_final_connect_has_one_ack_airtime_and_still_expires(cap, tries, use_cpm):
    a, request, end, old = last_connect(cap, tries, use_cpm, t_turn=0.7)
    ack = answer(a, request)
    airtime = a.policy.airtime(ack.submode, len(ack.slots))
    deadline = a.next_event()
    assert deadline == pytest.approx(old + airtime)
    assert a.poll(old) is None and a.state == S.CONNECTING
    assert a.poll(deadline - 1e-6) is None and a.state == S.CONNECTING
    assert a.poll(deadline) is None and a.state == S.CLOSED
    assert a.close_reason == "NO_ANSWER" and a.next_event() is None
    assert a.poll(deadline + 60) is None  # no extra attempt or unbounded grace


@pytest.mark.parametrize("header", [False, True])
def test_final_robust_connect_accepts_late_ack(header):
    a, request, end, old = last_connect()
    ack = answer(a, request)
    # Frozen streaming case: header 4.34 s and matching ACK 5.24 s after TX.
    assert a.poll(old) is None and a.state == S.CONNECTING
    if header:
        a.on_header(ack.submode, len(ack.slots), end + 4.34)
    a.on_rx(_rx(ack), end + 5.24)
    assert a.state == S.CONNECTED and a.events == ["CONNECTED K2XYZ"]


@pytest.mark.parametrize("kind", ["wrong_nonce", "unreadable", "malformed", "nak"])
def test_final_connect_grace_keeps_frame_validation(kind):
    a, request, end, old = last_connect()
    if kind == "wrong_nonce":
        body = F.ConnectAck(a._nonce ^ 1, a.cap, 10).pack()
    elif kind == "nak":
        body = F.ConnectNak(a._nonce, S.NAK_BUSY).pack()
    elif kind == "malformed":
        body = bytes([F.CONNECT_ACK])
    else:
        body = None
    ack = answer(a, request, body)
    deadline = a.next_event()
    a.poll(old)
    rx = _rx(ack)
    if kind == "unreadable":
        rx.good = [False] * rx.n_cw
    a.on_rx(rx, end + 5.24)
    if kind == "nak":
        assert a.state == S.CLOSED and a.close_reason == S.NAK_NAMES[S.NAK_BUSY]
    else:
        assert a.state == S.CONNECTING and not a.events
        a.poll(deadline)
        assert a.state == S.CLOSED and a.close_reason == "NO_ANSWER"


def test_valid_ack_after_final_allowance_does_not_reopen_dial():
    a, request, end, old = last_connect()
    deadline = a.next_event()
    a.poll(deadline)
    a.on_rx(_rx(answer(a, request)), deadline + 0.1)
    assert a.state == S.CLOSED and a.close_reason == "NO_ANSWER"


@pytest.mark.parametrize("accepted", [False, True])
def test_host_disconnect_during_final_wait_is_bounded(accepted):
    a, request, end, old = last_connect()
    deadline = a.next_event()
    a.disconnect()
    assert a.poll(old) is None and a.state == S.CONNECTING
    if accepted:
        a.on_rx(_rx(answer(a, request)), end + 5.24)
        assert a.state == S.DISCONNECTING
        disc = a.poll(end + 5.24)
        assert disc is not None  # answered dial gets DISC, never starts data
    else:
        a.poll(deadline)
        assert a.state == S.CLOSED and a.close_reason == "CLIENT unconfirmed"
