// Lifted from SSTVAE's core/rig/hamlib.cpp; see that file for the longer
// reasoning behind each choice (it is the one that met the Windows and
// Hamlib-version traps).
#include "rig/hamlib/hamlib.hpp"

#include <hamlib/rig.h>
#include <hamlib/riglist.h>

#include <algorithm>
#include <cstdarg>
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <limits>
#include <sstream>
#include <iomanip>
#include <cmath>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "rig/cm108.hpp"

namespace data2g::rig {

namespace {

// Quiet unless DATA2G_HAMLIB_DEBUG is set: a CAT failure is reported
// through our own status text. Also the level a removed sink returns to.
enum rig_debug_level_e env_debug_level() {
    const char* debug = std::getenv("DATA2G_HAMLIB_DEBUG");
    const bool verbose = debug != nullptr && *debug != '\0' && std::strcmp(debug, "0") != 0;
    return verbose ? RIG_DEBUG_TRACE : RIG_DEBUG_NONE;
}

// Hamlib's backend registry is global and loading it is not reentrant.
void load_backends_once() {
    static std::once_flag once;
    std::call_once(once, [] {
        rig_set_debug(env_debug_level());
        rig_load_all_backends();
    });
}

// rigerror() returns Hamlib's saved debug lines with the error string last;
// the first line is whatever was traced earlier ("not starting multicast
// publisher"), so keep only the last one.
std::string hamlib_error(const char* what, int code) {
    const char* raw = rigerror(code);
    std::string text = raw != nullptr ? raw : "";
    while (!text.empty() && (text.back() == '\n' || text.back() == '\r')) text.pop_back();
    const std::size_t nl = text.rfind('\n');
    if (nl != std::string::npos) text.erase(0, nl + 1);
    if (text.empty()) text = "unknown error";
    return std::string(what) + ": " + text + " (" + std::to_string(code) + ")";
}

// --- the trace sink: Hamlib hands us fmt + va_list; a line may span calls --

std::mutex& debug_mu() {
    static std::mutex m;
    return m;
}
DebugSink& debug_sink() {
    static DebugSink sink;
    return sink;
}
std::string& debug_partial() {
    static std::string partial;
    return partial;
}
constexpr std::size_t kMaxPartialBytes = 8192;  // a format with no newline can't grow it forever

std::string format_debug(const char* fmt, va_list ap) {
    va_list sizing;
    va_copy(sizing, ap);
    char stack[512];
    const int n = std::vsnprintf(stack, sizeof(stack), fmt, sizing);
    va_end(sizing);
    if (n < 0) return {};
    if (static_cast<std::size_t>(n) < sizeof(stack)) return std::string(stack, static_cast<std::size_t>(n));
    std::string big(static_cast<std::size_t>(n), '\0');
    va_list again;
    va_copy(again, ap);
    std::vsnprintf(&big[0], static_cast<std::size_t>(n) + 1, fmt, again);
    va_end(again);
    return big;
}

// A C callback under Hamlib's debug mutex: nothing may escape, and the sink
// runs outside our lock.
int debug_trampoline(enum rig_debug_level_e, rig_ptr_t, const char* fmt, va_list ap) {
    try {
        if (fmt == nullptr) return 0;
        const std::string text = format_debug(fmt, ap);
        if (text.empty()) return 0;
        std::vector<std::string> lines;
        DebugSink sink;
        {
            std::lock_guard<std::mutex> lock(debug_mu());
            sink = debug_sink();
            if (!sink) return 0;
            std::string& partial = debug_partial();
            partial += text;
            std::size_t start = 0;
            for (std::size_t nl; (nl = partial.find('\n', start)) != std::string::npos; start = nl + 1)
                lines.emplace_back(partial, start, nl - start);
            partial.erase(0, start);
            if (partial.size() > kMaxPartialBytes) {
                lines.push_back(partial);
                partial.clear();
            }
        }
        for (std::string& line : lines) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            sink(line);
        }
    } catch (...) {
    }
    return 0;
}

PortType port_type(int t) {
    switch (t) {
        case RIG_PORT_NONE: return PortType::None;
        case RIG_PORT_SERIAL: return PortType::Serial;
        case RIG_PORT_NETWORK:
        case RIG_PORT_UDP_NETWORK: return PortType::Network;
        default: return PortType::Other;
    }
}

RigModel from_caps(const struct rig_caps* caps) {
    RigModel m;
    m.model = static_cast<int>(caps->rig_model);
    m.manufacturer = caps->mfg_name != nullptr ? caps->mfg_name : "";
    m.name = caps->model_name != nullptr ? caps->model_name : "";
    m.version = caps->version != nullptr ? caps->version : "";
    const char* status = rig_strstatus(caps->status);
    m.status = status != nullptr ? status : "";
    m.port = port_type(caps->port_type);
    return m;
}

class HamlibBackend final : public RigBackend {
public:
    explicit HamlibBackend(HamlibConfig config) : config_(std::move(config)) {}
    ~HamlibBackend() override { close(); }

