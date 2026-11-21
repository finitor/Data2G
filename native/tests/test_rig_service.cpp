// Protocol interoperability and ownership, using real Hamlib clients on macOS
// or any desktop with Qt Network. No audio devices or radio hardware.
#include <QCoreApplication>
#include <QElapsedTimer>
#include <QEventLoop>
#include <QHostAddress>
#include <QTcpSocket>
#include <QTcpServer>
#include <QTemporaryDir>

#include <chrono>
#include <cmath>
#include <future>
#include <fstream>
#include <vector>
#include <thread>
#include <memory>
#include <atomic>
#include <string>

#include "check.hpp"
#include "app/rig_service.hpp"
#include "app/station.hpp"
#include "rig/hamlib/hamlib.hpp"
#include "rig/controller.hpp"

using namespace data2g;
using namespace std::chrono_literals;
namespace {
template<class F> bool until(F predicate, int timeout = 6000) {
    QElapsedTimer time; time.start();
    while (!predicate() && time.elapsed() < timeout) {
        QCoreApplication::processEvents(QEventLoop::AllEvents, 10);
        std::this_thread::sleep_for(1ms);
    }
    return predicate();
}
void connect(QTcpSocket& socket, quint16 port) {
    socket.connectToHost(QHostAddress::LocalHost, port);
    check::is_true(until([&] { return socket.state() == QAbstractSocket::ConnectedState; }), "client connects");
}
QByteArray command(QTcpSocket& socket, const QByteArray& request, int lines = 1) {
    socket.write(request);
    QByteArray reply;
    check::is_true(until([&] { reply += socket.readAll(); return request.startsWith("|") ? reply.endsWith("|RPRT 0|") : reply.count('\n') >= lines; }), "reply to " + request.toStdString());
    return reply;
}
struct Counts { std::atomic<int> opened{0}, closed{0}, off{0}; std::atomic<bool> fail_key{false}, fail_off{false}; };
class CountingBackend : public rig::RigBackend {
public:
    CountingBackend(std::unique_ptr<rig::RigBackend> backend, std::shared_ptr<Counts> counts)
        : backend_(std::move(backend)), counts_(std::move(counts)) {}
    void open() override { backend_->open(); ++counts_->opened; }
    void close() noexcept override { backend_->close(); ++counts_->closed; }
    void set_ptt(bool on) override {
        backend_->set_ptt(on);
        if (!on) {
            ++counts_->off;
            if (counts_->fail_off.exchange(false)) throw rig::RigError("unkey timed out");
        }
        if (on && counts_->fail_key.exchange(false)) throw rig::RigError("key timed out after reaching hardware");
    }
    double frequency_hz() override { return backend_->frequency_hz(); }
    void set_frequency_hz(double hz) override { backend_->set_frequency_hz(hz); }
    rig::RadioMode mode() override { return backend_->mode(); }
    void set_mode(const rig::RadioMode& m) override { backend_->set_mode(m); }
    std::string rigctld_state() override { return backend_->rigctld_state(); }
    std::string description() const override { return backend_->description(); }
private:
    std::unique_ptr<rig::RigBackend> backend_;
    std::shared_ptr<Counts> counts_;
};
int ports() {
    for (int i = 0; i < 100; ++i) {
        QTcpServer a, b, c;
        if (!a.listen(QHostAddress::LocalHost, 0)) continue;
        const int port = a.serverPort();
        if (port < 65534 && b.listen(QHostAddress::LocalHost, port + 1) && c.listen(QHostAddress::LocalHost, port + 2)) return port;
    }
    throw std::runtime_error("no free port triple");
}
void station_cycles(app::RigService& service, const Counts& counts) {
    QTcpSocket client; connect(client, service.port());
    for (int cycle = 0; cycle < 2; ++cycle) {
        check::is_true(until([&] { try { service.reserve_modem(); return true; } catch (...) { return false; } }), "reserve for real Station");
        QTemporaryDir directory;
        const auto input = directory.filePath("in.f32").toStdString();
        const auto output = directory.filePath("out.f32").toStdString();
        std::ofstream(input, std::ios::binary).close();
        app::Args args;
        args.mycall = "N0TEST";
        args.audio_io = "pipe:" + input + "," + output;
        args.command_port = ports(); args.kiss_port = args.command_port + 2;
        args.rig = true; args.rig_model = rig::MODEL_DUMMY;
        args.realtime = false;
        app::Station station(args);
        station.set_rig_factory([&](const rig::HamlibConfig&) { return service.modem_backend(); });
        station.start();
        check::is_true(command(client, "F 14079000\n") == "RPRT -9\n", "real Station reserves external tuning");
        station.stop(); service.release_modem();
        check::is_true(command(client, "F 14079000\n") == "RPRT 0\n", "same connection works after real Station stop");
        check::is_true(counts.opened == 1 && counts.closed == 0, "one physical handle across Station cycles");
    }
    client.abort();
}
void failed_disconnect_cleanup() {
    rig::HamlibConfig config; config.model = rig::MODEL_DUMMY; config.device = "";
    auto counts = std::make_shared<Counts>();
    app::RigService service(std::make_unique<CountingBackend>(rig::make_hamlib_backend(config), counts), 0);
    check::is_true(until([&] { return service.frequency().has_value(); }), "cleanup fixture opens");
    QTcpSocket client; connect(client, service.port());
    check::is_true(command(client, "T 1\n") == "RPRT 0\n", "cleanup fixture keys");
    counts->fail_off = true; client.abort();
    check::is_true(until([&] { return service.status().contains("PTT release failed"); }), "failed disconnect unkey is visible to operator");
    bool busy = false;
    try { service.reserve_modem(); } catch (const rig::RigError&) { busy = true; }
    check::is_true(busy, "uncertain release keeps ownership conservative");
    service.stop();
    check::is_true(service.wait_for_shutdown(3), "shutdown retries uncertain release");
    check::is_true(counts->off >= 2 && counts->closed == 1, "final worker close retries unkey once");
}

void queue_cancellation() {
    rig::HamlibConfig config; config.model = rig::MODEL_DUMMY; config.device = "";
    rig::RigController controller;
    rig::RigConfig timing; timing.poll_interval_s = 0;
    controller.start(rig::make_hamlib_backend(config), timing);
    std::promise<void> entered, release;
    auto blocked = release.get_future().share();
    auto active = controller.request([&](rig::RigBackend&) { entered.set_value(); blocked.wait(); });
    check::is_true(entered.get_future().wait_for(3s) == std::future_status::ready, "request runs on hardware worker");
    std::atomic<int> ran{0};
    std::vector<std::future<void>> pending;
    for (int i = 0; i < 16; ++i) pending.push_back(controller.request([&](rig::RigBackend&) { ++ran; }));
    bool full = false;
    try { controller.request([](rig::RigBackend&) {}); } catch (const rig::RigError& e) { full = e.code == -9; }
    check::is_true(full, "hardware queue is bounded");
    controller.stop();
    for (auto& task : pending) check::is_true(task.wait_for(0ms) == std::future_status::ready, "stop cancels pending work");
    release.set_value(); active.get();
    check::is_true(controller.wait_for_shutdown(3), "blocked request releases its worker");
    check::is_true(ran == 0, "cancelled writes never execute");
}

void net_client(app::RigService& service) {
    auto future = std::async(std::launch::async, [&] {
        rig::HamlibConfig config;
        config.device = "127.0.0.1:" + std::to_string(service.port());
        config.timeout_ms = 3000;
        auto client = rig::make_hamlib_backend(config);
        client->open(); // exercises chk_vfo and dump_state, not just raw commands
        client->set_frequency_hz(14075000);
        check::is_true(std::abs(client->frequency_hz() - 14075000) < 1, "NET client frequency round trip");
        client->set_mode({"USB", 2400});
        const auto returned_mode = client->mode();
        check::is_true(returned_mode.name == "USB", "NET client mode round trip: " + returned_mode.name);
        client->set_ptt(true);
        client->set_ptt(false);
        client->close();
    });
    check::is_true(until([&] { return future.wait_for(0ms) == std::future_status::ready; }, 15000), "Hamlib NET client completes");
    future.get();
    check::is_true(until([&] { try { service.reserve_modem(); return true; } catch (...) { return false; } }), "disconnect cleanup completes");
    service.release_modem();
}
void ownership(app::RigService& service) {
    QTcpSocket first, second;
    connect(first, service.port()); connect(second, service.port());
    check::is_true(command(first, "F 14076000\n") == "RPRT 0\n", "set frequency");
    check::is_true(command(first, "+f\n", 3).startsWith("get_freq:\nFrequency: 14076000"), "extended response");
    const auto mode_response = command(second, "|m\n");
    check::is_true(mode_response.contains("get_mode:|Mode: USB|Passband: 2400|RPRT 0|"), "separator response: " + mode_response.toStdString());
    check::is_true(command(first, "F nan\n") == "RPRT -1\n", "reject non-finite frequency");
    check::is_true(command(first, "F garbage\n") == "RPRT -1\n", "reject malformed number");
    check::is_true(command(first, "\\set_split_vfo 1 VFOB\n") == "RPRT -11\n", "unsupported command");
    check::is_true(command(first, "T 1\n") == "RPRT 0\n", "external PTT on");
    check::is_true(command(second, "T 0\n") == "RPRT -9\n", "other client cannot unkey owner");
    bool busy = false;
    try { service.reserve_modem(); } catch (const rig::RigError&) { busy = true; }
    check::is_true(busy, "modem cannot start during external TX");
    first.abort();
    check::is_true(until([&] { try { service.reserve_modem(); return true; } catch (...) { return false; } }), "disconnect releases external PTT");
    auto borrowed = service.modem_backend(); borrowed->open();
    check::is_true(command(second, "F 14077000\n") == "RPRT -9\n", "modem reservation protects tuning");
    auto ptt = std::async(std::launch::async, [&] { borrowed->set_ptt(true); });
    check::is_true(until([&] { return ptt.wait_for(0ms) == std::future_status::ready; }), "modem keys"); ptt.get();
    check::is_true(command(second, "T 0\n") == "RPRT -9\n", "external off cannot interrupt modem");
    check::is_true(command(second, "t\n") == "1\n", "external client reads modem PTT");
    ptt = std::async(std::launch::async, [&] { borrowed->set_ptt(false); });
    check::is_true(until([&] { return ptt.wait_for(0ms) == std::future_status::ready; }), "modem unkeys"); ptt.get();
    borrowed->close(); borrowed.reset(); service.release_modem();
    check::is_true(command(second, "F 14077000\n") == "RPRT 0\n", "same client survives modem stop");
    check::is_true(command(second, "f\n").startsWith("14077000"), "radio still open after modem stop");
    // Partial frames and pipelined input must stay ordered per connection.
    second.write("F 140");
    QCoreApplication::processEvents();
    check::is_true(command(second, "78000\nf\n", 2).startsWith("RPRT 0\n14078000"), "partial/pipelined commands");
    second.abort();
}
}  // namespace
int main(int argc, char** argv) {
    QCoreApplication application(argc, argv);
    try {
        rig::HamlibConfig config; config.model = rig::MODEL_DUMMY; config.device = "";
        auto counts = std::make_shared<Counts>();
        app::RigService service(std::make_unique<CountingBackend>(rig::make_hamlib_backend(config), counts), 0);
        check::is_true(until([&] { return service.frequency().has_value(); }), "radio opens without modem");
        net_client(service);
        ownership(service);
        station_cycles(service, *counts);
        QTcpSocket uncertain; connect(uncertain, service.port());
        counts->fail_key = true;
        check::is_true(command(uncertain, "T 1\n") == "RPRT -6\n", "failed key is reported");
        check::is_true(command(uncertain, "F 14080000\n") == "RPRT -9\n", "uncertain PTT blocks tuning");
        uncertain.abort();
        check::is_true(until([&] { try { service.reserve_modem(); return true; } catch (...) { return false; } }), "disconnect unkeys after uncertain key");
        service.release_modem();
        QTcpSocket keyed; connect(keyed, service.port());
        check::is_true(command(keyed, "T 1\n") == "RPRT 0\n", "key before service shutdown");
        const auto off_before = counts->off.load();
        service.stop();
        check::is_true(service.wait_for_shutdown(3), "physical radio shuts down");
        check::is_true(counts->closed == 1 && counts->off > off_before, "shutdown unkeys and closes once");
        queue_cancellation();
        failed_disconnect_cleanup();
    } catch (const std::exception& e) { check::fail("rig service", e.what()); }
    return check::report("rig service");
}
