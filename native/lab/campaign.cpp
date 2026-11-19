#include "campaign.hpp"
#include "channel.hpp"
#include "metrics.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <memory>
#include <optional>
#include <span>
#include <stdexcept>
#include <string_view>
#include <utility>
#include <vector>

#include "arq/engine.hpp"
#include "receiver/receiver.hpp"
#include "util/pool.hpp"

namespace data2g::lab {
namespace {
const std::array<std::string, 7> floor_channels{"awgn", "mpg", "mpp", "mpd", "flutter", "nvis", "hilat"};
const std::array<std::string, 10> session_channels{"awgn", "mpg", "mpp", "mpd", "mps", "flutter", "nvis-d", "lowlat-d", "hilat-m", "hilat-d"};
std::vector<std::string> cpm_modes() {
    std::vector<std::string> out;
    for (const auto& m : arq::modes()) if (m.is_cpm()) out.emplace_back(m.name);
    return out;
}
std::vector<CampaignCase> build_points(const std::string& name) {
    std::vector<CampaignCase> out;
    if (name == "cpm_floor") {
        // Exact public e2e_grid(mode, channel, below=0): 9 AWGN points,
        // 14 fading points. Every shipped CPM data mode, both code rates.
        for (const auto& mode : cpm_modes()) for (const auto& channel : floor_channels) {
            double lo = mode.starts_with("fsk32") ? -12 : mode.starts_with("fsk8") ? -14 : -16;
            if (channel != "awgn") lo += 2;
            const int n = channel == "awgn" ? 9 : 14;
            for (int i = 0; i < n; ++i) {
                CampaignCase c;
                c.kind = "cpm_receiver_burst";
                c.options.channel = channel; c.options.fixed_mode = mode;
                c.options.snr_db = lo + i; c.options.cfo_hz = 4.5; c.options.horizon_s = 120;
                out.push_back(std::move(c));
            }
        }
    } else if (name == "hf_sessions" || name == "hf_extreme") {
        auto modes = cpm_modes(); modes.insert(modes.begin(), ""); // adaptive, then all fixed CPM grids/rates
        for (const auto& mode : modes) for (const auto& channel : session_channels) {
            if (name == "hf_extreme" && channel != "nvis-d" && channel != "lowlat-d" && channel != "hilat-m" && channel != "hilat-d") continue;
            for (int snr = -16; snr <= 12; snr += 4) {
                CampaignCase c;
                c.kind = "two_endpoint_loopback";
                c.options.channel = channel; c.options.fixed_mode = mode;
                c.options.snr_db = snr; c.options.cfo_hz = 4.5; c.options.horizon_s = 300;
                out.push_back(std::move(c));
            }
        }
    } else throw std::invalid_argument("unknown HF campaign");
    return out;
}
const std::vector<CampaignCase>& points(const std::string& name) {
    if (name == "cpm_floor") { static const auto data = build_points(name); return data; }
    if (name == "hf_sessions") { static const auto data = build_points(name); return data; }
    if (name == "hf_extreme") { static const auto data = build_points(name); return data; }
    throw std::invalid_argument("unknown HF campaign");
}
}
std::size_t campaign_size(const std::string& name, int trials) {
    if (trials < 1 || trials > 1000) throw std::invalid_argument("trials per point must be 1..1000");
    return points(name).size() * static_cast<std::size_t>(trials);
}
CampaignCase campaign_case(const std::string& name, std::size_t ordinal, int trials, std::uint64_t first_seed) {
    const auto n = campaign_size(name, trials);
    if (ordinal >= n) throw std::out_of_range("campaign case index");
    auto c = points(name).at(ordinal / trials);
    c.options.seed = first_seed + ordinal % trials;
    return c;
}
std::string campaign_case_json(const CampaignCase& c) {
    const auto& o = c.options;
    return "{\"workload_kind\":" + arq::json_str(c.kind) + ",\"channel\":" + arq::json_str(o.channel)
        + ",\"fixed_mode\":" + arq::json_str(o.fixed_mode) + ",\"snr_db\":" + arq::json_num(o.snr_db)
        + ",\"seed\":" + std::to_string(o.seed) + ",\"cfo_hz\":" + arq::json_num(o.cfo_hz)
        + ",\"horizon_s\":" + arq::json_num(o.horizon_s) + "}";
}

std::string run_cpm_burst(const Options& o, const std::atomic_bool& cancel,
                        const std::function<void(const std::string&)>& progress) {
    using Clock = std::chrono::steady_clock;
    const auto start = Clock::now();
    const double cpu_start = cpu_seconds();
    const auto& mode = arq::mode_at(o.fixed_mode);
    if (!mode.is_cpm() || !std::isfinite(o.snr_db) || o.snr_db < -30 || o.snr_db > 60)
        throw std::invalid_argument("CPM burst requires a CPM mode and SNR -30..60");
    if (cancel.load()) return "{\"workload_kind\":\"cpm_receiver_burst\",\"outcome\":\"cancelled\"}";
    if (progress) progress("Synthesizing " + o.fixed_mode + " through " + o.channel);
    Random data(o.seed ^ UINT64_C(0xdaa));
    auto payload = [&](int n) {
        arq::Bytes out(static_cast<std::size_t>(n));
        for (auto& v : out) v = static_cast<std::uint8_t>(data.next() & 255);
        return out;
    };
    arq::TxBurst burst;
    burst.submode = o.fixed_mode; burst.cap = 2;
    burst.slots = {{arq::ctl_mask(0, 0, 5), 0, payload(arq::ctl_payload_bytes(mode))},
                   {arq::data_mask(0, 1, 5), 0, payload(arq::payload_bytes(mode))}};
    const auto audio = arq::tx_audio(burst);
    const double t0 = 5 + 95 * data.uniform();
    Channel channel(profile(o.channel), o.seed, 120, o.cfo_hz);
    auto faded = channel.render(audio, static_cast<std::size_t>(std::llround(t0 * config::FS)));
    constexpr int pad = config::FS * 3 / 10;
    std::vector<double> y(pad + faded.size() + pad, 0);
    std::copy(faded.begin(), faded.end(), y.begin() + pad);
    Random noise(o.seed ^ UINT64_C(0xabc1));
    const double sigma = o.channel == "clean" ? 0 : std::sqrt((config::FS / 2.0) / config::SNR_REF_BW_HZ / std::pow(10., o.snr_db / 10));
    for (auto& v : y) v += sigma * noise.normal();
    const auto& g = cpm::grid_of(*cpm::spec(o.fixed_mode));
    const std::array<std::string_view, 1> grids{g.name};
    const auto head = std::min<std::size_t>(y.size(), pad + config::FS / 2 + receiver::search_span({}, grids));
    const auto base_start = Clock::now();
    if (progress) progress("Normal receiver: acquisition");
    auto lock = cpm::find(g, std::span<const double>(y).first(head), std::nullopt, 150, true, 0, std::nullopt, true);
    if (lock && lock->wait) lock = lock->header_end <= static_cast<std::int64_t>(y.size()) ? cpm::late_lock(g, y, *lock) : std::nullopt;
    if (!lock) {
        const auto lead = pad + config::FS / 2;
        const auto mid_head = std::min<std::size_t>(y.size(), lead + cpm::hdr_span(g, 2) + g.T);
        lock = cpm::find_mid(g, std::span<const double>(y).first(mid_head));
        if (lock && lock->start > lead) lock.reset();
    }
    const bool acquired = lock && lock->spec && lock->spec->name == o.fixed_mode && lock->n_data == 1 && !lock->dup;
    auto decode = [&](const cpm::Lock& at) {
        auto received = std::make_shared<const cpm::Received>(cpm::receive(y, at));
        arq::Heard h; h.cpm = std::move(received);
        arq::ModemRx rx(h); // same no-wall-budget receiver as the public floor study
        std::array<bool, 2> ok{};
        for (int i = 0; i < 2; ++i) {
            if (cancel.load()) break;
            if (progress) progress(i == 0 ? "Decode control slot" : "Decode data slot");
            const auto got = rx.decode(i, burst.slots[i].mask_id, 0, nullptr);
            ok[i] = got && *got == burst.slots[i].payload;
        }
        return ok;
    };
    const auto base = acquired && !cancel.load() ? decode(*lock) : std::array<bool, 2>{};
    const double base_wall = std::chrono::duration<double>(Clock::now() - base_start).count();
    const auto genie_start = Clock::now();
    if (progress) progress("Supplied timing/CFO/header diagnostic");
    const cpm::Lock truth{cpm::spec(o.fixed_mode), 1, false, pad, o.cfo_hz, 0, 0, 0, 0, 0};
    const auto genie = cancel.load() ? std::array<bool, 2>{} : decode(truth);
    const double genie_wall = std::chrono::duration<double>(Clock::now() - genie_start).count();
    auto flag = [](bool v) { return v ? "true" : "false"; };
    return "{\"schema\":1,\"workload_kind\":\"cpm_receiver_burst\",\"outcome\":" + arq::json_str(cancel.load() ? "cancelled" : "measured")
        + ",\"revision\":" + arq::json_str(DATA2G_LAB_REVISION) + ",\"channel\":" + arq::json_str(o.channel)
        + ",\"fixed_mode\":" + arq::json_str(o.fixed_mode) + ",\"seed\":" + std::to_string(o.seed)
        + ",\"snr_db\":" + arq::json_num(o.snr_db) + ",\"snr_reference_hz\":2500,\"cfo_hz\":" + arq::json_num(o.cfo_hz)
        + ",\"pool_threads\":" + std::to_string(pool::threads()) + ",\"acquired\":" + flag(acquired)
        + ",\"base_control_ok\":" + flag(base[0]) + ",\"base_data_ok\":" + flag(base[1])
        + ",\"supplied_control_ok\":" + flag(genie[0]) + ",\"supplied_data_ok\":" + flag(genie[1])
        + ",\"base_wall_s\":" + arq::json_num(base_wall) + ",\"supplied_wall_s\":" + arq::json_num(genie_wall)
        + ",\"wall_s\":" + arq::json_num(std::chrono::duration<double>(Clock::now() - start).count())
        + ",\"process_cpu_s\":" + arq::json_num(cpu_seconds() - cpu_start) + ",\"process_lifetime_peak_rss_bytes\":" + std::to_string(peak_rss())
        + ",\"goodput_applicable\":false,\"limits\":[\"single burst, no application session or goodput\","
          "\"paired shipped receiver and supplied-timing/CFO/header diagnostic; other research arms not ported\","
          "\"native RNG differs from NumPy; same seed is paired across native arms and SNR points\","
          "\"8 kHz mean-power channel; no RF/audio hardware; no ITU simulator certification\"]}";
}
}