    void open() override {
        load_backends_once();
        if (rig_ != nullptr) return;
        // Before rig_init: a CM108 that can't be found throws with nothing to clean up.
        if (config_.ptt_method == PttMethod::Cm108) cm108_device_ = resolve_cm108_device(config_.ptt_device);
        rig_ = rig_init(static_cast<rig_model_t>(config_.model));
        if (rig_ == nullptr) throw RigError("Hamlib does not know rig model " + std::to_string(config_.model));
        // Tokens, not the port structs: those are Hamlib internals (IN_HAMLIB).
        if (!config_.device.empty()) set_conf("rig_pathname", config_.device);
        if (config_.baud > 0) set_conf("serial_speed", std::to_string(config_.baud));
        apply_serial_settings();
        apply_ptt_settings();
        set_conf("timeout", std::to_string(config_.timeout_ms));
        set_conf("retry", std::to_string(config_.retries));
        // Hamlib's own polling thread off: one command in flight, ours.
        set_conf("poll_interval", "0");
        const int rc = rig_open(rig_);
        if (rc != RIG_OK) {
            std::string msg = hamlib_error("could not open the rig", rc);
            // Hamlib opens the PTT port last and says only "I/O error": name the likely cause.
            if (config_.ptt_method == PttMethod::Cm108 && rc == -RIG_EIO)
                msg += "; if that is the CM108's " + cm108_device_ +
                       ", check that it can be opened for writing (a udev rule; see the User's Guide)";
            rig_cleanup(rig_);
            rig_ = nullptr;
            throw RigError(msg);
        }
        open_ = true;
        apply_mode();
    }

    void close() noexcept override {
        if (rig_ == nullptr) return;
        if (open_) rig_close(rig_);
        open_ = false;
        vfo_opt_ = false;
        rig_cleanup(rig_);
        rig_ = nullptr;
    }

    void set_ptt(bool on) override {
        require_open();
        // RIG_PTT_ON, not ON_MIC: on a MICDATA rig they differ (TX vs TX0).
        const ptt_t key = config_.ptt_audio == PttAudio::Data && config_.ptt_method == PttMethod::Cat ? RIG_PTT_ON_DATA : RIG_PTT_ON;
        const int rc = reconnecting([&] { return rig_set_ptt(rig_, RIG_VFO_CURR, on ? key : RIG_PTT_OFF); });
        if (rc != RIG_OK) throw RigError(hamlib_error(on ? "PTT on failed" : "PTT off failed", rc));
    }

    double frequency_hz() override {
        require_open();
        freq_t freq = 0;
        const int rc = reconnecting([&] { return rig_get_freq(rig_, RIG_VFO_CURR, &freq); });
        if (rc != RIG_OK) throw RigError(hamlib_error("could not read frequency", rc));
        return static_cast<double>(freq);
    }

    void set_frequency_hz(double hz) override {
        require_open();
        if (!std::isfinite(hz) || hz <= 0) throw RigError("invalid frequency", -1);
        const int rc = rig_set_freq(rig_, RIG_VFO_CURR, hz);
        if (rc != RIG_OK) throw RigError(hamlib_error("frequency setting failed", rc), rc);
    }

    RadioMode mode() override {
        require_open();
        rmode_t m = RIG_MODE_NONE;
        pbwidth_t width = 0;
        const int rc = rig_get_mode(rig_, RIG_VFO_CURR, &m, &width);
        if (rc != RIG_OK) throw RigError(hamlib_error("mode read failed", rc), rc);
        return {rig_strrmode(m), width};
    }

