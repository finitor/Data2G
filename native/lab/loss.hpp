#pragma once

#include <array>
#include <cstddef>
#include <span>
#include <string>
#include <vector>

#include "arq/engine.hpp"
#include "channel.hpp"

namespace data2g::lab {

struct Suppression {
    int endpoint, frame, occurrence;  // endpoint 0=A, 1=B; occurrence is one-based per endpoint/frame
    bool operator==(const Suppression&) const = default;
};
Suppression parse_suppression(const std::string& value);  // A:CONNECT:1, B:CONNECT_ACK:2, etc.
std::string frame_name(int frame);
int session_frame(const arq::TxBurst& burst);  // 0: other (including nods, IDs and CQ)

class LossPlan {
public:
    struct Decision { int frame, occurrence, rule = -1; };
    explicit LossPlan(std::vector<Suppression> rules);
    Decision decide(int endpoint, const arq::TxBurst& burst);
    void record(int endpoint, Decision d, const std::string& mode, std::size_t first, std::size_t samples);
    std::string plan_json() const;
    std::string trace_json() const;
    bool applied() const;
    int suppressed() const;
private:
    std::vector<Suppression> rules_;
    std::vector<bool> applied_;
    std::array<std::array<int, 6>, 2> counts_{};
    std::vector<std::string> trace_;
};

// The existing virtual TX seam provides exact per-frame sample ranges,
// including when an engine bundles IDs and session frames on one PTT.
// The complete original TX audio still drives engine/PTT/timer state.
class LossEngine final : public arq::Engine {
public:
    LossEngine(std::string call, arq::EngineConfig cfg, arq::EngineHooks hooks, int endpoint, LossPlan& plan);
    std::vector<double> render_tx(const Channel& channel, std::span<const double> audio, std::size_t first);
protected:
    std::vector<double> tx_audio(const arq::TxBurst& burst) override;
private:
    struct Pending { LossPlan::Decision decision; std::string mode; std::size_t samples; };
    int endpoint_;
    LossPlan& plan_;
    std::vector<Pending> pending_;
};

}  // namespace data2g::lab
