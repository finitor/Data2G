# Rig-control server

The native application layer provides a Hamlib NET rigctl facade over the
radio Data2G already controls. The shared `app::RigService` has no Android
API dependency. Android supplies its foreground-service and USB/Bluetooth
integration; desktops can run the same service through `data2g-rigctld`.
This adds radio control, not audio streaming or a different on-air protocol.

## Rationale and design decisions

The goal is to let applications that already speak Hamlib NET rigctl share
the radio attached to a running Data2G application. On a phone, Data2G can
already acquire USB/Bluetooth permissions and reach the radio through its
platform transports. Exposing the familiar TCP interface lets another local
application or a trusted LAN peer use that connection without implementing
the radio's CAT dialect or competing for the hardware port. Compatibility
with a particular client still needs testing; the current evidence includes
Hamlib 4.7.2's library and `rigctl` executable.

Radio control must work while the app is open and the modem is stopped. It
therefore belongs to an app-owned service with a longer lifetime than the
audio/modem station. Starting the modem borrows that service; stopping it
must not close the radio or disconnect rig-control clients. Radio-only use
needs neither a callsign nor microphone access. The user manually launches
Data2G, so this feature does not need boot startup or an independent Android
daemon installation.

The implementation uses the existing C++20/Qt application layer, Hamlib and
platform transports. The protocol and ownership code is shared; Android adds
its lifecycle/UI integration and desktops get a standalone entry point.
Keeping these boundaries avoids an Android-only protocol implementation and
allows later desktop GUI integration without another server or CAT stack.

| Decision | Reason and tradeoff |
|---|---|
| Reuse one Hamlib handle on one worker | Retains existing radio support and transport permissions; avoids concurrent CAT transactions and multiple owners of the same USB/serial device. |
| Add a small protocol adapter | Reuses the app's lifecycle and PTT scheduling. The existing internal byte bridge carries raw CAT and is not a rigctld server; opening a second handle or merely exposing that bridge would not provide the required interface. |
| Extend a declared command subset in tested increments | The initial current-VFO frequency/mode/PTT proof is now extended to VFO selection/targeting, split and common levels. There is no Android or Hamlib architectural restriction to that initial subset. Each added operation needs protocol, ownership and client tests; memories and raw CAT remain separate work. |
| Reserve control while the modem runs | Retuning between bursts can still break an ongoing exchange. The coarse reservation gives predictable ownership across the modem's whole lifetime; finer sharing can be added later with explicit state boundaries and tests. |
| Give external PTT to one connected client | Another client cannot cut an active transmission. Disconnect triggers an unkey attempt, and a failed key/release keeps conservative state. Clients must retain their connection through key/unkey; one-shot clients that close immediately after keying do not hold PTT. |
| Support configurable LAN listening | A radio attached to one machine or phone can serve applications elsewhere on the trusted network. Loopback remains the default, and LAN access is explicit because the rigctld protocol has no authentication. |
| Qualify platforms in stages | Prove the shared behavior on macOS first, then build and test Android once stable. This provides cross-platform evidence without repeatedly building a full platform matrix on a resource-limited development machine. |

The facade does not transport audio, implement a different modem, or change
Data2G's waveform. VARA-style modem command/data compatibility, rig-control
compatibility and over-air interoperability remain separate interfaces.
The implementation is a tested software increment; it does not establish
physical-radio compatibility or operation on every supported platform.

## Android

In **Settings > Rig control**, select the existing radio model, connection
and CAT/PTT settings, then enable **Share radio (rigctld)**. No modem Start,
callsign or microphone permission is required for radio-only operation.

The server defaults to `127.0.0.1:4532`. Its TCP port is editable. Enable
**Allow local-network clients** to bind all IPv4 interfaces; remote clients
use the device's IP address and configured port. The settings screen already
lists this device's IPv4 addresses under Connecting a client. Rigctld is
unauthenticated, so expose it only on a trusted network or private tunnel.

Use **Reconnect radio** after changing network/radio settings or granting
USB/Bluetooth permission. Stop the modem before reconfiguring the server.
These settings persist; manually opening the app restores an enabled server.
There is no boot startup. Switching apps leaves the foreground radio service
running. Closing the app completely or the notification's **Stop all** shuts
it down and attempts to unkey the radio.