    void set_mode(const RadioMode& m) override {
        require_open();
        const rmode_t value = rig_parse_mode(m.name.c_str());
        if (value == RIG_MODE_NONE) throw RigError("unknown mode", -1);
        const int rc = rig_set_mode(rig_, RIG_VFO_CURR, value, m.width);
        if (rc != RIG_OK) throw RigError(hamlib_error("mode setting failed", rc), rc);
    }

    RadioControl control(const RadioControl& command) override {
        require_open();
        auto result = command;
        const vfo_t vfo = parse_vfo(command.target);
        // NET's default wire syntax silently drops VFO arguments. Negotiate
        // targeting on this connection before the first explicit target.
        if (config_.model == MODEL_NET_RIGCTL && vfo != RIG_VFO_CURR && !vfo_opt_) {
            const int status = rig_set_vfo_opt(rig_, 1);
            if (status != RIG_OK) throw RigError(hamlib_error("VFO targeting unavailable", status), status);
            vfo_opt_ = true;
        }
        int rc = RIG_OK;
        freq_t frequency = command.value;
        rmode_t mode = RIG_MODE_NONE;
        pbwidth_t width = command.width;
        vfo_t tx = RIG_VFO_NONE;
        split_t split = command.split ? RIG_SPLIT_ON : RIG_SPLIT_OFF;
        const auto parse_mode = [&] {
            const auto m = rig_parse_mode(command.name.c_str());
            if (m == RIG_MODE_NONE) throw RigError("unknown mode", -1);
            return m;
        };
        switch (command.op) {
            case RadioOp::GetFrequency:
                // Retain the existing idle NET reconnection behavior. An
                // explicit target is never silently retried without its VFO
                // negotiation on a freshly opened connection.
                if (vfo == RIG_VFO_CURR) result.value = frequency_hz();
                else { rc = rig_get_freq(rig_, vfo, &frequency); result.value = frequency; }
                break;
            case RadioOp::SetFrequency:
                if (!std::isfinite(frequency) || frequency <= 0) throw RigError("invalid frequency", -1);
                rc = rig_set_freq(rig_, vfo, frequency); break;
            case RadioOp::GetMode:
                rc = rig_get_mode(rig_, vfo, &mode, &width);
                result.name = rig_strrmode(mode); result.width = width; break;
            case RadioOp::SetMode: rc = rig_set_mode(rig_, vfo, parse_mode(), width); break;
            case RadioOp::GetVfo:
                rc = rig_get_vfo(rig_, &tx); result.name = rig_strvfo(tx); break;
            case RadioOp::SetVfo: rc = rig_set_vfo(rig_, parse_vfo(command.name)); break;
            case RadioOp::GetVfoList: {
                char list[512] = {};
                rc = rig_get_vfo_list(rig_, list, sizeof list); result.name = list; break;
            }
            case RadioOp::GetSplitVfo:
                rc = rig_get_split_vfo(rig_, vfo, &split, &tx);
                result.split = split == RIG_SPLIT_ON; result.name = rig_strvfo(tx); break;
            case RadioOp::SetSplitVfo:
                rc = rig_set_split_vfo(rig_, vfo, split, parse_vfo(command.name)); break;
            case RadioOp::GetSplitFrequency:
                rc = rig_get_split_freq(rig_, vfo, &frequency); result.value = frequency; break;
            case RadioOp::SetSplitFrequency:
                if (!std::isfinite(frequency) || frequency <= 0) throw RigError("invalid frequency", -1);
                rc = rig_set_split_freq(rig_, vfo, frequency); break;
            case RadioOp::GetSplitMode:
                rc = rig_get_split_mode(rig_, vfo, &mode, &width);
                result.name = rig_strrmode(mode); result.width = width; break;
            case RadioOp::SetSplitMode: rc = rig_set_split_mode(rig_, vfo, parse_mode(), width); break;
            case RadioOp::GetSplitFrequencyMode:
                rc = rig_get_split_freq_mode(rig_, vfo, &frequency, &mode, &width);
                result.value = frequency; result.name = rig_strrmode(mode); result.width = width; break;
            case RadioOp::SetSplitFrequencyMode:
                if (!std::isfinite(frequency) || frequency <= 0) throw RigError("invalid frequency", -1);
                rc = rig_set_split_freq_mode(rig_, vfo, frequency, parse_mode(), width); break;
            case RadioOp::GetLevel:
            case RadioOp::SetLevel: {
                const setting_t level = rig_parse_level(command.name.c_str());
                const bool write = command.op == RadioOp::SetLevel;
                if (!level || !(level & supported_levels) ||
                    !(write ? rig_has_set_level(rig_, level) & RIG_LEVEL_SET(supported_levels)
                            : rig_has_get_level(rig_, level)))
                    throw RigError("level unavailable", -11);
                value_t value = {};
                if (write) {
                    if (!std::isfinite(command.value)) throw RigError("invalid level", -1);
                    if (RIG_LEVEL_IS_FLOAT(level)) {
                        // All writable float levels in this declared subset are normalized.
                        if (command.value < 0 || command.value > 1) throw RigError("level outside 0..1", -1);
                        value.f = static_cast<float>(command.value);
                    } else {
                        if (command.value < std::numeric_limits<int>::min() || command.value > std::numeric_limits<int>::max() ||
                            std::floor(command.value) != command.value) throw RigError("invalid integer level", -1);
                        value.i = static_cast<int>(command.value);
                    }
                    rc = rig_set_level(rig_, vfo, level, value);
                } else {
                    rc = rig_get_level(rig_, vfo, level, &value);
                    result.value = RIG_LEVEL_IS_FLOAT(level) ? value.f : value.i;
                    result.floating_level = RIG_LEVEL_IS_FLOAT(level);
                }
                break;
            }
        }
        if (rc != RIG_OK) throw RigError(hamlib_error("radio control failed", rc), rc);
        return result;
    }

