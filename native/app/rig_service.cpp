#include "rig_service.hpp"

#include "app/log.hpp"

#include <QHostAddress>
#include <QTcpSocket>
#include <QPointer>
#include <QByteArray>
#include <QSettings>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstddef>
#include <deque>
#include <future>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace data2g::app {
RigServerSettings load_rig_server_settings(QSettings& settings) {
    RigServerSettings config;
    config.enabled = settings.value("rigctld/enabled", settings.value("android/rigctld", false)).toBool();
    bool valid = false;
    const auto port = settings.value("rigctld/port", 4532).toUInt(&valid);
    if (valid && port > 0 && port <= 65535) config.port = static_cast<quint16>(port);
    const auto listen = settings.value("rigctld/listen", "127.0.0.1").toString();
    QHostAddress address;
    if (address.setAddress(listen)) config.listen = listen;
    return config;
}
void save_rig_server_settings(QSettings& settings, const RigServerSettings& config) {
    settings.setValue("rigctld/enabled", config.enabled);
    settings.setValue("rigctld/port", config.port);
    settings.setValue("rigctld/listen", config.listen);
    settings.remove("android/rigctld");
}
struct SharedRadio {
    std::shared_ptr<rig::RigController> controller;
    std::mutex mutex;
    bool modem = false;
    bool stopping = false;
    bool ready = false;
    bool ptt = false;  // service-owned PTT, including an attempted key
    std::uint64_t owner = 0;
    std::optional<double> frequency;
    std::optional<rig::RadioMode> mode;
    std::optional<std::string> vfo;
    using CacheKey = std::tuple<rig::RadioOp, std::string, std::string>;
    std::map<CacheKey, rig::RadioControl> reads;
    std::string caps, description, status = "Radio connecting";
};
namespace {
class OwnedBackend : public rig::RigBackend {
public:
    OwnedBackend(std::unique_ptr<rig::RigBackend> backend, std::shared_ptr<SharedRadio> state)
        : backend_(std::move(backend)), state_(std::move(state)) {}
    void open() override {
        backend_->open();
        std::optional<double> frequency;
        std::optional<rig::RadioMode> mode;
        std::string caps;
        std::optional<std::string> vfo;
        try { vfo = backend_->control({rig::RadioOp::GetVfo}).name; } catch (...) {}
        try { frequency = backend_->frequency_hz(); } catch (...) {}
        try { mode = backend_->mode(); } catch (...) {}
        try { caps = backend_->rigctld_state(); } catch (...) {}
        std::lock_guard lock(state_->mutex);
        state_->description = backend_->description();
        state_->frequency = frequency;
        state_->mode = mode;
        state_->vfo = vfo;
        state_->caps = std::move(caps);
        state_->ready = true;
    }
    void close() noexcept override {
        if (keyed_) { try { backend_->set_ptt(false); } catch (...) {} }
        backend_->close();
        std::lock_guard lock(state_->mutex);
        state_->ready = false;
        state_->ptt = false;
    }
    void set_ptt(bool on) override {
        if (on) {
            keyed_ = true;
            std::lock_guard lock(state_->mutex);
            state_->ptt = true;  // a failed key may still have reached the radio
        }
        if (on) state_->controller->pause_polling();
        backend_->set_ptt(on);
        if (!on) state_->controller->resume_polling();
        keyed_ = on;
        std::lock_guard lock(state_->mutex);
        state_->ptt = on;
    }
    double frequency_hz() override { return backend_->frequency_hz(); }
    void set_frequency_hz(double hz) override { backend_->set_frequency_hz(hz); }
    rig::RadioMode mode() override { return backend_->mode(); }
    void set_mode(const rig::RadioMode& mode) override { backend_->set_mode(mode); }
    std::string rigctld_state() override { return backend_->rigctld_state(); }
    rig::RadioControl control(const rig::RadioControl& command) override { return backend_->control(command); }
    std::string description() const override { return backend_->description(); }
private:
    std::unique_ptr<rig::RigBackend> backend_;
    std::shared_ptr<SharedRadio> state_;
    bool keyed_ = false;
};
class BorrowedBackend : public rig::RigBackend {
public:
    explicit BorrowedBackend(std::shared_ptr<SharedRadio> state) : state_(std::move(state)) {}
    void open() override {
        std::lock_guard lock(state_->mutex);
        if (!state_->ready || !state_->modem || state_->stopping) throw rig::RigError("radio unavailable");
    }
    void close() noexcept override {}  // Station does not own the physical radio
    void set_ptt(bool on) override { state_->controller->ptt_function()(on); }
    double frequency_hz() override {
        std::lock_guard lock(state_->mutex);
        if (!state_->frequency) throw rig::RigError("frequency unavailable");
        return *state_->frequency;
    }
    std::string description() const override {
        std::lock_guard lock(state_->mutex);
        return state_->description;
    }
private:
    std::shared_ptr<SharedRadio> state_;
};
struct Reply {
    int error = 0;
    bool report = false;
    std::vector<std::pair<std::string, std::string>> fields;
    std::string raw;
};
struct Command {
    std::string name;
    std::vector<std::string> args;
    char separator = 0;
    std::string header;
};
Command parse(const QByteArray& line) {
    std::string text = line.toStdString();
    Command cmd;
    if (!text.empty() && (text[0] == '+' || text[0] == ';' || text[0] == '|' || text[0] == ',')) {
        cmd.separator = text[0] == '+' ? '\n' : text[0];
        text.erase(0, 1);
    }
    std::istringstream in(text);
    in >> cmd.name;
    if (!cmd.name.empty() && cmd.name[0] == '\\') cmd.name.erase(0, 1);
    static const std::map<std::string, std::string> names = {
        {"f", "get_freq"}, {"F", "set_freq"}, {"m", "get_mode"}, {"M", "set_mode"},
        {"t", "get_ptt"}, {"T", "set_ptt"}, {"v", "get_vfo"}, {"V", "set_vfo"},
        {"s", "get_split_vfo"}, {"S", "set_split_vfo"}, {"i", "get_split_freq"}, {"I", "set_split_freq"},
        {"x", "get_split_mode"}, {"X", "set_split_mode"}, {"k", "get_split_freq_mode"}, {"K", "set_split_freq_mode"},
        {"l", "get_level"}, {"L", "set_level"}, {"_", "get_info"}, {"q", "quit"}
    };
    if (const auto n = names.find(cmd.name); n != names.end()) cmd.name = n->second;
    std::string arg;
    while (in >> arg) cmd.args.push_back(arg);
    cmd.header = cmd.name + ':';
    for (const auto& a : cmd.args) cmd.header += " " + a;
    return cmd;
}
QByteArray format(const Command& cmd, const Reply& reply) {
    std::string out;
    if (cmd.separator) out = cmd.header + cmd.separator;
    if (reply.error == 0) {
        if (!reply.raw.empty()) {
            auto raw = reply.raw;
            if (cmd.separator) std::replace(raw.begin(), raw.end(), '\n', cmd.separator);
            out += raw;
        }
        for (const auto& [name, value] : reply.fields)
            out += (cmd.separator ? name + ": " : "") + value + (cmd.separator ? cmd.separator : '\n');
    }
    if (cmd.separator || reply.error || reply.report || (reply.fields.empty() && reply.raw.empty()))
        out += "RPRT " + std::to_string(reply.error) + (cmd.separator ? cmd.separator : '\n');
    return QByteArray::fromStdString(out);
}
double number(const std::string& text) {
    std::size_t n = 0;
    double value;
    try { value = std::stod(text, &n); } catch (...) { throw rig::RigError("invalid number", -1); }
    if (n != text.size() || !std::isfinite(value)) throw rig::RigError("invalid number", -1);
    return value;
}
}  // namespace
struct RigService::Client {
    QPointer<QTcpSocket> socket;
    std::uint64_t id = 0;
    bool vfo_opt = false;  // per connection, accessed only on the radio worker
    std::atomic<bool> alive{true};
    QByteArray input;
    std::deque<QByteArray> lines;
    std::future<void> pending;
    std::shared_ptr<Reply> reply;
    Command command;
};
struct RigService::Clients {
    std::vector<std::shared_ptr<Client>> list;
    std::vector<std::future<void>> cleanup;
    std::uint64_t next_id = 0;
};
RigService::RigService(std::unique_ptr<rig::RigBackend> backend, quint16 port, QHostAddress address)
    : radio_(std::make_shared<SharedRadio>()), clients_(std::make_unique<Clients>()) {
    if (!backend) throw rig::RigError("no radio backend");
    if (address.isNull()) throw rig::RigError("invalid listen address", -1);
    if (!server_.listen(address, port)) throw rig::RigError(server_.errorString().toStdString());
    const std::weak_ptr<SharedRadio> weak = radio_;
    radio_->controller = std::make_shared<rig::RigController>([weak](std::optional<double> hz) {
        if (auto s = weak.lock()) { std::lock_guard lock(s->mutex); s->frequency = hz; }
    }, [weak](const std::string& status, bool error) {
        if (auto s = weak.lock()) { std::lock_guard lock(s->mutex); s->status = status; }
        if (error) log_line(ERROR, "rig server: " + status);
    });
    radio_->controller->start(std::make_unique<OwnedBackend>(std::move(backend), radio_));
    connect(&server_, &QTcpServer::newConnection, this, [this] { accept(); });
    connect(&timer_, &QTimer::timeout, this, [this] {
        using namespace std::chrono_literals;
        for (auto i = clients_->cleanup.begin(); i != clients_->cleanup.end();) {
            if (i->wait_for(0ms) != std::future_status::ready) { ++i; continue; }
            try { i->get(); }
            catch (const std::exception& e) {
                const std::string message = std::string("PTT release failed; stop/reconnect radio: ") + e.what();
                { std::lock_guard lock(radio_->mutex); radio_->status = message; }
                log_line(ERROR, "rig server: " + message);
            }
            i = clients_->cleanup.erase(i);
        }
        for (auto& c : clients_->list) process(c);
        std::erase_if(clients_->list, [](const auto& c) { return !c->alive && !c->pending.valid(); });
    });
    timer_.start(20);
}
RigService::~RigService() { stop(); }
void RigService::stop() {
    server_.close();
    timer_.stop();
    { std::lock_guard lock(radio_->mutex); radio_->stopping = true; }
    for (auto& c : clients_->list) {
        c->alive = false;
        if (c->socket) { c->socket->disconnect(this); c->socket->abort(); c->socket->deleteLater(); }
    }
    radio_->controller->stop();  // OwnedBackend unkeys on its hardware worker
    clients_->list.clear();
    clients_->cleanup.clear();
}
bool RigService::wait_for_shutdown(double seconds) { return radio_->controller->wait_for_shutdown(seconds); }
std::optional<double> RigService::frequency() const { std::lock_guard lock(radio_->mutex); return radio_->frequency; }
QString RigService::status() const { std::lock_guard lock(radio_->mutex); return QString::fromStdString(radio_->status); }
void RigService::reserve_modem() {
    for (const auto& c : clients_->list)
        if (c->pending.valid()) throw rig::RigError("radio command in progress; retry modem start", -9);
    if (!clients_->cleanup.empty()) throw rig::RigError("radio cleanup in progress", -9);
    std::lock_guard lock(radio_->mutex);
    if (!radio_->ready || radio_->stopping) throw rig::RigError("radio is not connected");
    if (radio_->owner || radio_->ptt) throw rig::RigError("external client owns PTT; release it before starting the modem", -9);
    radio_->modem = true;
}
void RigService::release_modem() { std::lock_guard lock(radio_->mutex); radio_->modem = false; }
std::unique_ptr<rig::RigBackend> RigService::modem_backend() { return std::make_unique<BorrowedBackend>(radio_); }
void RigService::accept() {
    while (auto* socket = server_.nextPendingConnection()) {
        if (clients_->list.size() >= 8) { socket->abort(); socket->deleteLater(); continue; }
        auto c = std::make_shared<Client>();
        c->socket = socket;
        c->id = ++clients_->next_id;
        socket->setReadBufferSize(4096);
        clients_->list.push_back(c);
        connect(socket, &QTcpSocket::readyRead, this, [this, c] { read(c); });
        connect(socket, &QTcpSocket::disconnected, this, [this, c] { disconnect(c); });
    }
}
void RigService::disconnect(const std::shared_ptr<Client>& c) {
    if (!c->alive.exchange(false)) return;
    if (c->socket) c->socket->deleteLater();
    {
        std::lock_guard lock(radio_->mutex);
        if (radio_->owner != c->id) return;
    }
    try {
        clients_->cleanup.push_back(radio_->controller->request([s = radio_, id = c->id](rig::RigBackend& backend) {
            bool owns;
            { std::lock_guard lock(s->mutex); owns = s->owner == id; }
            if (!owns) return;
            backend.set_ptt(false);
            std::lock_guard lock(s->mutex);
            s->owner = 0;
        }, true));
    } catch (...) {}  // stop's worker-owned close is the final backstop
}
void RigService::read(const std::shared_ptr<Client>& c) {
    if (!c->alive || !c->socket) return;
    c->input += c->socket->readAll();
    if (c->input.size() > 4096) { c->socket->abort(); return; }
    while (true) {
        const auto n = c->input.indexOf('\n');
        if (n < 0) break;
        const auto line = c->input.left(n).trimmed();
        c->input.remove(0, n + 1);
        if (!line.isEmpty()) c->lines.push_back(line);
        if (c->lines.size() > 16) { c->socket->abort(); return; }
    }
    process(c);
}
void RigService::process(const std::shared_ptr<Client>& c) {
    using namespace std::chrono_literals;
    if (c->pending.valid()) {
        if (c->pending.wait_for(0ms) != std::future_status::ready) return;
        try { c->pending.get(); }
        catch (const rig::RigError& e) { c->reply->error = e.code; }
        catch (...) { c->reply->error = -6; }
        if (c->alive && c->socket) {
            c->socket->write(format(c->command, *c->reply));
            if (c->socket->bytesToWrite() > 65536) c->socket->abort();
        }
    }
    if (!c->alive || c->lines.empty()) return;
    c->command = parse(c->lines.front());
    c->lines.pop_front();
    if (c->command.name == "quit") { c->socket->write("RPRT 0\n"); c->socket->disconnectFromHost(); return; }
    c->reply = std::make_shared<Reply>();
    try {
        c->pending = radio_->controller->request([s = radio_, c, cmd = c->command, reply = c->reply](rig::RigBackend& backend) {
            if (!c->alive) throw rig::RigError("client disconnected");
            const auto& name = cmd.name;
            auto args = cmd.args;
            const auto need = [&](std::size_t n) { if (args.size() != n) throw rig::RigError("wrong argument count", -1); };
            if (name == "chk_vfo") { need(0); reply->fields = {{"ChkVFO", c->vfo_opt ? "1" : "0"}}; return; }
            if (name == "set_vfo_opt") {
                need(1);
                if (args[0] != "0" && args[0] != "1") throw rig::RigError("invalid VFO option", -1);
                c->vfo_opt = args[0] == "1"; return;
            }
            // Hamlib 4.7.2 consumes both the value and a status record here.
            if (name == "get_lock_mode") { need(0); reply->fields = {{"Locked", "0"}}; reply->report = true; return; }
            if (name == "dump_state") {
                need(0); std::lock_guard lock(s->mutex);
                if (s->caps.empty()) throw rig::RigError("capabilities unavailable", -11);
                reply->raw = s->caps; return;
            }
            if (name == "get_info") { need(0); reply->fields = {{"Info", "Data2G shared rig proxy"}}; return; }
            using Op = rig::RadioOp;
            static const std::map<std::string, Op> operations = {
                {"get_freq", Op::GetFrequency}, {"set_freq", Op::SetFrequency},
                {"get_mode", Op::GetMode}, {"set_mode", Op::SetMode},
                {"get_vfo", Op::GetVfo}, {"set_vfo", Op::SetVfo}, {"get_vfo_list", Op::GetVfoList},
                {"get_split_vfo", Op::GetSplitVfo}, {"set_split_vfo", Op::SetSplitVfo},
                {"get_split_freq", Op::GetSplitFrequency}, {"set_split_freq", Op::SetSplitFrequency},
                {"get_split_mode", Op::GetSplitMode}, {"set_split_mode", Op::SetSplitMode},
                {"get_split_freq_mode", Op::GetSplitFrequencyMode}, {"set_split_freq_mode", Op::SetSplitFrequencyMode},
                {"get_level", Op::GetLevel}, {"set_level", Op::SetLevel}
            };
            const bool ptt = name == "get_ptt" || name == "set_ptt";
            const auto operation = operations.find(name);
            if (!ptt && operation == operations.end()) throw rig::RigError("command unsupported", -11);
            rig::RadioControl request{ptt ? Op::GetVfo : operation->second};
            const bool no_target = !ptt && (request.op == Op::GetVfo || request.op == Op::SetVfo || request.op == Op::GetVfoList);
            if (c->vfo_opt && !no_target) {
                if (args.empty()) throw rig::RigError("missing VFO", -1);
                request.target = args.front(); args.erase(args.begin());
            }
            const bool write = name.starts_with("set_");
            bool cached, transmitting, modem;
            {
                std::lock_guard lock(s->mutex);
                if (!s->ready || s->stopping) throw rig::RigError("radio unavailable");
                if (write && (s->modem || (s->owner && s->owner != c->id))) throw rig::RigError("radio busy", -9);
                modem = s->modem; transmitting = s->ptt; cached = modem || transmitting;
                // NET clients can spell currVFO as the actual VFO name on the
                // wire. During a reservation, use the same current-VFO cache
                // and meter path without allowing a temporary VFO switch.
                if (!ptt && !write && cached && s->vfo && request.target == *s->vfo) request.target = "currVFO";
            }
            if (ptt && request.target != "currVFO") {
                // PTT never temporarily switches VFOs. Resolve an explicit
                // target while idle, then retain that identity through unkey.
                if (!cached) {
                    const auto actual = backend.control({Op::GetVfo});
                    std::lock_guard lock(s->mutex);
                    if (s->vfo && *s->vfo != actual.name) { s->frequency.reset(); s->mode.reset(); s->reads.clear(); }
                    s->vfo = actual.name;
                }
                std::lock_guard lock(s->mutex);
                if (!s->vfo || request.target != *s->vfo) throw rig::RigError("PTT requires the current VFO", -11);
            }
            if (name == "get_ptt") {
                need(0); std::lock_guard lock(s->mutex);
                reply->fields = {{"PTT", s->ptt ? "1" : "0"}}; return;
            }
            if (name == "set_ptt") {
                need(1);
                if (args[0] != "0" && args[0] != "1") throw rig::RigError("unsupported PTT type", -1);
                const bool on = args[0] == "1";
                {
                    std::lock_guard lock(s->mutex);
                    if (!c->alive) throw rig::RigError("client disconnected");
                    if (on && s->ptt && s->owner != c->id) throw rig::RigError("radio transmitting", -9);
                    if (on) s->owner = c->id;
                }
                backend.set_ptt(on);
                { std::lock_guard lock(s->mutex); if (!on) s->owner = 0; }
                return;
            }
            if (write && cached) throw rig::RigError("radio transmitting", -9);
            const auto frequency = [&](std::size_t i) {
                const auto hz = number(args[i]);
                if (hz <= 0) throw rig::RigError("invalid frequency", -1);
                return hz;
            };
            const auto mode = [&](std::size_t i) {
                request.name = args[i];
                const double width = number(args[i + 1]);
                if (width < -1 || width > 100000 || std::floor(width) != width) throw rig::RigError("invalid passband", -1);
                request.width = static_cast<long>(width);
            };
            switch (request.op) {
                case Op::SetFrequency: case Op::SetSplitFrequency: need(1); request.value = frequency(0); break;
                case Op::SetMode: case Op::SetSplitMode: need(2); mode(0); break;
                case Op::SetSplitFrequencyMode: need(3); request.value = frequency(0); mode(1); break;
                case Op::SetVfo: need(1); request.name = args[0]; break;
                case Op::SetSplitVfo:
                    need(2);
                    if (args[0] != "0" && args[0] != "1") throw rig::RigError("invalid split state", -1);
                    request.split = args[0] == "1"; request.name = args[1]; break;
                case Op::GetLevel: need(1); request.name = args[0]; break;
                case Op::SetLevel: need(2); request.name = args[0]; request.value = number(args[1]); break;
                default: need(0); break;
            }
            const SharedRadio::CacheKey key{request.op, request.target, request.name};
            auto result = request;
            if (write) {
                // Invalidate before the call: a reported failure can still have
                // changed hardware. Never reuse another VFO's frequency/mode.
                {
                    std::lock_guard lock(s->mutex);
                    s->reads.clear();
                    if (request.op != Op::SetLevel) { s->frequency.reset(); s->mode.reset(); }
                    if (request.op == Op::SetVfo || request.op == Op::SetSplitVfo) s->vfo.reset();
                }
                backend.control(request);
                // Preserve the existing current-frequency/mode readback. Other
                // writes wait for a getter/poll rather than a chain of CAT reads.
                if (request.target == "currVFO" && request.op == Op::SetFrequency) {
                    const auto hz = backend.frequency_hz(); std::lock_guard lock(s->mutex); s->frequency = hz;
                } else if (request.target == "currVFO" && request.op == Op::SetMode) {
                    const auto m = backend.mode(); std::lock_guard lock(s->mutex); s->mode = m;
                } else if (request.op == Op::SetVfo) {
                    const auto v = backend.control({Op::GetVfo}); std::lock_guard lock(s->mutex); s->vfo = v.name;
                }
                return;
            }
            // A level read of the current VFO is useful during external TX
            // (power/SWR). Never retarget a meter read during TX, and never send
            // extra CAT reads while the modem reserves the radio.
            if (transmitting && !modem && request.op == Op::GetLevel && request.target == "currVFO") cached = false;
            if (request.op == Op::GetVfoList) cached = false; // metadata, no CAT transaction
            if (cached) {
                std::lock_guard lock(s->mutex);
                if (request.op == Op::GetFrequency && request.target == "currVFO" && s->frequency) result.value = *s->frequency;
                else if (request.op == Op::GetMode && request.target == "currVFO" && s->mode) { result.name = s->mode->name; result.width = s->mode->width; }
                else if (request.op == Op::GetVfo && s->vfo) result.name = *s->vfo;
                else if (const auto i = s->reads.find(key); i != s->reads.end()) result = i->second;
                else throw rig::RigError("no safe cached value; radio busy", -9);
            } else {
                result = backend.control(request);
                std::lock_guard lock(s->mutex);
                if (s->reads.size() >= 128) s->reads.clear();
                s->reads.insert_or_assign(key, result);
                const bool current = request.target == "currVFO" || (s->vfo && request.target == *s->vfo);
                if (request.op == Op::GetFrequency && current) s->frequency = result.value;
                if (request.op == Op::GetMode && current) s->mode = rig::RadioMode{result.name, result.width};
                if (request.op == Op::GetVfo) {
                    if (s->vfo && *s->vfo != result.name) { s->frequency.reset(); s->mode.reset(); s->reads.clear(); }
                    s->vfo = result.name;
                }
            }
            const auto value = std::to_string(result.value);
            const auto width = std::to_string(result.width);
            switch (request.op) {
                case Op::GetFrequency: reply->fields = {{"Frequency", value}}; break;
                case Op::GetMode: reply->fields = {{"Mode", result.name}, {"Passband", width}}; break;
                case Op::GetVfo: reply->fields = {{"VFO", result.name}}; break;
                case Op::GetVfoList: reply->fields = {{"VFOs", result.name}}; break;
                case Op::GetSplitVfo: reply->fields = {{"Split", result.split ? "1" : "0"}, {"TX VFO", result.name}}; break;
                case Op::GetSplitFrequency: reply->fields = {{"TX Frequency", value}}; break;
                case Op::GetSplitMode: reply->fields = {{"TX Mode", result.name}, {"TX Passband", width}}; break;
                case Op::GetSplitFrequencyMode: reply->fields = {{"TX Frequency", value}, {"TX Mode", result.name}, {"TX Passband", width}}; break;
                case Op::GetLevel: reply->fields = {{"Level Value", result.floating_level ? value : std::to_string(static_cast<int>(result.value))}}; break;
                default: break;
            }

        }, c->command.name == "set_ptt");
    } catch (const rig::RigError& e) {
        c->reply->error = e.code;
        if (c->socket) c->socket->write(format(c->command, *c->reply));
    }
}
}  // namespace data2g::app