The modem borrows the existing radio when started. Stopping the modem leaves
the server, client connections and physical radio open. The initial sharing
policy reserves transmit control for the modem for its entire running
lifetime: cached external reads continue, but external PTT and all radio-setting
writes return busy. Reads without a safe cached value also return busy.
Stop the modem to give external applications transmit/tuning control.

## Desktop / headless

Build the `data2g-rigctld` target with Qt Core/Network and Hamlib, then launch
it with the existing radio options. It opens no modem or audio devices:

```sh
native/build/data2g-rigctld --rig-model 3073 --rig-device /dev/ttyUSB0 --rig-baud 115200
# Permit clients on the LAN:
native/build/data2g-rigctld --rig-model 3073 --rig-device /dev/ttyUSB0 --listen 0.0.0.0 --port 4532
# A hardware-free dummy for local testing only:
native/build/data2g-rigctld --rig-model 1 --port 14532
rigctl -m 2 -r 127.0.0.1:14532 f
```

Use a platform-appropriate serial device (for example a Windows COM port).
The listen option accepts numeric IPv4/IPv6 addresses and defaults to IPv4
loopback. Stop the process to disable the server. A radio already reached
through NET rigctl must use a different upstream endpoint from this facade.
Desktop GUI controls for the shared service are not wired in this increment;
the desktop entry point is the standalone process. Other modem applications
can share its radio by selecting Hamlib NET rigctl instead of opening the
physical port separately.

GUI integrations share `rigctld/enabled`, `rigctld/listen`, and `rigctld/port`
through `load_rig_server_settings` / `save_rig_server_settings`. Tool-specific
paths are not part of those settings.

## Compatibility and ownership

The facade implements the operations below when the selected Hamlib backend
supports them. VFO names now refer to actual hardware VFOs; `VFOA` is no longer
an alias for whichever VFO happens to be current. Memories, VFO copy/exchange
operations, functions, parameters, raw CAT and TCI remain outside this increment.
Unsupported operations are reported explicitly rather than simulated.

| Operation | Commands |
|---|---|
| Frequency | `f` / `F`, `get_freq` / `set_freq` |
| Mode and passband | `m` / `M`, `get_mode` / `set_mode`; Hamlib mode names supported by the selected radio |
| VFO | `v` / `V`, `get_vfo` / `set_vfo`, `get_vfo_list` |
| Split routing | `s` / `S`, `get_split_vfo` / `set_split_vfo` |
| Split TX frequency | `i` / `I`, `get_split_freq` / `set_split_freq` |
| Split TX mode/passband | `x` / `X`, `get_split_mode` / `set_split_mode` |
| Combined split TX frequency/mode | `k` / `K`, `get_split_freq_mode` / `set_split_freq_mode` |
| Levels | `l` / `L`, `get_level` / `set_level`; declared subset intersected with radio support |
| PTT | `t` / `T`, `get_ptt` / `set_ptt`; setters accept 0 or 1 using configured CAT/control-line keying |
| Negotiation | `chk_vfo`, `set_vfo_opt`, `dump_state`, `get_lock_mode`, `get_info` |
| Disconnect client | `q` / `quit` |

Each connection defaults to current-VFO syntax. `\set_vfo_opt 1` enables a
VFO argument before the normal arguments for frequency, mode, split, level
and PTT commands, for example `F VFOB 14075000` or `l currVFO SWR`.
`get_vfo`, `set_vfo`, `get_vfo_list` and negotiation commands take no extra
VFO argument. `chk_vfo` reports that connection's setting; changing one client
never changes another client's syntax. `\set_vfo_opt 0` restores the default.
PTT accepts only the current VFO and never switches VFOs to key a target.

The declared level subset is `AF`, `RF`, `SQL`, `RFPOWER`, `MICGAIN`, `COMP`,
`AGC`, `ATT`, `PREAMP`, `CWPITCH`, `KEYSPD`, `IF`, `APF`, `NR`, `NOTCHF`,
`MONITOR_GAIN`, `BALANCE`, `STRENGTH`, `RAWSTR`, `SWR`, `ALC`,
`RFPOWER_METER` and `RFPOWER_METER_WATTS`. Read-only meters cannot be set.
Writable float levels in this subset use 0..1; integer levels require whole
numbers in Hamlib units (for example Hz or dB). The radio enforces its own
supported values. Capability level masks reflect the supported intersection,
including separate get/set masks. Range, tuning-step and filter metadata
comes from the selected Hamlib model's public capability table, rather than
the original synthetic USB-only table. This is model metadata, not a live
snapshot of every configuration override; in particular, an upstream NET
rigctl connection uses NET model metadata for those tables. Runtime level
masks and the VFO list are queried through Hamlib's public API. Capability
negotiation is captured when the service opens; reconnect after changing
the underlying radio configuration.

