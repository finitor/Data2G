#include "runner.hpp"
#include "channel.hpp"
#include "metrics.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <deque>
#include <filesystem>
#include <span>
#include <stdexcept>
#include <utility>
#include <vector>

#include "arq/engine.hpp"
#include "util/pool.hpp"

namespace data2g::lab {
namespace {
using Clock = std::chrono::steady_clock;
constexpr int BLOCK = config::FS / 10;

struct Lane {
    std::deque<double> signal;
    Random noise;
    double sigma;
    Lane(std::uint64_t seed, double s) : noise(seed), sigma(s) {}
    std::vector<double> read() {
        std::vector<double> x(BLOCK);
        for (double& v : x) {
            v = sigma ? sigma * noise.normal() : 0;
            if (!signal.empty()) { v += signal.front(); signal.pop_front(); }
        }
        return x;
    }
    void send(std::span<const double> x) {
        if (signal.size() < x.size()) signal.resize(x.size(), 0);
        for (std::size_t i = 0; i < x.size(); ++i) signal[i] += x[i];
    }
};

struct Steps {
    std::vector<double> ms;
    template<class F> auto time(F&& f) {
        const auto start = Clock::now();
        auto out = f();
        ms.push_back(std::chrono::duration<double, std::milli>(Clock::now() - start).count());
        return out;
    }
    std::string json() {
        if (ms.empty()) return "{\"count\":0}";
        std::sort(ms.begin(), ms.end());
        double total = 0;
        for (double m : ms) total += m;
        return "{\"count\":" + std::to_string(ms.size()) + ",\"total_wall_s\":" + arq::json_num(total * .001)
             + ",\"p95_ms\":" + arq::json_num(ms[(ms.size() - 1) * 95 / 100])
             + ",\"max_ms\":" + arq::json_num(ms.back()) + "}";
    }
};
}

std::string run(const Options& o, const std::atomic_bool& cancel,
                const std::function<void(const std::string&)>& progress) {
    const auto p = profile(o.channel);
    if (!std::isfinite(o.snr_db) || o.snr_db < -30 || o.snr_db > 60 || o.horizon_s < 1 || o.horizon_s > 600
        || !std::isfinite(o.horizon_s) || o.bytes_each_way < 1 || o.bytes_each_way > 65536
        || o.bandwidth_cap < 0 || o.bandwidth_cap > 2)
        throw std::invalid_argument("SNR -30..60 dB; horizon 1..600 s; payload 1..65536 bytes; cap 0..2");
    const auto start = Clock::now();
    const double cpu_start = cpu_seconds();
    const auto channel_start = Clock::now();
    Channel ch(p, o.seed, o.horizon_s, o.cfo_hz);
    double channel_wall_s = std::chrono::duration<double>(Clock::now() - channel_start).count();
    const double sigma = p.name == "clean" ? 0 : std::sqrt((config::FS / 2.0) / config::SNR_REF_BW_HZ / std::pow(10., o.snr_db / 10));
    Lane ab(o.seed ^ UINT64_C(0xabc1), sigma), ba(o.seed ^ UINT64_C(0xabc2), sigma);
    arq::EngineConfig ca, cb;
    ca.seed = o.seed ^ UINT64_C(0xa1);
    cb.seed = o.seed ^ UINT64_C(0xb2);
    if (!o.record_dir.empty()) {
        const std::filesystem::path root(o.record_dir);
        if (std::filesystem::exists(root)) throw std::invalid_argument("record directory already exists; choose a new one");
        std::filesystem::create_directories(root / "a");
        std::filesystem::create_directories(root / "b");
        ca.record_dir = (root / "a").string();
        cb.record_dir = (root / "b").string();
    }
    // Virtual time, synchronous decode. No OS audio, radio or host sockets.
    ca.worker = cb.worker = false;
    arq::Engine a("LAB1", ca), b("LAB2", cb);
    std::array<int, 2> sent{}, heard{}, lost{};
    a.set_on_send([&](const arq::TxBurstPtr&) { ++sent[0]; });
    b.set_on_send([&](const arq::TxBurstPtr&) { ++sent[1]; });
    a.set_on_burst([&](const arq::BurstHeard& h) { ++heard[0]; lost[0] += h.lost; });
    b.set_on_burst([&](const arq::BurstHeard& h) { ++heard[1]; lost[1] += h.lost; });
    Random data(o.seed ^ UINT64_C(0xdaa));
    arq::Bytes up(o.bytes_each_way), down(o.bytes_each_way), got_a, got_b;
    for (auto& v : up) v = static_cast<std::uint8_t>(data.next() & 255);
    for (auto& v : down) v = static_cast<std::uint8_t>(data.next() & 255);
    bool connected = false, wrote = false, delivered = false, acked = false, disc = false, closed = false;
    double connect_s = -1, delivery_s = -1, ack_s = -1;
    std::string outcome = "connect_timeout";
    std::vector<std::string> events;
    Steps astep, bstep;
    b.listen();
    a.connect("LAB2", o.bandwidth_cap);
    const auto blocks = static_cast<int>(o.horizon_s * config::FS / BLOCK);
    for (int block = 0; block < blocks; ++block) {
        if (cancel.load()) { outcome = "cancelled"; break; }
        const auto channel_tick = Clock::now();
        const auto ina = ba.read(), inb = ab.read();
        channel_wall_s += std::chrono::duration<double>(Clock::now() - channel_tick).count();
        auto ao = astep.time([&] { return a.step(ina); });
        auto bo = bstep.time([&] { return b.step(inb); });
        // Both endpoints hear only previous output: identical one-block
        // transport latency in each direction, with no caller-order bias.
        const auto channel_render = Clock::now();
        if (ao.tx_abort) ab.signal.clear();
        if (bo.tx_abort) ba.signal.clear();
        if (ao.tx_burst) ab.send(ch.render(*ao.tx_burst, a.n()));
        if (bo.tx_burst) ba.send(ch.render(*bo.tx_burst, b.n()));
        channel_wall_s += std::chrono::duration<double>(Clock::now() - channel_render).count();
        const auto ra = a.session().read(), rb = b.session().read();
        got_a.insert(got_a.end(), ra.begin(), ra.end());
        got_b.insert(got_b.end(), rb.begin(), rb.end());
        for (auto& e : a.events()) events.push_back("A " + e);
        for (auto& e : b.events()) events.push_back("B " + e);
        if (got_a.size() > down.size() || got_b.size() > up.size()
            || !std::equal(got_a.begin(), got_a.end(), down.begin()) || !std::equal(got_b.begin(), got_b.end(), up.begin())) {
            outcome = "data_mismatch";
            break;
        }
        if (!wrote && a.session().state == arq::SessionState::CONNECTED && b.session().state == arq::SessionState::CONNECTED) {
            connected = wrote = true;
            connect_s = a.now();
            a.session().write(up);
            b.session().write(down);
            outcome = "delivery_timeout";
        }
        if (wrote && !delivered && got_a == down && got_b == up) {
            delivered = true;
            delivery_s = a.now();
            outcome = "ack_timeout";
        }
        // A closed/lost session can discard its queue. That is not an ACK.
        if (delivered && !acked && a.session().state == arq::SessionState::CONNECTED
            && b.session().state == arq::SessionState::CONNECTED
            && a.session().queued_bytes().unacked == 0 && b.session().queued_bytes().unacked == 0) {
            acked = true;
            ack_s = a.now();
            a.disconnect();
            disc = true;
            outcome = "disconnect_timeout";
        }
        if (disc && a.session().state == arq::SessionState::CLOSED && b.session().state == arq::SessionState::CLOSED) {
            closed = true;
            outcome = "complete";
            break;
        }
        if (progress && block % 20 == 0)
            progress(o.channel + ": " + std::to_string(static_cast<int>(a.now())) + " simulated s; "
                     + std::to_string(got_a.size() + got_b.size()) + " verified bytes");
    }
    const double simulated = a.now();
    a.stop();
    b.stop();
    const double wall = std::chrono::duration<double>(Clock::now() - start).count();
    std::string ev = "[";
    for (const auto& e : events) { if (ev.size() > 1) ev += ','; ev += arq::json_str(e); }
    ev += ']';
    auto flag = [](bool b) { return b ? "true" : "false"; };
    return "{\"schema\":1,\"revision\":" + arq::json_str(DATA2G_LAB_REVISION)
        + ",\"version\":" + arq::json_str(DATA2G_VERSION) + ",\"channel\":" + arq::json_str(o.channel)
        + ",\"compiler\":" + arq::json_str(
#ifdef _MSC_VER
            "MSVC"
#else
            __VERSION__
#endif
          ) + ",\"pool_threads\":" + std::to_string(pool::threads())
        + ",\"dd_enabled\":" + flag(ca.dd) + ",\"dd_budget_s\":" + (ca.dd_budget_s ? arq::json_num(*ca.dd_budget_s) : "null")
        + ",\"seed\":" + std::to_string(o.seed) + ",\"channel_payload_rng\":\"splitmix64-boxmuller-v1\",\"session_rng\":\"native DefaultRng; C++ library dependent\",\"snr_db\":" + arq::json_num(o.snr_db)
        + ",\"snr_reference_hz\":" + arq::json_num(config::SNR_REF_BW_HZ) + ",\"tx_active_mean_power\":1"
        + ",\"delay_ms\":" + arq::json_num(p.delay_ms) + ",\"doppler_2sigma_hz\":" + arq::json_num(p.spread_hz)
        + ",\"cfo_hz\":" + arq::json_num(o.cfo_hz) + ",\"sample_rate\":" + std::to_string(config::FS)
        + ",\"block_samples\":" + std::to_string(BLOCK) + ",\"horizon_s\":" + arq::json_num(o.horizon_s)
        + ",\"bytes_each_way\":" + std::to_string(o.bytes_each_way) + ",\"bandwidth_cap\":" + std::to_string(o.bandwidth_cap)
        + ",\"outcome\":" + arq::json_str(outcome) + ",\"connected\":" + flag(connected)
        + ",\"delivered\":" + flag(delivered) + ",\"acknowledged\":" + flag(acked) + ",\"disconnected\":" + flag(closed)
        + ",\"connect_s\":" + arq::json_num(connect_s) + ",\"delivery_s\":" + arq::json_num(delivery_s)
        + ",\"ack_s\":" + arq::json_num(ack_s) + ",\"verified_at_a\":" + std::to_string(got_a.size())
        + ",\"verified_at_b\":" + std::to_string(got_b.size()) + ",\"simulated_s\":" + arq::json_num(simulated)
        + ",\"wall_s\":" + arq::json_num(wall) + ",\"process_cpu_s\":" + arq::json_num(cpu_seconds() - cpu_start)
        + ",\"channel_wall_s\":" + arq::json_num(channel_wall_s) + ",\"record_dir\":" + arq::json_str(o.record_dir)
        + ",\"process_lifetime_peak_rss_bytes\":" + std::to_string(peak_rss())
        + ",\"a_engine_step\":" + astep.json() + ",\"b_engine_step\":" + bstep.json()
        + ",\"a_tx_bursts\":" + std::to_string(sent[0]) + ",\"b_tx_bursts\":" + std::to_string(sent[1])
        + ",\"a_heard\":" + std::to_string(heard[0]) + ",\"b_heard\":" + std::to_string(heard[1])
        + ",\"a_lost\":" + std::to_string(lost[0]) + ",\"b_lost\":" + std::to_string(lost[1])
        + ",\"events\":" + ev
        + ",\"limits\":[\"virtual-time synchronous engines; not a real-time qualification\","
          "\"shared reciprocal fading; independent receiver noise\",\"no radio, USB audio, clock drift or interference\","
          "\"selected Gaussian-scatter presets; not ITU simulator certification\","
          "\"engine step timing includes TX and RX work; not isolated decoder latency\"]}";
}
}  // namespace data2g::lab
