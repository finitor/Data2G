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
    rig::RadioControl control(const rig::RadioControl& command) override { return backend_->control(command); }
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
    for (int i = 0; i < 16; ++i) pending.push_back(controller.request([&](rig::RigBackend&) { ++ran; }, true));
    full = false;
    try { controller.request([](rig::RigBackend&) {}, true); } catch (const rig::RigError& e) { full = e.code == -9; }
    check::is_true(full, "priority queue is separately bounded");
    controller.stop();
    for (auto& task : pending) check::is_true(task.wait_for(0ms) == std::future_status::ready, "stop cancels pending work");
    release.set_value(); active.get();
    check::is_true(controller.wait_for_shutdown(3), "blocked request releases its worker");
    check::is_true(ran == 0, "cancelled writes never execute");
}

void queue_priority() {
    rig::HamlibConfig config; config.model = rig::MODEL_DUMMY; config.device = "";
    rig::RigController controller;
    rig::RigConfig timing; timing.poll_interval_s = 0;
    controller.start(rig::make_hamlib_backend(config), timing);
    std::promise<void> entered, release;
    auto blocked = release.get_future().share();
    auto active = controller.request([&](rig::RigBackend&) { entered.set_value(); blocked.wait(); });
    check::is_true(entered.get_future().wait_for(3s) == std::future_status::ready, "priority fixture blocks one in-flight operation");
    std::vector<int> order;
    auto read = controller.request([&](rig::RigBackend&) { order.push_back(3); });
    auto key = controller.request([&](rig::RigBackend&) { order.push_back(1); }, true);
    auto unkey = controller.request([&](rig::RigBackend&) { order.push_back(2); }, true);
    release.set_value(); active.get(); key.get(); unkey.get(); read.get();
    check::is_true(order == std::vector<int>{1, 2, 3}, "external PTT bypasses reads and keeps FIFO order");
    controller.stop(); check::is_true(controller.wait_for_shutdown(3), "priority worker stops");
}

