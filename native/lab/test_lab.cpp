#include "runner.hpp"
#include "channel.hpp"
#include "campaign.hpp"
#include "goodput.hpp"

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

#include "util/pool.hpp"

namespace {
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
}
int main() {
    using namespace data2g::lab;
    try {
        data2g::pool::set_threads(1);
        Goodput meter;
        meter.add(10, {100, 50, 0, 0});
        require(std::abs(meter.bps()[0] - 80) < 1e-9 && meter.bps()[2] == 0, "goodput counts unique delivered bytes separately from ACKs");
        meter.add(20, {100, 50, 100, 50});
        require(std::abs(meter.bps()[0] - 40) < 1e-9, "unchanged bytes during retransmission do not add goodput");
        meter.add(41, {100, 50, 100, 50});
        require(meter.bps()[0] == 0 && meter.bps()[2] > 0, "30-second window expires delivery independently of later ACKs");
        require(campaign_size("cpm_floor", 100) == 55800, "full six-mode seven-channel floor grid and all seeds");
        require(campaign_size("hf_extreme", 32) == 7168, "all four severe ITU channels, adaptive and six fixed modes, eight SNRs");
        Options probe;
        probe.channel = "awgn"; probe.fixed_mode = "fsk8r50-r1/3"; probe.snr_db = 30;
        const std::atomic_bool probe_go{false};
        const auto burst = run_cpm_burst(probe, probe_go);
        require(burst.find("\"base_data_ok\":true") != std::string::npos && burst.find("\"supplied_data_ok\":true") != std::string::npos,
                "paired CPM baseline and supplied-information diagnostic recover a clean burst");
        Random rng(0);
        require(rng.next() == UINT64_C(0xe220a8397b1dcdaf), "specified PRNG vector");
        double sum = 0, squares = 0;
        for (int i = 0; i < 100000; ++i) { const double x = rng.normal(); sum += x; squares += x * x; }
        require(std::abs(sum / 100000) < .02 && std::abs(squares / 100000 - 1) < .03, "noise mean and variance");
        Channel clean(profile("clean"), 1, 1);
        std::vector<double> tone(8000);
        for (std::size_t i = 0; i < tone.size(); ++i) tone[i] = std::cos(2 * 3.141592653589793 * 1000 * i / 8000);
        const auto y = clean.render(tone, 0);
        for (std::size_t i = 0; i < y.size(); ++i)
            require(std::abs(y[i] - std::sqrt(2.) * tone[i]) < 1e-10, "clean channel, mean-power normalization");
        bool rejected = false;
        try { profile("unsupported"); } catch (const std::invalid_argument&) { rejected = true; }
        require(rejected, "unknown profiles rejected");
        Options o;
        std::atomic_bool cancelled{true};
        require(run(o, cancelled).find("\"outcome\":\"cancelled\"") != std::string::npos, "cancelled never reported complete");
        const std::atomic_bool go{false};
        std::string clean_result;
        for (const char* name : {"clean", "awgn"}) {
            o.channel = name;
            o.snr_db = 20;
            const auto result = run(o, go);
            std::puts(result.c_str());
            require(result.find("\"outcome\":\"complete\"") != std::string::npos, "connect, exact bidirectional bytes, final ACK, disconnect");
            if (o.channel == "clean") clean_result = result;
        }
        auto field = [&](const std::string& name) {
            const std::string label = "\"" + name + "\":";
            const auto pos = clean_result.find(label);
            require(pos != std::string::npos, "reference session records delivery and ACK times");
            return std::stod(clean_result.substr(pos + label.size()));
        };
        const double delivery = field("delivery_s"), ack = field("ack_s");
        require(delivery >= 0 && ack > delivery, "final ACK follows application delivery");
        o.channel = "clean";
        o.horizon_s = (delivery + ack) * .5;
        const auto late_ack = run(o, go);
        require(late_ack.find("\"delivered\":true") != std::string::npos
                && late_ack.find("\"acknowledged\":false") != std::string::npos,
                "delivered bytes without a final ACK are not acknowledged completion");
        o.horizon_s = 1;
        const auto timeout = run(o, go);
        require(timeout.find("\"outcome\":\"connect_timeout\"") != std::string::npos, "horizon excludes late completion");
        o.paced = true;
        const auto start = std::chrono::steady_clock::now();
        const auto paced = run(o, go);
        require(std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count() >= .99,
                "paced simulation cannot finish a second of audio faster than wall time");
        require(paced.find("\"clock_mode\":\"wall_clock_paced\"") != std::string::npos, "pacing recorded in result");
        std::atomic_bool stop{false};
        std::jthread stopper([&] { std::this_thread::sleep_for(std::chrono::milliseconds(150)); stop = true; });
        require(run(o, stop).find("\"outcome\":\"cancelled\"") != std::string::npos,
                "cancellation interrupts a paced quiet period");
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
}