    std::string rigctld_state() override {
        require_open();
        // Public model metadata and runtime level/VFO queries only; do not
        // dereference RIG (its pthread layout differs under the Windows shim).
        const rig_caps* caps = rig_get_caps(static_cast<rig_model_t>(config_.model));
        if (!caps) throw RigError("capabilities unavailable", -11);
        std::ostringstream out;
        out << "1\n" << config_.model << "\n0\n" << std::setprecision(15);
        const auto ranges = [&](const freq_range_t* list) {
            for (int i = 0; i < HAMLIB_FRQRANGESIZ && list[i].endf != 0; ++i)
                out << list[i].startf << ' ' << list[i].endf << " 0x" << std::hex << list[i].modes << std::dec
                    << ' ' << list[i].low_power << ' ' << list[i].high_power << " 0x" << std::hex
                    << list[i].vfo << " 0x" << list[i].ant << std::dec << '\n';
            out << "0 0 0 0 0 0 0\n";
        };
        ranges(caps->rx_range_list1);
        ranges(caps->tx_range_list1);
        for (const auto& step : caps->tuning_steps) {
            if (!step.modes) break;
            out << "0x" << std::hex << step.modes << std::dec << ' ' << step.ts << '\n';
        }
        out << "0 0\n";
        for (const auto& filter : caps->filters) {
            if (!filter.modes) break;
            out << "0x" << std::hex << filter.modes << std::dec << ' ' << filter.width << '\n';
        }
        out << "0 0\n0\n0\n0\n0\n";
        for (const auto* list : {caps->preamp, caps->attenuator}) {
            for (int i = 0; i < HAMLIB_MAXDBLSTSIZ && list[i]; ++i) out << list[i] << ' ';
            out << '\n';
        }
        out << "0\n0\n0x" << std::hex << rig_has_get_level(rig_, supported_levels)
            << "\n0x" << (rig_has_set_level(rig_, supported_levels) & RIG_LEVEL_SET(supported_levels))
            << std::dec << "\n0\n0\n";
        // The adapter accepts explicit targets and lets Hamlib emulate them
        // on this worker when the physical backend cannot target natively.
        out << "vfo_ops=0\nptt_type=1\ntargetable_vfo=" << (RIG_TARGETABLE_FREQ | RIG_TARGETABLE_MODE | RIG_TARGETABLE_LEVEL)
            << "\nhas_get_vfo=" << bool(caps->get_vfo) << "\nhas_set_vfo=" << bool(caps->set_vfo)
            << "\nhas_get_freq=" << bool(caps->get_freq) << "\nhas_set_freq=" << bool(caps->set_freq)
            << "\nhas_get_mode=" << bool(caps->get_mode) << "\nhas_set_mode=" << bool(caps->set_mode)
            << "\nhas_get_split_vfo=" << bool(caps->get_split_vfo) << "\nhas_set_split_vfo=" << bool(caps->set_split_vfo)
            << "\nhas_get_split_freq=" << bool(caps->get_split_freq) << "\nhas_set_split_freq=" << bool(caps->set_split_freq)
            << "\nhas_get_split_mode=" << bool(caps->get_split_mode) << "\nhas_set_split_mode=" << bool(caps->set_split_mode)
            << "\nhas_get_ant=0\nhas_set_ant=0\nhas_get_conf=0\nhas_set_conf=0\nhas_power2mW=0\nhas_mW2power=0\ndone\n";
        return out.str();
    }

