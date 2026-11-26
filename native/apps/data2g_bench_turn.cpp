// data2g-bench-turn: two engines in one process, real time, as data2g-host runs them (session stage on a
// worker thread), joined by an AWGN channel whose SNR alternates high and low. A (a node) sends data to B
// (the station under test: the one whose decode speed matters). Per A burst: how long until B's reply starts
// on the air, and whether A spoke again first (a poll or timeout). For turnaround timing on a slow machine.
//
//   data2g-bench-turn [--seconds S] [--hi DB] [--lo DB] [--hi-s S] [--lo-s S] [--threads N] [--seed N]
//                     [--b-tturn S]

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <random>
#include <string>
#include <thread>
#include <vector>

#include "arq/engine.hpp"
#include "util/pool.hpp"

using namespace data2g;
using namespace data2g::arq;

namespace {

constexpr int BLOCK = config::FS / 10;

double pct(std::vector<double> v, double p) {
    if (v.empty()) return NAN;
    std::sort(v.begin(), v.end());
    return v[static_cast<std::size_t>(p * static_cast<double>(v.size() - 1))];
}

}  // namespace

int main(int argc, char** argv) {
    double seconds = 300, hi = 18, lo = 6, hi_s = 40, lo_s = 20, b_tturn = 1.0;
    int threads = 4;
    unsigned seed = 1;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        const auto val = [&] {
            if (i + 1 >= argc) {
                std::fprintf(stderr, "%s: value missing\n", a.c_str());
                std::exit(2);
            }
            return std::atof(argv[++i]);
        };
        if (a == "--seconds") seconds = val();
        else if (a == "--hi") hi = val();
        else if (a == "--lo") lo = val();
        else if (a == "--hi-s") hi_s = val();
        else if (a == "--lo-s") lo_s = val();
        else if (a == "--threads") threads = static_cast<int>(val());
        else if (a == "--seed") seed = static_cast<unsigned>(val());
        else if (a == "--b-tturn") b_tturn = val();
        else {
            std::fprintf(stderr,
                         "usage: data2g-bench-turn [--seconds S] [--hi DB] [--lo DB] [--hi-s S] [--lo-s S] [--threads N]"
                         " [--seed N] [--b-tturn S]\n");
            return 2;
        }
    }
    pool::set_threads(threads);
    EngineConfig ca, cb;
    ca.seed = seed;
    cb.seed = seed + 1;
    ca.worker = cb.worker = true;
    Engine a("W1AW", ca), b("K2XYZ", cb);
    // the sessions are the workers': driven by post(), watched from after_block (engine.hpp)
    std::atomic<int> decoded{0}, failed{0};
    std::atomic<std::size_t> got{0};
    b.set_on_decoded([&](int d, int f) { decoded += d, failed += f; });
    b.set_after_block([&](bool) { got += b.session().read().size(); });
    bool wrote = false;  // a's worker only
    a.set_after_block([&](bool) {
        if (!wrote && a.session().state == SessionState::CONNECTED) {
            Bytes data(1 << 20);  // more than the run can send; random, as compression would shrink a pattern
            std::mt19937 dr(seed);
            for (auto& v : data) v = static_cast<std::uint8_t>(dr() & 255);
            a.session().write(data);
            wrote = true;
        }
    });
    b.post([&] {
        b.listen();
        b.session().t_turn = b_tturn;  // (after listen: a new session)
    });
    a.post([&] { a.connect("K2XYZ", 2); });

    std::mt19937 rng(seed);
    std::normal_distribution<double> unit(0.0, 1.0);
    const auto sigma = [](double snr_db) {
        return std::sqrt((config::FS / 2.0) / config::SNR_REF_BW_HZ / std::pow(10.0, snr_db / 10));
    };
    std::vector<double> ao(BLOCK, 0.0), bo(BLOCK, 0.0), x(BLOCK);
    std::int64_t n = 0;                      // samples so far
    std::int64_t a_end = -1, a_last = -1;    // A's latest burst's last sample; A's last audible sample
    std::int64_t b_last = -1;                // B's last audible sample
    bool a_on = false, b_on = false, waiting = false;
    std::vector<double> turn;                // A burst end -> B reply start, s
    int a_bursts = 0, a_again = 0, b_bursts = 0;
    const auto t0 = std::chrono::steady_clock::now();
    const int blocks = static_cast<int>(seconds * 10);
    for (int i = 0; i < blocks; ++i) {
        const double t = static_cast<double>(i) / 10;
        const double s = sigma(std::fmod(t, hi_s + lo_s) < hi_s ? hi : lo);
        for (int j = 0; j < BLOCK; ++j) x[j] = 2.2 * bo[j] + s * unit(rng);
        ao = a.step(x).audio;
        for (int j = 0; j < BLOCK; ++j) x[j] = 2.2 * ao[j] + s * unit(rng);
        bo = b.step(x).audio;
        for (int j = 0; j < BLOCK; ++j, ++n) {
            const bool ax = ao[j] != 0.0, bx = bo[j] != 0.0;
            // a burst: audio with gaps under 0.2 s (PTT lead-in silence and the like)
            if (ax) {
                if (!a_on && (a_last < 0 || n - a_last > config::FS / 5)) {
                    ++a_bursts;
                    if (waiting) ++a_again;  // A spoke again before B answered its last burst
                }
                a_on = true;
                a_last = n;
            } else if (a_on && n - a_last > config::FS / 5) {
                a_on = false;
                a_end = a_last;
                waiting = true;
            }
            if (bx) {
                if (!b_on && (b_last < 0 || n - b_last > config::FS / 5)) {
                    ++b_bursts;
                    if (waiting && a_end >= 0) turn.push_back(static_cast<double>(n - a_end) / config::FS);
                    waiting = false;
                }
                b_on = true;
                b_last = n;
            } else if (b_on && n - b_last > config::FS / 5) {
                b_on = false;
            }
        }
        std::this_thread::sleep_until(t0 + std::chrono::milliseconds(100 * (i + 1)));
    }
    a.stop();
    b.stop();
    // direct replies (under 3 s: A's reply timer is t_turn + 2.5 s from its burst's end) apart from B's wakes
    // after a burst it missed
    std::vector<double> direct;
    for (double v : turn)
        if (v < 3.0) direct.push_back(v);
    std::printf("turn: %.0f s, SNR %g/%g dB (%g s/%g s), B t_turn %.1f s, pool %d: %zu bytes to B (%.0f bps); "
                "A bursts %d, A again before B's reply %d, B bursts %d; B codewords decoded %d failed %d; "
                "B direct replies %zu: p50 %.2f p90 %.2f p99 %.2f max %.2f s; later %zu\n",
                seconds, hi, lo, hi_s, lo_s, b_tturn, threads, got.load(), 8.0 * static_cast<double>(got) / seconds,
                a_bursts, a_again, b_bursts, decoded.load(), failed.load(), direct.size(), pct(direct, 0.5),
                pct(direct, 0.9), pct(direct, 0.99), pct(direct, 1.0), turn.size() - direct.size());
    return 0;
}