Long commands accept the usual leading backslash. Default responses and
extended `+`, `;`, `|`, `,` separators are supported. The lock-mode query emits
the additional status record consumed by Hamlib 4.7.2's NET backend.
Unsupported operations return `RPRT -11`; conflicting operations return
`RPRT -9`. A client that acquires PTT owns it until release or disconnect;
another client cannot unkey it. Failed keys retain conservative ownership
because the command may have reached the radio. Disconnect/shutdown attempts
to unkey. PTT readback reports service-owned state, not unrelated front-panel
or other physical PTT sources. All setting writes, including VFO/split/level
changes by the PTT owner, are blocked during TX. Cached reads avoid CAT traffic
while the modem reserves the radio. During external TX, current-VFO level
reads remain live for meters such as power/SWR; other controls use cached
values or return busy. Cache entries include operation, target and level;
mutations invalidate them conservatively, including failed writes that may
have reached hardware. Missing cached data returns busy rather than a value
from another VFO.

The hardware remains on one worker. Modem PTT retains priority over queued
queries; external PTT and disconnect cleanup use a separate bounded FIFO
ahead of routine queries. Each connection remains sequential, so a client
should not pipeline a long series of reads ahead of its own unkey. Control
work, per-client input and output, and client counts are bounded. Pending work is cancelled on shutdown and expired queued work does
not touch the radio. No software can guarantee an unkey after process death,
a lost cable or hardware that no longer accepts commands.

## Development and handoff

- Feature branch: `feature/rigctld`; incremental base `f6309ec`, with tracked
  agent guidance added at `32ef773`. The requested integration context is the
  fork's incremental work, not an upstream PR. Do not publish to upstream.
  The VFO/split/level increment follows `b856c6e`; the instruction source is
  root `AGENTS.md`, last updated by `d6f1247`.
- Validation starts on macOS ARM64, followed by Android ARM64 once stable,
  with expensive builds run sequentially. Hosted Actions remain disabled.
- `test_rig_service` exercises real Hamlib NET clients, partial/pipelined and
  extended responses, actual VFO selection and explicit targeting, split and
  integer/float levels, real Station start/stop cycles, PTT contention,
  disconnect/failure cleanup, shutdown and queue cancellation without radio
  hardware. The existing rig/bridge/Hamlib/transmit tests cover regressions.

For an already configured native build:

```sh
cmake --build native/build --target data2g-rigctld test_rig_service --parallel 2
ctest --test-dir native/build --output-on-failure -R '^(rig_service|rig|rig_bridge|rig_bridged|rig_hamlib|station_tx)$'
python3 tools/check_layering.py
python3 tools/check_includes.py
git diff --check
```

Android device tests can use a separate application ID via
`-DDATA2G_ANDROID_PACKAGE_NAME=org.cleverdomain.data2g.rigctldtest`. Set
`-DQT_ANDROID_DEPLOYMENT_TYPE=Debug` for a debuggable APK while retaining
optimized native code. This keeps an installed production app and its settings
separate. Source defaults retain the normal application ID.

## Local validation record (2026-11-21)

The VFO/split/level extension was validated after the initial proof:

- macOS ARM64, AppleClang 17, Qt 6.11.1, Hamlib 4.7.2: all six selected
  native tests passed; `test_rig_service` now has 241 checks. These include
  real NET clients, actual A/B selection and independent targeting, split
  frequency/mode/routing, typed levels, invalid/read-only level errors,
  separate client VFO syntax, cache invalidation, modem/PTT interlocks,
  live TX meters and bounded priority/cancellation queues. Layering,
  explicit includes and whitespace checks passed.