    // Through rig_get_caps_cptr: nothing here dereferences a RIG* (its
    // pthread members differ in size under the MSVC shim).
    std::string description() const override {
        const auto model = static_cast<rig_model_t>(config_.model);
        const char* mfg = rig_get_caps_cptr(model, RIG_CAPS_MFG_NAME_CPTR);
        const char* name = rig_get_caps_cptr(model, RIG_CAPS_MODEL_NAME_CPTR);
        std::string out = mfg && name ? std::string(mfg) + " " + name : "model " + std::to_string(config_.model);
        if (!config_.device.empty()) out += " at " + config_.device;
        if (config_.ptt_method == PttMethod::Cm108)
            out += ", PTT on GPIO" + std::to_string(config_.ptt_gpio) + " of " +
                   (cm108_device_.empty() ? std::string("a CM108") : cm108_device_);
        return out;
    }

private:
    static constexpr setting_t supported_levels = RIG_LEVEL_AF | RIG_LEVEL_RF | RIG_LEVEL_SQL |
        RIG_LEVEL_RFPOWER | RIG_LEVEL_MICGAIN | RIG_LEVEL_COMP | RIG_LEVEL_AGC | RIG_LEVEL_ATT |
        RIG_LEVEL_PREAMP | RIG_LEVEL_STRENGTH | RIG_LEVEL_RAWSTR | RIG_LEVEL_SWR | RIG_LEVEL_ALC |
        RIG_LEVEL_CWPITCH | RIG_LEVEL_KEYSPD | RIG_LEVEL_IF | RIG_LEVEL_APF | RIG_LEVEL_NR |
        RIG_LEVEL_NOTCHF | RIG_LEVEL_MONITOR_GAIN | RIG_LEVEL_BALANCE | RIG_LEVEL_RFPOWER_METER |
        RIG_LEVEL_RFPOWER_METER_WATTS;

    static vfo_t parse_vfo(const std::string& name) {
        const vfo_t vfo = rig_parse_vfo(name.c_str());
        if (vfo == RIG_VFO_NONE) throw RigError("unknown VFO", -1);
        return vfo;
    }

    // A rigctld can drop the connection between overs (seen with
    // kappanhang, polling off), and the next command finds the dead
    // socket: EOF on read, then EPIPE, both RIG_EIO. Reconnect and retry
    // once; a failed reopen throws its own "could not open the rig".
    template <class Call>
    int reconnecting(Call call) {
        const int rc = call();
        if (rc != -RIG_EIO) return rc;
        close();
        open();
        return call();
    }

    void require_open() const {
        if (rig_ == nullptr || !open_) throw RigError("the rig is not open");
    }

    // Token names and values from Hamlib 4.7.2's src/serial_cfg_params.h and
    // src/conf.c: a misspelled token is silently ignored, not an error.
    void apply_serial_settings() {
        switch (config_.data_bits) {
            case DataBits::Seven: set_conf("data_bits", "7"); break;
            case DataBits::Eight: set_conf("data_bits", "8"); break;
            case DataBits::Default: break;
        }
        switch (config_.stop_bits) {
            case StopBits::One: set_conf("stop_bits", "1"); break;
            case StopBits::Two: set_conf("stop_bits", "2"); break;
            case StopBits::Default: break;
        }
        switch (config_.parity) {
            case Parity::None: set_conf("serial_parity", "None"); break;
            case Parity::Odd: set_conf("serial_parity", "Odd"); break;
            case Parity::Even: set_conf("serial_parity", "Even"); break;
            case Parity::Default: break;
        }
        switch (config_.handshake) {
            case Handshake::None: set_conf("serial_handshake", "None"); break;
            case Handshake::XonXoff: set_conf("serial_handshake", "XONXOFF"); break;
            case Handshake::Hardware: set_conf("serial_handshake", "Hardware"); break;
            case Handshake::Default: break;
        }
        for (const auto& [state, token] : {std::pair{config_.dtr, "dtr_state"}, std::pair{config_.rts, "rts_state"}}) {
            if (state == LineState::High) set_conf(token, "ON");
            if (state == LineState::Low) set_conf(token, "OFF");
        }
    }

