"""Standalone default-mode DISC exhaustion budget, without a receiver or Lab.

Run from either upstream or the corrected checkout with its dependencies:
    PYTHONPATH=. python /path/to/repro_disc_retry_budget.py
All replies are absent; start the first DISC at time zero, with no PTT or ID.
"""
import hashlib
import json
from pathlib import Path

from data2g.arq import link, policy, session


def main():
    gear = policy.GearShifter()
    src = session.Session("LAB1", gear, t_turn=1.0)
    src.station = link.Station(0, gear, master=True, key=1)
    src.state = session.CONNECTED
    src.disconnect()
    assert src._disc(0.0)
    now, attempts = 0.0, []
    burst = src.poll(now)
    while burst is not None:
        end = now + gear.airtime(burst.submode, len(burst.slots))
        src.on_tx_end(burst, end)
        deadline = src.next_event()
        attempts.append(dict(mode=burst.submode, start_s=now, end_s=end, deadline_s=deadline))
        now = deadline
        burst = src.poll(now)
        assert len(attempts) <= session.DISC_TRIES
    assert src.state == session.CLOSED and src.close_reason == "CLIENT unconfirmed"
    source = Path(session.__file__)
    print(json.dumps(dict(session_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                          t_turn_s=src.t_turn, attempts=attempts, exhausted_s=now), indent=2))


if __name__ == "__main__":
    main()