- Android ARM64 was built afterward with the same Qt/NDK configuration
  below. All 73 native libraries passed the 16 KB ELF/APK alignment check.
  The separate test package passed raw-protocol and standard Hamlib `rigctl`
  checks for VFO selection/targeting, split controls, float/integer levels,
  live TX meters and write interlocks. Background use and restoration after
  manual relaunch also passed with the modem stopped and no callsign.
  This repeat used temporary ADB forwarding to the all-IPv4 listener:
  direct phone Wi-Fi connectivity timed out for both the test port and the
  phone's ADB port, so direct-LAN behavior was not requalified in this run.
  The earlier direct-LAN proof is recorded below. The test server was
  disabled and forwards removed afterward; production app data was untouched.
- Physical-radio, USB/Bluetooth, Windows/Linux and actual 16 KB-kernel
  runtime qualification remain outstanding. Memory-channel operations and
  other command families outside the declared subset remain future work.
  Hosted Actions remained disabled; no performance claim is made.

Initial frequency/mode/PTT proof:

- macOS ARM64, AppleClang 17, Qt 6.11.1, Hamlib 4.7.2: the six selected
  native tests passed. The focused rig-service test was extended to 91
  checks, including an operator-visible failed disconnect unkey and a final
  shutdown retry. Layering, explicit includes and whitespace checks passed.
- Android ARM64: optimized native code and a separate debug test APK built
  with Qt 6.11.1 / NDK r27.2. On the connected API 37 phone, a Mac dummy radio
  was reached through temporary ADB reverse forwarding. A client connected
  directly to the phone's Wi-Fi address and exercised frequency, mode and
  PTT, including the standard Hamlib `rigctl` executable (exit 0), background
  operation and restoration after manual relaunch. The modem
  was stopped and no callsign was configured. The test server and forwards
  were disabled/removed afterward; the production app was not replaced.
  The radio-only foreground service reported connected-device type `0x10`,
  without microphone/media-playback service types.
- No physical radio was keyed by these tests. USB/Bluetooth/hardware-specific
  qualification remains separate. The tested phone runs a 4 KB kernel;
  runtime operation on a 16 KB kernel has not been qualified.

The first Hamlib-enabled test APK exposed a packaging defect: Hamlib's
separate autotools build had 4 KB ELF alignment although Qt's libraries and
the application were aligned for 16 KB. The older installed APK had
`DATA2G_ANDROID_RIG=OFF` and contained no Hamlib. Its library set therefore did
not exercise this build path.

The Android Hamlib recipe now supplies both 16 KB page-size linker flags and
uses a separate cache key/output directory to avoid reusing an older 4 KB
library. `tools/check_android_native_alignment.py` verifies ELF LOAD, RELRO
and uncompressed ZIP entry alignment. The normal build script also preserves
16 KB ZIP alignment when signing. The initial APK failed this check for
Hamlib; the rebuilt APK passed for all 73 native libraries, and the installed
APK was checked byte-for-byte against that rebuild. See the
[Android page-size guidance](https://developer.android.com/guide/practices/page-sizes).

A device smoke test can be reproduced without a radio:

1. Build/install a separate debug test package as described above.
2. Run `data2g-rigctld --rig-model 1 --port 14532` on the development machine.
3. Set up `adb -s "$DEVICE" reverse tcp:14532 tcp:14532`.
4. In the test app, select CAT, Network and Hamlib NET rigctl (model 2), with
   upstream endpoint `127.0.0.1:14532`. Enable the facade on port 14533 with
   LAN clients allowed. Leave the callsign blank and the modem stopped.
5. Use `rigctl -m 2 -r "$PHONE_IP:14533"` from a trusted LAN peer to exercise
   frequency, mode, VFO, split, levels and PTT against the dummy only.
   For example, with the dummy selected:

   ```sh
   rigctl -m 2 -r "$PHONE_IP:14533" V VFOB F 14105000 f V VFOA S 1 VFOB s I 14076000 i X CW 500 x L AF 0.4 l AF S 0 VFOB
   ```

   Repeat a read after Home,
   then after closing and manually reopening the app.
6. Stop/disable the test server and remove the temporary ADB reverse mapping.

Use the app's settings UI rather than assuming a device-specific settings
file location. Keep raw build/test logs in the chosen local build directories;
no machine paths or device IP addresses are required in source configuration.