    void apply_ptt_settings() {
        switch (config_.ptt_method) {
            case PttMethod::Vox: set_conf("ptt_type", "None"); break;
            // Always RIGMICDATA: "RIG" would downgrade ON_DATA to plain mic
            // keying, and set_ptt already picks ON vs ON_DATA. Under netrigctl
            // "RIG" also lets rigctld's own ptt_type (e.g. GPIO) replace ours,
            // so the client drives a port it never opened instead of sending T.
            case PttMethod::Cat: set_conf("ptt_type", "RIGMICDATA"); break;
            case PttMethod::Dtr: set_conf("ptt_type", "DTR"); break;
            case PttMethod::Rts: set_conf("ptt_type", "RTS"); break;
            // GPIO1..8 is Hamlib's ptt_bitnum 0..7; open() found the device.
            case PttMethod::Cm108: {
                set_conf("ptt_type", "CM108");
                set_conf("ptt_pathname", cm108_device_);
                // Hamlib 4.7.2's conf.c stores ptt_bitnum in the CAT port's
                // parm union too, over parm.serial.rate: a serial rig would
                // open at "2 baud" and fail with "Invalid configuration".
                // Put the speed back (get_conf: none on a network rig).
                const std::optional<std::string> speed = get_conf("serial_speed");
                set_conf("ptt_bitnum", std::to_string(config_.ptt_gpio - 1));
                if (speed) set_conf("serial_speed", *speed);
                break;
            }
        }
        if (!config_.ptt_device.empty() && (config_.ptt_method == PttMethod::Dtr || config_.ptt_method == PttMethod::Rts))
            set_conf("ptt_pathname", config_.ptt_device);
    }

    // A rig command, after open; a refusal is not fatal (it still keys).
    void apply_mode() {
        rmode_t mode = RIG_MODE_NONE;
        switch (config_.mode) {
            case RigMode::Usb: mode = RIG_MODE_USB; break;
            case RigMode::PktUsb: mode = RIG_MODE_PKTUSB; break;
            case RigMode::None: return;
        }
        rig_set_mode(rig_, RIG_VFO_CURR, mode, RIG_PASSBAND_NOCHANGE);
    }

    // nullopt: a token the backend lacks, or one its port doesn't have.
    std::optional<std::string> get_conf(const char* name) const {
        const hamlib_token_t token = rig_token_lookup(rig_, name);
        if (token == RIG_CONF_END) return std::nullopt;
        char buf[128] = {};
        if (rig_get_conf2(rig_, token, buf, sizeof buf) != RIG_OK) return std::nullopt;
        return std::string(buf);
    }

    // A token the backend lacks is skipped (netrigctl has no serial retry).
    void set_conf(const char* name, const std::string& value) {
        const hamlib_token_t token = rig_token_lookup(rig_, name);
        if (token == RIG_CONF_END) return;
        rig_set_conf(rig_, token, value.c_str());
    }

    HamlibConfig config_;
    std::string cm108_device_;  // PttMethod::Cm108: the hidraw device open() resolved
    RIG* rig_ = nullptr;
    bool open_ = false;
    bool vfo_opt_ = false;
};

}  // namespace

std::vector<RigModel> list_models() {
    load_backends_once();
    std::vector<RigModel> models;
    rig_list_foreach(
        [](const struct rig_caps* caps, rig_ptr_t data) -> int {
            static_cast<std::vector<RigModel>*>(data)->push_back(from_caps(caps));
            return 1;  // keep going
        },
        &models);
    std::sort(models.begin(), models.end(), [](const RigModel& a, const RigModel& b) {
        if (a.manufacturer != b.manufacturer) return a.manufacturer < b.manufacturer;
        if (a.name != b.name) return a.name < b.name;
        return a.model < b.model;
    });
    return models;
}

