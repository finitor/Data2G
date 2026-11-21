// What the controller needs a radio to do.
//
// A seam: it keeps the part with the hard-won *behaviour* -- one handle
// on one thread, PTT that never queues behind a stale poll, a teardown
// that does not block -- in `data2g_core` (RigController), buildable and
// testable with no libhamlib and no radio. `core/rig/hamlib/hamlib.hpp`
// (data2g_rig) is the real implementation; `tests/test_rig.cpp` uses a
// fake that accepts and never answers, which is the scenario SSTVAE's
// `test_rig_controller.py` exists for.
//
// Every method here **blocks**, and may block for the rig's timeout.
// That is the whole problem this subsystem is arranged around.

#ifndef DATA2G_RIG_BACKEND_HPP
#define DATA2G_RIG_BACKEND_HPP

#include <stdexcept>
#include <cstdint>
#include <string>

namespace data2g::rig {

class RigError : public std::runtime_error {
public:
    explicit RigError(const std::string& what, int code = -6) : std::runtime_error(what), code(code) {}
    int code;  // Hamlib-compatible error, without a libhamlib dependency
};

struct RadioMode {
    std::string name;
    long width = 0;
};

// Optional radio controls shared by the portable protocol adapter and Hamlib.
// No Hamlib types cross this boundary. VFO names use Hamlib's public spelling.
enum class RadioOp {
    GetFrequency, SetFrequency, GetMode, SetMode, GetVfo, SetVfo, GetVfoList,
    GetSplitVfo, SetSplitVfo, GetSplitFrequency, SetSplitFrequency,
    GetSplitMode, SetSplitMode, GetSplitFrequencyMode, SetSplitFrequencyMode,
    GetLevel, SetLevel
};
struct RadioControl {
    RadioControl(RadioOp operation) : op(operation) {}
    RadioOp op;
    std::string target = "currVFO";
    std::string name;  // VFO, TX VFO, mode or level name, according to op
    double value = 0;  // frequency or level
    long width = 0;
    bool split = false;
    bool floating_level = false;  // response type for GetLevel
};

class RigBackend {
public:
    virtual ~RigBackend() = default;

    // Open the radio. Throws RigError with something an operator can act
    // on -- the wrong device path and a busy port are both routine.
    virtual void open() = 0;

    // Close it. Called from the worker thread as it exits, and must not
    // throw: by then there is nobody left to tell.
    virtual void close() noexcept = 0;

    virtual void set_ptt(bool on) = 0;

    // Dial frequency in Hz.
    virtual double frequency_hz() = 0;

    // Optional controls, used by the rigctld facade. Existing key-only backends
    // remain valid and explicitly report unsupported operations.
    virtual void set_frequency_hz(double) { throw RigError("frequency setting unavailable", -11); }
    virtual RadioMode mode() { throw RigError("mode unavailable", -11); }
    virtual void set_mode(const RadioMode&) { throw RigError("mode setting unavailable", -11); }
    virtual std::string rigctld_state() { throw RigError("capabilities unavailable", -11); }
    virtual RadioControl control(const RadioControl& command) {
        auto result = command;
        if (command.target != "currVFO") throw RigError("VFO targeting unavailable", -11);
        switch (command.op) {
            case RadioOp::GetFrequency: result.value = frequency_hz(); break;
            case RadioOp::SetFrequency: set_frequency_hz(command.value); break;
            case RadioOp::GetMode: {
                const auto m = mode(); result.name = m.name; result.width = m.width; break;
            }
            case RadioOp::SetMode: set_mode({command.name, command.width}); break;
            default: throw RigError("radio control unavailable", -11);
        }
        return result;
    }

    // For status text. Need not be the model name the user picked.
    virtual std::string description() const = 0;
};

}  // namespace data2g::rig

#endif
