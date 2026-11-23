#!/usr/bin/env python3
"""Run one connected session between two running Data2G stations and time data each way.

    tools/session_probe.py CALLER CALLEE [--bw BW2300] [--bytes 3000]

    CALLER, CALLEE: NAME:CALLSIGN:PORT[:ADB_SERIAL]

Acts as the client of both stations over their VARA-style ports (commands on PORT, data on PORT + 1, on
127.0.0.1): sets each callsign and bandwidth, has CALLER connect to CALLEE, sends random bytes CALLER to
CALLEE and then back, checks them, and disconnects. Every line the stations report (MODE, PTT, BUFFER,
CONNECTED...) is printed with its time, and each step ends in a RESULT line.

With ADB_SERIAL the station is the Android TNC on that device: PORT and PORT + 1 are forwarded with adb to
the phone's 8300 and 8301 first (a wireless adb link drops its forwards when it reconnects). Two phones
with speaker and microphone, calls only as an example:

    tools/session_probe.py a:N0CALL-1:18300:SERIAL_A b:N0CALL-2:28300:SERIAL_B

The times run from queueing the bytes to the last one arriving, so they include acks and resends. The
bytes are random and don't compress. SNR is in each station's own log, not here. Exit status 0 only when
the connect and both transfers succeeded.
"""
import argparse
import os
import select
import socket
import subprocess
import sys
import time

TNC_COMMAND_PORT = 8300  # the Android TNC's own, on the phone

T0 = time.time()


def log(who, msg):
    print(f"{time.time() - T0:7.2f} {who:6s} {msg}", flush=True)


class Station:
    def __init__(self, spec):
        parts = spec.split(":", 3)  # a wireless adb serial is HOST:PORT
        if len(parts) not in (3, 4):
            raise SystemExit(f"{spec}: want NAME:CALLSIGN:PORT[:ADB_SERIAL]")
        self.name, self.call, port = parts[0], parts[1], int(parts[2])
        if len(parts) == 4:
            for local, remote in ((port, TNC_COMMAND_PORT), (port + 1, TNC_COMMAND_PORT + 1)):
                subprocess.run(["adb", "-s", parts[3], "forward", f"tcp:{local}", f"tcp:{remote}"],
                               check=True, stdout=subprocess.DEVNULL)
        self.cmd = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.data = socket.create_connection(("127.0.0.1", port + 1), timeout=5)
        self.buf = b""
        self.rx = b""
        self.lines = []

    def send(self, line):
        log(self.name, "> " + line)
        self.cmd.sendall(line.encode() + b"\r")

    def said(self, prefix):
        return any(line.startswith(prefix) for line in self.lines)


def pump(stations, seconds, until):
    """Read both stations for up to `seconds`; True once until() holds, False on a timeout or a closed socket."""
    end = time.time() + seconds
    socks = {s.cmd: s for s in stations} | {s.data: s for s in stations}
    while time.time() < end:
        ready, _, _ = select.select(list(socks), [], [], 0.25)
        for sock in ready:
            st = socks[sock]
            chunk = sock.recv(65536)
            if not chunk:
                log(st.name, "socket closed")
                return False
            if sock is st.data:
                st.rx += chunk
                log(st.name, f"data +{len(chunk)} (total {len(st.rx)})")
                continue
            st.buf += chunk
            while b"\r" in st.buf:
                line, st.buf = st.buf.split(b"\r", 1)
                text = line.decode(errors="replace")
                st.lines.append(text)
                if not text.startswith(("IAMALIVE", "BUSY")):
                    log(st.name, "< " + text)
        if until():
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("caller", help="NAME:CALLSIGN:PORT[:ADB_SERIAL]")
    ap.add_argument("callee", help="NAME:CALLSIGN:PORT[:ADB_SERIAL]")
    ap.add_argument("--bw", default="BW2300", choices=["BW500", "BW1200", "BW2300", "BW2750"])
    ap.add_argument("--bytes", type=int, default=3000, help="sent each way (default 3000)")
    ap.add_argument("--connect-timeout", type=float, default=150, metavar="S")
    ap.add_argument("--data-timeout", type=float, default=300, metavar="S", help="each way")
    args = ap.parse_args()

    caller, callee = Station(args.caller), Station(args.callee)
    both = [caller, callee]
    for s in both:
        s.send("VERSION")
        s.send("MYCALL " + s.call)
        s.send(args.bw)
        s.send("LISTEN ON")
    pump(both, 2, lambda: False)

    caller.send(f"CONNECT {caller.call} {callee.call}")
    t = time.time()
    pump(both, args.connect_timeout, lambda: all(s.said("CONNECTED") for s in both) or caller.said("DISCONNECTED"))
    ok = all(s.said("CONNECTED") for s in both) and not caller.said("DISCONNECTED")
    log("probe", f"RESULT connect {'OK' if ok else 'FAILED'} after {time.time() - t:.1f} s")

    if ok:
        for src, dst in ((caller, callee), (callee, caller)):
            payload = os.urandom(args.bytes)
            dst.rx = b""
            t = time.time()
            src.data.sendall(payload)
            log(src.name, f"queued {args.bytes} bytes")
            pump(both, args.data_timeout, lambda: len(dst.rx) >= args.bytes or src.said("DISCONNECTED"))
            dt = time.time() - t
            good = dst.rx == payload
            rate = f" = {args.bytes * 8 / dt:.0f} bit/s" if good else ""
            log("probe", f"RESULT {src.name}->{dst.name} {'OK' if good else 'FAILED'}: "
                         f"{len(dst.rx)}/{args.bytes} bytes in {dt:.1f} s{rate}")
            if not good:
                ok = False
                break

    if not caller.said("DISCONNECTED"):
        caller.send("DISCONNECT")
        if not pump(both, 45, lambda: caller.said("DISCONNECTED")):
            for s in both:
                s.send("ABORT")
            pump(both, 5, lambda: False)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
