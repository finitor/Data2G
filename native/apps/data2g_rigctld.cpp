// Portable standalone entry point for the same radio service used by Android.
// No audio devices, callsign, modem or Android lifecycle are required.
#include <QCoreApplication>
#include <QTimer>

#include <charconv>
#include <clocale>
#include <cstdio>
#include <string>
#include <system_error>
#include <vector>

#include "app/options.hpp"
#include "app/log.hpp"
#include "app/rig_service.hpp"
#include "rig/hamlib/hamlib.hpp"

using namespace data2g;
int main(int argc, char** argv) {
    int port = 4532;
    std::vector<char*> options{argv[0]};
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]) != "--port") { options.push_back(argv[i]); continue; }
        if (++i >= argc) app::usage_error("--port requires a value", "data2g-rigctld");
        const std::string value = argv[i];
        const auto result = std::from_chars(value.data(), value.data() + value.size(), port);
        if (result.ec != std::errc{} || result.ptr != value.data() + value.size() || port < 1 || port > 65535)
            app::usage_error("--port must be 1..65535", "data2g-rigctld");
    }
    options.push_back(nullptr);
    const auto args = app::parse(static_cast<int>(options.size()) - 1, options.data(), {}, "data2g-rigctld",
                                "Radio facade: --port N (default 4532), --listen ADDRESS (default 127.0.0.1; use 0.0.0.0 for LAN). Opens no modem or audio.\n");
    if (args.list_rigs) return app::list_rigs() ? 0 : 1;
    if (const auto bad = app::check(args)) app::usage_error(*bad, "data2g-rigctld");
    if (!args.rig || args.ptt_method == "vox" || args.tci)
        app::usage_error("choose a Hamlib rig with CAT or hardware PTT", "data2g-rigctld");
    QHostAddress address;
    if (!address.setAddress(QString::fromStdString(args.listen)))
        app::usage_error("--listen requires an IPv4 or IPv6 address", "data2g-rigctld");
    const auto level = app::parse_level(args.log_level);
    if (!level) app::usage_error("invalid log level", "data2g-rigctld");
    app::g_level = *level;
    if (args.rig_debug) rig::set_debug_sink([](const std::string& line) { app::log_line(app::INFO, "hamlib: " + line); });
    auto config = app::hamlib_config(args);
    if (config.model == rig::MODEL_NET_RIGCTL &&
        (config.device.empty() || config.device == "127.0.0.1:" + std::to_string(port) ||
         config.device == "localhost:" + std::to_string(port)))
        app::usage_error("upstream rigctld must use a different endpoint", "data2g-rigctld");
    QCoreApplication application(argc, argv);
    std::setlocale(LC_NUMERIC, "C");
    app::quit_on_signals();
    try {
        app::RigService radio(rig::make_hamlib_backend(config), static_cast<quint16>(port), address);
        std::printf("rigctld facade on %s:%u\n", args.listen.c_str(), radio.port());
        std::fflush(stdout);
        QTimer quit;
        QObject::connect(&quit, &QTimer::timeout, [] { if (app::quit_requested()) QCoreApplication::quit(); });
        quit.start(100);
        const int result = QCoreApplication::exec();
        radio.stop();
        radio.wait_for_shutdown(3.0);
        return result;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "data2g-rigctld: %s\n", e.what());
        return 1;
    }
}
