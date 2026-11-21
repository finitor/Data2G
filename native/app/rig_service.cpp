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
        try { frequency = backend_->frequency_hz(); } catch (...) {}
        try { mode = backend_->mode(); } catch (...) {}
        try { caps = backend_->rigctld_state(); } catch (...) {}
        std::lock_guard lock(state_->mutex);
        state_->description = backend_->description();
        state_->frequency = frequency;
        state_->mode = mode;
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
        {"t", "get_ptt"}, {"T", "set_ptt"}, {"v", "get_vfo"}, {"_", "get_info"}, {"q", "quit"}
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
        }));
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
            const auto& args = cmd.args;
            const auto need = [&](std::size_t n) { if (args.size() != n) throw rig::RigError("wrong argument count", -1); };
            if (name == "chk_vfo") { need(0); reply->fields = {{"VFO", "0"}}; return; }
            if (name == "get_vfo") { need(0); reply->fields = {{"VFO", "VFOA"}}; return; }
            // Hamlib 4.7.2 consults this before set_mode and expects BOTH the
            // value and a status line (its NET backend consumes two records).
            if (name == "get_lock_mode") { need(0); reply->fields = {{"Locked", "0"}}; reply->report = true; return; }
            if (name == "dump_state") {
                need(0); std::lock_guard lock(s->mutex);
                if (s->caps.empty()) throw rig::RigError("capabilities unavailable", -11);
                reply->raw = s->caps; return;
            }
            if (name == "get_info") { need(0); reply->fields = {{"Info", "Data2G current-VFO rig proxy"}}; return; }
            const bool write = name == "set_freq" || name == "set_mode" || name == "set_ptt";
            bool cached;
            {
                std::lock_guard lock(s->mutex);
                if (!s->ready || s->stopping) throw rig::RigError("radio unavailable");
                if (write && (s->modem || (s->owner && s->owner != c->id))) throw rig::RigError("radio busy", -9);
                cached = s->modem || s->ptt;
            }
            if (name == "get_ptt") {
                need(0); std::lock_guard lock(s->mutex);
                reply->fields = {{"PTT", s->ptt ? "1" : "0"}};
            } else if (name == "set_ptt") {
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
            } else if (name == "get_freq") {
                need(0);
                if (!cached) { const auto hz = backend.frequency_hz(); std::lock_guard lock(s->mutex); s->frequency = hz; }
                std::lock_guard lock(s->mutex);
                if (!s->frequency) throw rig::RigError("frequency unavailable");
                reply->fields = {{"Frequency", std::to_string(*s->frequency)}};
            } else if (name == "set_freq") {
                need(1);
                if (cached) throw rig::RigError("radio transmitting", -9);
                const auto hz = number(args[0]);
                if (hz <= 0) throw rig::RigError("invalid frequency", -1);
                backend.set_frequency_hz(hz);
                const auto actual = backend.frequency_hz();
                std::lock_guard lock(s->mutex); s->frequency = actual;
            } else if (name == "get_mode") {
                need(0);
                if (!cached) { const auto mode = backend.mode(); std::lock_guard lock(s->mutex); s->mode = mode; }
                std::lock_guard lock(s->mutex);
                if (!s->mode) throw rig::RigError("mode unavailable", -11);
                reply->fields = {{"Mode", s->mode->name}, {"Passband", std::to_string(s->mode->width)}};
            } else if (name == "set_mode") {
                need(2);
                if (cached) throw rig::RigError("radio transmitting", -9);
                const double width = number(args[1]);
                if (width < -1 || width > 100000 || std::floor(width) != width) throw rig::RigError("invalid passband", -1);
                backend.set_mode({args[0], static_cast<long>(width)});
                const auto mode = backend.mode();
                std::lock_guard lock(s->mutex); s->mode = mode;
            } else throw rig::RigError("command unsupported", -11);
        });
    } catch (const rig::RigError& e) {
        c->reply->error = e.code;
        if (c->socket) c->socket->write(format(c->command, *c->reply));
    }
}
}  // namespace data2g::app
