#include "runner.hpp"
#include "channel.hpp"

#include <atomic>
#include <cmath>
#include <cstdio>
#include <exception>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "util/pool.hpp"

int main(int argc, char** argv) {
    try {
        data2g::lab::Options o;
        int threads = 1;
        bool probe = false;
        std::string output;
        for (int i = 1; i < argc; ++i) {
            const std::string flag = argv[i];
            auto value = [&]() -> std::string {
                if (i + 1 == argc) throw std::invalid_argument("missing value for " + flag);
                return argv[++i];
            };
            if (flag == "--channel") o.channel = value();
            else if (flag == "--snr") o.snr_db = std::stod(value());
            else if (flag == "--horizon") o.horizon_s = std::stod(value());
            else if (flag == "--cfo") o.cfo_hz = std::stod(value());
            else if (flag == "--seed") o.seed = std::stoull(value());
            else if (flag == "--bytes") o.bytes_each_way = std::stoull(value());
            else if (flag == "--cap") o.bandwidth_cap = std::stoi(value());
            else if (flag == "--threads") threads = std::stoi(value());
            else if (flag == "--record-dir") o.record_dir = value();
            else if (flag == "--paced") o.paced = true;
            else if (flag == "--output") output = value();
            else if (flag == "--channel-probe") probe = true;
            else if (flag == "--help") {
                std::puts("data2g-loopback [--channel clean|awgn|mpg|mpp|mpd|nvis|hilat] [--snr DB]\n"
                          "  [--seed N] [--bytes N] [--horizon SECONDS] [--cfo HZ] [--cap 0|1|2]\n"
                          "  [--threads N] [--paced] [--record-dir NEW_DIR] [--output FILE]\n"
                          "Synchronous simulation, optionally paced to wall time. JSON to stdout; progress to stderr.\n"
                          "Exit 0=complete, 1=trial incomplete, 2=configuration/runtime error.");
                return 0;
            } else throw std::invalid_argument("unknown option: " + flag);
        }
        if (threads < 1 || threads > 32) throw std::invalid_argument("threads must be 1..32");
        data2g::pool::set_threads(threads);
        if (probe) {
            data2g::lab::Channel ch(data2g::lab::profile(o.channel), o.seed, o.horizon_s, o.cfo_hz);
            std::cout << std::setprecision(17) << "{\"rate\":" << ch.tap_rate() << ",\"taps\":[";
            for (int p = 0; p < 2; ++p) {
                if (p) std::cout << ',';
                std::cout << '[';
                const auto& tap = ch.tap(p);
                for (std::size_t i = 0; i < tap.size(); ++i) {
                    if (i) std::cout << ',';
                    std::cout << '[' << tap[i].real() << ',' << tap[i].imag() << ']';
                }
                std::cout << ']';
            }
            std::vector<double> audio(8000, 0);
            for (std::size_t i = 100; i < audio.size() - 100; ++i)
                audio[i] = std::cos(2 * 3.141592653589793 * 1000 * i / 8000)
                         + .3 * std::sin(2 * 3.141592653589793 * 1555 * i / 8000);
            const auto rendered = ch.render(audio, 24017);
            std::cout << "],\"rendered\":[";
            for (std::size_t i = 0; i < rendered.size(); ++i) {
                if (i) std::cout << ',';
                std::cout << rendered[i];
            }
            std::cout << "]}\n";
            return 0;
        }
        const std::atomic_bool cancel{false};
        const auto result = data2g::lab::run(o, cancel, [](const std::string& s) { std::fprintf(stderr, "%s\n", s.c_str()); });
        if (!output.empty()) {
            std::ofstream file(output);
            if (!(file << result << '\n')) throw std::runtime_error("cannot write output file");
        }
        std::cout << result << '\n';
        return result.find("\"outcome\":\"complete\"") != std::string::npos ? 0 : 1;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "data2g-loopback: %s\n", e.what());
        return 2;
    }
}