void extended_controls(app::RigService& service) {
    QTcpSocket first, second; connect(first, service.port()); connect(second, service.port());
    check::is_true(command(first, "V VFOB\n") == "RPRT 0\n", "switch physical VFO B");
    check::is_true(command(first, "v\n") == "VFOB\n", "read actual VFO B");
    check::is_true(command(first, "F 14100000\n") == "RPRT 0\n", "tune B");
    check::is_true(command(first, "M CW 500\n") == "RPRT 0\n", "modes outside original digital subset");
    check::is_true(command(first, "V VFOA\n") == "RPRT 0\n", "switch back to A");
    check::is_true(command(first, "F 14075000\n") == "RPRT 0\n", "tune A independently");
    check::is_true(command(first, "M USB 2400\n") == "RPRT 0\n", "restore current mode");
    check::is_true(command(first, "\\set_vfo_opt 1\n") == "RPRT 0\n", "enable per-client VFO syntax");
    check::is_true(command(first, "\\chk_vfo\n") == "1\n", "first client VFO option on");
    check::is_true(command(second, "\\chk_vfo\n") == "0\n", "second client VFO option stays off");
    check::is_true(command(first, "f VFOB\n").startsWith("14100000"), "explicit B frequency");
    check::is_true(command(first, "m VFOB\n", 2) == "CW\n500\n", "explicit B mode");
    check::is_true(command(second, "v\n") == "VFOA\n", "targeted reads preserve selected VFO");
    check::is_true(command(second, "f\n").startsWith("14075000"), "default client still reads A");
    check::is_true(command(first, "F VFOB 14101000\n") == "RPRT 0\n", "explicit B write");
    check::is_true(command(first, "f VFOB\n").startsWith("14101000"), "explicit B write readback");
    check::is_true(command(first, "f INVALID\n") == "RPRT -1\n", "invalid target rejected");
    check::is_true(command(first, "f\n") == "RPRT -1\n", "VFO mode requires target");
    check::is_true(command(first, "\\get_vfo_list\n").contains("VFOB"), "discover VFO list");
    check::is_true(command(first, "S VFOA 1 VFOB\n") == "RPRT 0\n", "enable split A/B");
    check::is_true(command(first, "s VFOA\n", 2) == "1\nVFOB\n", "read split routing");
    check::is_true(command(first, "I VFOA 14076000\n") == "RPRT 0\n", "set TX frequency");
    check::is_true(command(first, "i VFOA\n").startsWith("14076000"), "read TX frequency");
    check::is_true(command(first, "X VFOA CW 500\n") == "RPRT 0\n", "set TX mode");
    check::is_true(command(first, "x VFOA\n", 2) == "CW\n500\n", "read TX mode");
    check::is_true(command(first, "K VFOA 14077000 USB 2400\n") == "RPRT 0\n", "set combined TX frequency/mode");
    check::is_true(command(first, "k VFOA\n", 3).startsWith("14077000"), "read combined TX settings");
    check::is_true(command(second, "L AF 0.42\n") == "RPRT 0\n", "float level write");
    check::is_true(std::abs(command(second, "l AF\n").toDouble() - 0.42) < 0.001, "float level readback");
    check::is_true(command(second, "L CWPITCH 700\n") == "RPRT 0\n", "integer level write");
    check::is_true(command(second, "l CWPITCH\n") == "700\n", "integer level readback");
    check::is_true(command(second, "L AF 1.1\n") == "RPRT -1\n", "normalized level bounds");
    check::is_true(command(second, "L CWPITCH 700.5\n") == "RPRT -1\n", "reject fractional integer level");
    check::is_true(command(second, "L CWPITCH 999999999999\n") == "RPRT -1\n", "integer overflow rejected");
    check::is_true(command(second, "L STRENGTH 1\n") == "RPRT -11\n", "read-only level rejected");
    check::is_true(command(second, "l UNKNOWN\n") == "RPRT -11\n", "unknown level rejected");
    check::is_true(command(second, "L AF nan\n") == "RPRT -1\n", "non-finite level rejected");
    check::is_true(command(second, "M UNKNOWN 2400\n") == "RPRT -1\n", "unknown mode rejected");
    check::is_true(command(second, "S 2 VFOB\n") == "RPRT -1\n", "invalid split state rejected");
    // Prime a different-VFO cache, then mutate routing: it must not be reused.
    command(first, "f VFOB\n");
    check::is_true(command(second, "V VFOA\n") == "RPRT 0\n", "routing mutation invalidates caches");
    command(second, "f\n"); command(second, "m\n", 2);
    check::is_true(command(second, "T 1\n") == "RPRT 0\n", "key for control interlocks");
    check::is_true(command(second, "V VFOB\n") == "RPRT -9\n", "PTT owner cannot change VFO during TX");
    check::is_true(command(first, "S VFOA 0 VFOB\n") == "RPRT -9\n", "other client cannot change split during TX");
    check::is_true(command(second, "L RFPOWER 0.5\n") == "RPRT -9\n", "level writes blocked during TX");
    check::is_true(!command(second, "l SWR\n").startsWith("RPRT"), "live current-VFO meter during external TX");
    check::is_true(command(first, "f VFOB\n") == "RPRT -9\n", "no stale other-VFO cache after routing change");
    check::is_true(command(first, "T VFOB 0\n") == "RPRT -9\n", "other owner cannot target an unkey");
    check::is_true(command(second, "f\n").toDouble() > 0, "current frequency cached during TX");
    check::is_true(command(second, "T 0\n") == "RPRT 0\n", "unkey after reads");
    check::is_true(until([&] { try { service.reserve_modem(); return true; } catch (...) { return false; } }), "reserve expanded controls for modem");
    for (const auto& request : {"V VFOB\n", "S 1 VFOB\n", "I 14100000\n", "X USB 2400\n", "L AF 0.5\n"})
        check::is_true(command(second, request) == "RPRT -9\n", "modem blocks " + std::string(request));
    check::is_true(command(second, "l AF\n") == "RPRT -9\n", "uncached level read does not issue CAT during modem use");
    service.release_modem();
    check::is_true(command(second, "S 0 VFOB\n") == "RPRT 0\n", "disable split after reservation");
    command(second, "F 14075000\n"); command(second, "M USB 2400\n");
    first.abort(); second.abort();
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
        using Op = rig::RadioOp;
        rig::RadioControl control{Op::SetVfo}; control.name = "VFOB"; client->control(control);
        client->set_frequency_hz(14102000);
        control.name = "VFOA"; client->control(control);
        control = rig::RadioControl{Op::GetFrequency}; control.target = "VFOB";
        check::is_true(std::abs(client->control(control).value - 14102000) < 1, "NET client explicitly targets B");
        check::is_true(client->control({Op::GetVfo}).name == "VFOA", "NET target preserves current VFO");
        control = rig::RadioControl{Op::SetSplitVfo}; control.split = true; control.name = "VFOB";
        client->control(control);
        const auto split = client->control({Op::GetSplitVfo});
        check::is_true(split.split && split.name == "VFOB", "NET client split routing");
        control = rig::RadioControl{Op::SetSplitFrequency}; control.value = 14078000; client->control(control);
        check::is_true(std::abs(client->control({Op::GetSplitFrequency}).value - 14078000) < 1, "NET client split frequency");
        control = rig::RadioControl{Op::SetSplitMode}; control.name = "CW"; control.width = 500; client->control(control);
        const auto tx_mode = client->control({Op::GetSplitMode});
        check::is_true(tx_mode.name == "CW" && tx_mode.width == 500, "NET client split mode");
        control = rig::RadioControl{Op::SetLevel}; control.name = "AF"; control.value = 0.35; client->control(control);
        control.op = Op::GetLevel;
        check::is_true(std::abs(client->control(control).value - 0.35) < 0.001, "NET float level round trip");
        control = rig::RadioControl{Op::SetLevel}; control.name = "CWPITCH"; control.value = 650; client->control(control);
        control.op = Op::GetLevel;
        check::is_true(client->control(control).value == 650, "NET integer level round trip");
        const auto caps = client->rigctld_state();
        check::is_true(caps.find("has_set_vfo=1") != std::string::npos, "NET capability discovery includes VFO control");
        control = rig::RadioControl{Op::SetSplitVfo}; control.name = "VFOB"; control.split = false; client->control(control);
        client->control({Op::GetVfo}); client->control({Op::GetFrequency});
        client->set_ptt(true);
        check::is_true(client->frequency_hz() > 0, "NET client cached frequency while keyed");
        control = rig::RadioControl{Op::GetLevel}; control.name = "SWR";
        check::is_true(std::isfinite(client->control(control).value), "NET client live meter while keyed with VFO syntax");
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
    check::is_true(command(first, "\\set_mem 1\n") == "RPRT -11\n", "unsupported command");
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
        extended_controls(service);
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
        queue_priority();
        failed_disconnect_cleanup();
    } catch (const std::exception& e) { check::fail("rig service", e.what()); }
    return check::report("rig service");
}
