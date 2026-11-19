#include "runner.hpp"
#include "loss.hpp"
#include "channel.hpp"
#include "transport.hpp"
#include "util/pool.hpp"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
void require(bool value, const char* message) { if (!value) throw std::runtime_error(message); }

data2g::arq::TxBurst frame(int subtype, int payload_bytes = 28) {
    using namespace data2g::arq;
    Core core; core.ftype = SESSION;
    Control control{core, {{T_SESS, Bytes{static_cast<std::uint8_t>(subtype)}}}};
    TxBurst burst;
    for (const auto& p : control.pack(payload_bytes))
        burst.slots.push_back({ctl_mask(0, static_cast<int>(burst.slots.size())), 0, p});
    return burst;
}
}

int main() {
    using namespace data2g;
    using namespace data2g::lab;
    try {
        pool::set_threads(1);
        for (int subtype : {arq::CONNECT, arq::CONNECT_ACK, arq::DISC, arq::DISC_ACK}) {
            require(session_frame(frame(subtype)) == subtype, "session frame classifier");
            require(session_frame(frame(subtype, 4)) == subtype, "multi-codeword control classifier");
        }
        auto compact = frame(arq::CONNECT);
        compact.slots.front().mask_id = arq::COMPACT_CONNECT;
        require(session_frame(compact) == arq::CONNECT, "compact CONNECT classifier");
        compact.nod = std::pair{0, std::array<int, 4>{}};
        require(session_frame(compact) == 0, "nod's retained slots are not a transmitted session frame");
        arq::Core core; core.ftype = arq::SESSION;
        arq::Control id{core, {{arq::T_ID, arq::Bytes(10)}}};
        arq::TxBurst id_burst;
        for (const auto& p : id.pack(28)) id_burst.slots.push_back({arq::ctl_mask(0, 0), 0, p});
        require(session_frame(id_burst) == 0, "ID is not a session control frame");

        for (const char* bad : {"", "A", "C:CONNECT:1", "A:CONNECT:0", "A:CONNECT:-1", "A:CONNECT:1x",
                               "A:CONNECT:1001", "A:other:1", "A:CONNECT:1:2"}) {
            bool rejected = false;
            try { parse_suppression(bad); } catch (const std::invalid_argument&) { rejected = true; }
            require(rejected, "malformed suppression rejected");
        }
        const auto rule = parse_suppression("A:CONNECT:2");
        bool duplicate = false;
        try { LossPlan p({rule, rule}); } catch (const std::invalid_argument&) { duplicate = true; }
        require(duplicate, "duplicate rule rejected");
        LossPlan plan({rule});
        const auto connect = frame(arq::CONNECT);
        require(plan.decide(1, connect).rule == -1, "occurrences are per endpoint");
        require(plan.decide(0, frame(arq::DISC)).rule == -1, "occurrences are per frame");
        require(plan.decide(0, connect).rule == -1, "unselected first occurrence retained");
        const auto selected = plan.decide(0, connect);
        require(selected.rule == 0 && !plan.applied(), "selected request remains unapplied until audio emission");
        plan.record(0, selected, "test", 800, 1600);
        require(plan.applied() && plan.suppressed() == 1, "applied rule accounted once");
        require(plan.decide(0, connect).rule == -1, "later occurrence retained");

        std::vector<double> signal(1600);
        for (std::size_t i = 0; i < signal.size(); ++i) signal[i] = std::cos(.2 * i) + .2 * std::sin(.35 * i);
        for (const auto& profile_name : {"clean", "mpp", "hilat-d"}) {
            Channel channel(profile(profile_name), 17, 2, 4.5);
            const auto base = channel.render(signal, 100);
            require(base == channel.render(signal, 100, {}), "empty suppression preserves samples exactly");
            const SampleRange whole{0, signal.size()};
            const auto erased = channel.render(signal, 100, std::span(&whole, 1));
            require(erased.size() == base.size() && std::all_of(erased.begin(), erased.end(), [](double v) { return v == 0; }),
                    "whole-burst erasure includes fading tail and preserves length");
        }
        Channel clean(profile("clean"), 17, 2);
        const SampleRange middle{400, 800};
        const auto base = clean.render(signal, 100), partial = clean.render(signal, 100, std::span(&middle, 1));
        for (std::size_t i = 0; i < base.size(); ++i)
            require(partial[i] == (i >= middle.begin && i < middle.end ? 0 : base[i]),
                    "partial erasure preserves neighboring samples and original gain");
        bool bad_range = false;
        const SampleRange outside{0, signal.size() + 1};
        try { clean.render(signal, 0, std::span(&outside, 1)); } catch (const std::invalid_argument&) { bad_range = true; }
        require(bad_range, "out-of-range erasure rejected");

        // Same independent additive noise draws, even across an erased signal.
        Lane original(23, 1), erased_lane(23, 1), noise_only(23, 1);
        original.send(base); erased_lane.send(partial);
        for (int block = 0; block < 3; ++block) {
            const auto a = original.read(), b = erased_lane.read(), noise = noise_only.read();
            for (std::size_t i = 0; i < a.size(); ++i) {
                const std::size_t index = block * a.size() + i;
                require(a[i] == noise[i] + (index < base.size() ? base[index] : 0)
                        && b[i] == noise[i] + (index < partial.size() ? partial[index] : 0),
                        "transport preserves additive noise across erasures and later silence");
            }
        }

        const std::atomic_bool go{false};
        for (bool alternate : {false, true}) {
            for (const char* target : {"A:CONNECT:", "B:CONNECT_ACK:", "A:DISC:", "B:DISC_ACK:"}) {
                Options o; o.channel = "clean"; o.bytes_each_way = 16; o.horizon_s = 180; o.alternate_retries = alternate;
                o.suppressions = {parse_suppression(std::string(target) + "1"), parse_suppression(std::string(target) + "2")};
                const auto result = run(o, go);
                require(result.find("\"suppressed_bursts\":2") != std::string::npos, "both requested losses actually emitted");
                require(result.find("\"suppression_plan_applied\":true") != std::string::npos, "plan applied");
                require(result.find("\"outcome\":\"complete\"") != std::string::npos,
                        "clean mixed-peer session recovers after two selected losses with exact bytes, ACKs and close");
            }
        }
        Options absent; absent.suppressions = {parse_suppression("B:CONNECT:1")};
        const auto result = run(absent, go);
        require(result.find("\"outcome\":\"complete\"") != std::string::npos
                && result.find("\"suppression_plan_applied\":false") != std::string::npos,
                "untriggered plan remains visible despite a successful session");
        std::puts("ok: deterministic session loss selection, timing, gain, noise and complete-session recovery");
        return 0;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "%s\n", e.what());
        return 1;
    }
}
