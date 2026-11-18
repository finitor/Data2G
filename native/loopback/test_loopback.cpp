#include "runner.hpp"
#include "channel.hpp"

#include <atomic>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <string>
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
        for (const char* name : {"clean", "awgn"}) {
            o.channel = name;
            o.snr_db = 20;
            const auto result = run(o, go);
            std::puts(result.c_str());
            require(result.find("\"outcome\":\"complete\"") != std::string::npos, "connect, exact bidirectional bytes, final ACK, disconnect");
        }
        o.horizon_s = 8;
        const auto late_ack = run(o, go);
        require(late_ack.find("\"delivered\":true") != std::string::npos
                && late_ack.find("\"acknowledged\":false") != std::string::npos,
                "delivered bytes without a final ACK are not acknowledged completion");
        o.horizon_s = 1;
        const auto timeout = run(o, go);
        require(timeout.find("\"outcome\":\"connect_timeout\"") != std::string::npos, "horizon excludes late completion");
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
}
