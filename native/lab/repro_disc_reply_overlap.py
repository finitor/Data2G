"""Standalone timer arithmetic reproduction on unchanged upstream v0.5.2.

From an upstream checkout with normal project dependencies installed:
    PYTHONPATH=. python /path/to/repro_disc_reply_overlap.py
No Lab, native module, waveform simulation or other repository is required.
The constructed station isolates the real Session.on_tx_end calculation;
the Lab study separately retains full paired-engine audio reproductions.
"""
import hashlib
import json
from pathlib import Path

from data2g.arq import link, policy, session


def main():
    rows = []
    for tries in (0, 1):
        gear = policy.GearShifter()
        caller = session.Session("LAB1", gear, t_turn=1.0)
        caller.station = link.Station(0, gear, master=True, key=1)
        caller.state = session.DISCONNECTING
        caller._tries = tries
        burst = caller._disc_burst()
        caller.on_tx_end(burst, 0.0)
        # DISC and DISC_ACK have equal-size T_SESS bodies and reply in the
        # received mode. Ignore PTT/audio latency: even this lower bound overlaps.
        ack_airtime = gear.airtime(burst.submode, len(burst.slots))
        ack_end = caller.t_turn + ack_airtime
        rows.append(dict(mode=burst.submode, try_index=tries, deadline_s=caller._deadline,
                         nominal_ack_end_s=ack_end, overlap_s=max(0, ack_end - caller._deadline)))
    source = Path(session.__file__)
    print(json.dumps({"session_module": str(source),
                      "session_source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "cases": rows}, indent=2))


if __name__ == "__main__":
    main()