std::optional<RigModel> model_info(int model) {
    load_backends_once();
    struct Search {
        int model;
        std::optional<RigModel> out;
    } search{model, std::nullopt};
    rig_list_foreach(
        [](const struct rig_caps* caps, rig_ptr_t data) -> int {
            auto* s = static_cast<Search*>(data);
            if (static_cast<int>(caps->rig_model) != s->model) return 1;
            s->out = from_caps(caps);
            return 0;  // stop
        },
        &search);
    return search.out;
}

SerialDefaults serial_defaults(int model) {
    load_backends_once();

    struct Search {
        int model;
        SerialDefaults out;
        bool found = false;
    } search{model, SerialDefaults{}, false};

    // `rig_list_foreach` rather than a `RIG*`: there is no
    // `rig_get_caps_int` token for the serial fields, and reading them
    // out of an initialised RIG would mean dereferencing a pointer whose
    // struct carries pthread members -- the thing CLAUDE.md forbids on
    // Windows. `struct rig_caps` has none, which is why it is the one
    // Hamlib struct this file reads through.
    rig_list_foreach(
        [](const struct rig_caps* caps, rig_ptr_t data) -> int {
            auto* s = static_cast<Search*>(data);
            if (static_cast<int>(caps->rig_model) != s->model) return 1;
            s->found = true;
            // `serial_rate_max`, not a mean or a minimum: `rig_init`
            // takes the default from that field and its own comment
            // says "fastest !". Matching it is the whole point -- a
            // different choice here would make a bridged rig run at a
            // different speed than the same rig on a desktop.
            if (caps->serial_rate_max > 0) s->out.baud = caps->serial_rate_max;
            if (caps->serial_data_bits > 0) s->out.data_bits = caps->serial_data_bits;
            if (caps->serial_stop_bits > 0) s->out.stop_bits = caps->serial_stop_bits;
            switch (caps->serial_parity) {
                case RIG_PARITY_ODD: s->out.parity = SerialParams::kOdd; break;
                case RIG_PARITY_EVEN: s->out.parity = SerialParams::kEven; break;
                default: s->out.parity = SerialParams::kNoParity; break;
            }
            switch (caps->serial_handshake) {
                case RIG_HANDSHAKE_HARDWARE: s->out.flow = SerialParams::kRtsCts; break;
                case RIG_HANDSHAKE_XONXOFF: s->out.flow = SerialParams::kXonXoff; break;
                default: s->out.flow = SerialParams::kNoFlow; break;
            }
            return 0;  // stop
        },
        &search);

    // A model Hamlib does not know is a configuration the operator has
    // to fix anyway, and `rig_init` will refuse it a moment later with a
    // better message than this function could give. 9600 8-N-1 rather
    // than throwing, so a settings screen can still render.
    return search.out;
}

bool supports_ptt_audio_source(int model) {
    load_backends_once();
    return rig_get_caps_int(static_cast<rig_model_t>(model), RIG_CAPS_PTT_TYPE) == RIG_PTT_RIG_MICDATA;
}

std::unique_ptr<RigBackend> make_hamlib_backend(const HamlibConfig& config) {
    return std::make_unique<HamlibBackend>(config);
}

std::string hamlib_version() {
    const char* v = rig_version();  // a function, not the data symbol: MSVC can't import data from a DLL
    return v != nullptr ? v : "";
}

void set_debug_sink(DebugSink sink) {
    load_backends_once();  // first, or its rig_set_debug would undo ours
    const bool active = static_cast<bool>(sink);
    {
        std::lock_guard<std::mutex> lock(debug_mu());
        debug_sink() = std::move(sink);
        debug_partial().clear();
    }
    // Registered only while a sink exists: rig_debug writes to stderr *or*
    // the callback, so a permanent one would swallow DATA2G_HAMLIB_DEBUG.
    rig_set_debug_callback(active ? &debug_trampoline : nullptr, nullptr);
    rig_set_debug(active ? RIG_DEBUG_TRACE : env_debug_level());
}

}  // namespace data2g::rig
