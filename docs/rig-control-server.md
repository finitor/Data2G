# Rig-control server

The native application layer provides a Hamlib NET rigctl facade over the
radio Data2G already controls. The shared `app::RigService` has no Android
API dependency. Android supplies its foreground-service and USB/Bluetooth
integration; desktops can run the same service through `data2g-rigctld`.
This adds radio control, not audio streaming or a different on-air protocol.

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
lifetime: external reads continue, but external PTT and tuning return busy.
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

This is a current-VFO subset, not a full replacement for every Hamlib command.
`VFOA` is the facade's alias for the physical rig's current VFO; it does not
switch the hardware VFO. Split, levels, memories, raw CAT, arbitrary VFO
switching and TCI are outside this increment.

| Operation | Commands |
|---|---|
| Frequency | `f` / `F`, `get_freq` / `set_freq` |
| Mode and passband | `m` / `M`, `get_mode` / `set_mode`; setters accept USB, LSB, PKTUSB |
| PTT | `t` / `T`, `get_ptt` / `set_ptt`; setters accept 0 or 1 using configured CAT/control-line keying |
| Negotiation | `chk_vfo`, `dump_state`, `get_vfo`, `get_lock_mode`, `get_info` |
| Disconnect client | `q` / `quit` |

Long commands accept the usual leading backslash. Default responses and
extended `+`, `;`, `|`, `,` separators are supported. The lock-mode query emits
the additional status record consumed by Hamlib 4.7.2's NET backend.
Unsupported operations return `RPRT -11`; conflicting operations return
`RPRT -9`. A client that acquires PTT owns it until release or disconnect;
another client cannot unkey it. Failed keys retain conservative ownership
because the command may have reached the radio. Disconnect/shutdown attempts
to unkey. PTT readback reports service-owned state, not unrelated front-panel
or other physical PTT sources. Cached frequency/mode reads avoid CAT traffic
while transmitting or while the modem reserves the radio.

The hardware remains on one worker. Modem PTT retains priority over queued
queries. Control work, per-client input and output, and client counts are
bounded. Pending work is cancelled on shutdown and expired queued work does
not touch the radio. No software can guarantee an unkey after process death,
a lost cable or hardware that no longer accepts commands.

## Development and handoff

- Feature branch: `feature/rigctld`; incremental base `f6309ec`, with tracked
  agent guidance added at `32ef773`. The requested integration context is the
  fork's incremental work, not an upstream PR. Do not publish to upstream.
- Validation starts on macOS ARM64, followed by Android ARM64 once stable,
  with expensive builds run sequentially. Hosted Actions remain disabled.
- `test_rig_service` exercises real Hamlib NET clients, partial/pipelined and
  extended responses, real Station start/stop cycles, PTT contention,
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
   frequency, mode and PTT against the dummy only. Repeat a read after Home,
   then after closing and manually reopening the app.
6. Stop/disable the test server and remove the temporary ADB reverse mapping.

Use the app's settings UI rather than assuming a device-specific settings
file location. Keep raw build/test logs in the chosen local build directories;
no machine paths or device IP addresses are required in source configuration.
