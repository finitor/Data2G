# Android acoustic link: first probe

Two phones running the Android TNC, coupled only through their own speakers and
microphones, hold a connected session and pass data both ways. This note records
the first measurements, taken on 2026-11-23 with unmodified release builds.

Branch `feature/android-acoustic-link`, based on the fork's `master` at
`76155db`; integration target `master`. Guidance: the root `AGENTS.md` at that
commit. The maintainer asked for this on-device probe explicitly.

## Result

- Phone to phone works with no code changes. In the best setting a session
  connected in 4.7 s and carried 3000 bytes each way in 53 s.
- The link depends heavily on placement and on speaker level. The same hardware
  ranged from 2200 bit/s to no data at all.
- At full speaker volume the receiver reported a higher SNR and decoded worse.
- The gear shifter tends to open with a 64-level mode that does not get through,
  then succeeds on 16-QAM rate 1/2.
- In the worst placement the measured echo delay was 11 to 15 ms, against a
  4 ms cyclic prefix, and OFDM data stopped decoding.

Every row below is a single run. Distances and orientations were not measured,
and the phones may have moved between runs, so the comparisons are suggestive
and not established.

## Setup

| Station | Device | Software |
|---|---|---|
| Phone A | Samsung SM-S948U1, Android 17 | Data2G TNC 0.5.3 from the Play Store (version code 5003) |
| Phone B | Xiaomi 220333QAG, Android 13 | the same |
| Mac | MacBook Air, built-in microphone and speakers | `data2g-host` and `data2g-gui`, local release build of v0.5.3 |

- Phone A: input "Builtin Mic", output "Speaker", chosen in Settings. Phone B:
  both left on "System default"; its log names neither device.
- No rig, transmit level 0 dB, 2300 Hz bandwidth, all other settings default.
- One indoor room. Ambient noise was not measured.
- Sessions were driven with `tools/session_probe.py`: it is the client of both
  stations over their command and data ports (a phone's through `adb forward`),
  connects, sends random bytes each way and disconnects. Times run from queueing
  the bytes to the last one arriving, so they include acks and resends.
- SNR figures are each receiver's own, read from its log.

## Phone A and the Mac

Phone A called the Mac. 1500 bytes each way in run 1, 3000 after.

| Run | Change | Connect | Phone to Mac | Mac to phone |
|---|---|---|---|---|
| 1 | first placement, `data2g-host` | 4.6 s | 8.5 s, 1410 bit/s, `w48-64l-r1/2` first try | 24.5 s, 490 bit/s, two bursts lost |
| 2 | same, `data2g-gui` | 4.7 s | 10.9 s, 2211 bit/s, `w48-64l-r7/12` first try | 59.0 s, 407 bit/s, five bursts lost |
| 3 | phone repositioned | 4.8 s | 20.7 s, 1158 bit/s, `w48-16qam-r1/3` | 11.1 s, 2163 bit/s, `w48-64l-r7/12` first try |
| 4 | phone moved again | 4.7 s | failed: 0 of 3000 bytes in 243 s | not attempted |

What the Mac measured on the phone's bursts:

| Run | SNR, short acks | SNR, data | Echo delay | Energy |
|---|---|---|---|---|
| 1, 2 | 10 to 14 dB | 15 to 16 dB | 0.0 ms | 39 to 49 dB |
| 3 | 3 to 5 dB | 12.5 dB | 4.2 to 7.9 ms | 34 to 36 dB |
| 4 | -2 to -4 dB | 5.1 dB | 11.5 to 14.6 ms | 21 to 26 dB |

- Runs 1 and 2: the phone heard the Mac at 9 to 10.5 dB. It acknowledged the
  Mac's short bursts every time and none of its 64-level data bursts.
- Run 4: `w48-16qam-r1/3` was sent four times and lost each time. The session
  fell back to FSK. The Mac decoded `fsk32r62-r1/2` payloads at about 7 dB and
  several `fsk8r50-r1/3` bursts, but logged "control lost" on them, 14 times, so
  it could not acknowledge and the phone gave up after 13 timeouts.

## Phone A and phone B

Phone A called phone B. 3000 bytes each way. Volume is Android's media volume,
out of 15.

| Run | Volume A / B | Connect | A to B | B to A | Session |
|---|---|---|---|---|---|
| 5 | 9 / 15 | 5.0 s | 71.8 s, 334 bit/s | 31.9 s, 753 bit/s | 110 s |
| 6 | 15 / 15 | 4.9 s | 174.7 s, 137 bit/s | 52.1 s, 461 bit/s | 238 s |
| 7 | 13 / 15 | 4.9 s | 13.8 s, 1742 bit/s | 33.3 s, 722 bit/s | 53 s |
| 8 | 13 / 13 | 4.7 s | 13.7 s, 1747 bit/s | 33.2 s, 723 bit/s | 53 s |

- Phone B heard phone A at about 5 dB in run 5, 6.6 to 10 dB in run 6 and
  4.6 to 6.7 dB in runs 7 and 8. The loudest setting gave the highest reading
  and the slowest transfer, with audible distortion from phone A's speaker.
- Phone A heard phone B at 11 to 15 dB throughout.
- A to B in runs 7 and 8: one `w48-16qam-r1/2` burst, no resends.
- B to A in runs 5, 7 and 8: `w48-64l-r7/12` lost (twice in runs 7 and 8), then
  `w48-16qam-r1/2` delivered everything. Run 6 opened with `w48-256l-r5/8`,
  also lost. Lowering phone B's volume from 15 to 13 changed nothing.
- Runs 7 and 8 agree to within 0.1 s per direction.

## Other observations

- While idle in the room, phone A logged false detections: "header heard, burst
  lost" in modes no station was using, six times in eight minutes, and
  "CW ID heard: holding" twice.
- Phone B logged "RX audio 1.1 s behind the card" twice just before run 6.
- Connect and disconnect on `qpsk-r1/5` succeeded in every run, including run 4.

## Not established

- Why 64-level bursts are lost at 12 to 15 dB reported SNR. Speaker distortion
  and echo that the SNR estimate does not count as noise are candidates.
- Why control is lost on FSK bursts whose data decodes (run 4).
- Which microphone and capture source phone B used.
- Anything about range: no distance was measured.
- Behaviour with Ragtime as the client; the probe is not Ragtime's protocol.
- None of this has been reproduced on a pinned upstream source build; the phones
  ran upstream's 0.5.3 release.

## Candidate work for this branch

1. An acoustic preset in the Android TNC's settings: built-in microphone and
   loudspeaker, a transmit level below the speaker's maximum, and a warning when
   the unprocessed capture source is missing.
2. A cap or offset on the starting mode for acoustic use, so that sessions open
   at 16-QAM.
3. The idle false detections and the lost FSK control, once reproduced.

## State

- Tested: stock 0.5.3 release builds, not this branch. No modem code is changed.
- `tools/session_probe.py` in its checked-in form has been compile-checked only.
  The runs above used an earlier copy with the stations fixed in the script.
- Recordings of the Mac's received bursts from runs 1 to 4 were kept only in a
  temporary directory.
- Not run: core tests, any Android build, hosted workflows.
