#include "loss.hpp"

#include <algorithm>
#include <stdexcept>
#include <utility>

namespace data2g::lab {

std::string frame_name(int frame) {
    switch (frame) {
    case arq::CONNECT: return "CONNECT";
    case arq::CONNECT_ACK: return "CONNECT_ACK";
    case arq::CONNECT_NAK: return "CONNECT_NAK";
    case arq::DISC: return "DISC";
    case arq::DISC_ACK: return "DISC_ACK";
    default: return "other";
    }
}

Suppression parse_suppression(const std::string& value) {
    const auto colon = value.find(':', 2);
    if (value.size() < 5 || value[1] != ':' || (value[0] != 'A' && value[0] != 'B') || colon == std::string::npos)
        throw std::invalid_argument("suppression requires A|B:CONNECT|CONNECT_ACK|DISC|DISC_ACK:occurrence");
    const auto name = value.substr(2, colon - 2), number = value.substr(colon + 1);
    int frame = 0;
    for (int f : {arq::CONNECT, arq::CONNECT_ACK, arq::DISC, arq::DISC_ACK})
        if (name == frame_name(f)) frame = f;
    if (!frame || number.empty() || number.size() > 4 || number.find_first_not_of("0123456789") != std::string::npos)
        throw std::invalid_argument("invalid suppression frame or occurrence");
    const int occurrence = std::stoi(number);
    if (occurrence < 1 || occurrence > 1000) throw std::invalid_argument("suppression occurrence must be 1..1000");
    return {value[0] == 'A' ? 0 : 1, frame, occurrence};
}

int session_frame(const arq::TxBurst& burst) {
    if (burst.nod || burst.slots.empty()) return 0;
    if (burst.slots.front().mask_id == arq::COMPACT_CONNECT) return arq::CONNECT;
    if (burst.slots.front().mask_id.seq != arq::SEQ_MOD) return 0;
    const auto core = arq::Core::unpack(burst.slots.front().payload);
    if (core.ftype != arq::SESSION || core.n_ctl > static_cast<int>(burst.slots.size())) return 0;
    std::vector<arq::Bytes> payloads;
    for (int i = 0; i < core.n_ctl; ++i) {
        if (burst.slots[i].mask_id.seq != arq::SEQ_MOD + i) return 0;
        payloads.push_back(burst.slots[i].payload);
    }
    const auto control = arq::Control::unpack(payloads);
    const auto body = control.ext.find(arq::T_SESS);
    if (body == control.ext.end() || body->second.empty()) return 0;
    const int frame = body->second.front();
    return frame >= arq::CONNECT && frame <= arq::DISC_ACK ? frame : 0;
}

LossPlan::LossPlan(std::vector<Suppression> rules) : rules_(std::move(rules)), applied_(rules_.size(), false) {
    if (rules_.size() > 64) throw std::invalid_argument("at most 64 suppression rules");
    for (std::size_t i = 0; i < rules_.size(); ++i) {
        const auto& r = rules_[i];
        if (r.endpoint < 0 || r.endpoint > 1 || r.occurrence < 1 || r.occurrence > 1000
            || (r.frame != arq::CONNECT && r.frame != arq::CONNECT_ACK && r.frame != arq::DISC && r.frame != arq::DISC_ACK))
            throw std::invalid_argument("invalid suppression rule");
        if (std::find(rules_.begin(), rules_.begin() + static_cast<std::ptrdiff_t>(i), r)
            != rules_.begin() + static_cast<std::ptrdiff_t>(i)) throw std::invalid_argument("duplicate suppression rule");
    }
}

LossPlan::Decision LossPlan::decide(int endpoint, const arq::TxBurst& burst) {
    const int frame = session_frame(burst);
    Decision d{frame, ++counts_.at(endpoint).at(frame)};
    const auto it = std::find(rules_.begin(), rules_.end(), Suppression{endpoint, frame, d.occurrence});
    if (it != rules_.end()) d.rule = static_cast<int>(it - rules_.begin());
    return d;
}

void LossPlan::record(int endpoint, Decision d, const std::string& mode, std::size_t first, std::size_t samples) {
    if (d.rule >= 0) applied_.at(d.rule) = true;
    trace_.push_back("{\"endpoint\":" + arq::json_str(endpoint ? "B" : "A")
        + ",\"frame\":" + arq::json_str(frame_name(d.frame)) + ",\"occurrence\":" + std::to_string(d.occurrence)
        + ",\"mode\":" + arq::json_str(mode) + ",\"channel_first_sample\":" + std::to_string(first)
        + ",\"samples\":" + std::to_string(samples) + ",\"suppressed\":" + (d.rule >= 0 ? "true" : "false") + "}");
}

std::string LossPlan::plan_json() const {
    std::string out = "[";
    for (std::size_t i = 0; i < rules_.size(); ++i) {
        const auto& r = rules_[i];
        if (i) out += ',';
        out += "{\"endpoint\":" + arq::json_str(r.endpoint ? "B" : "A")
            + ",\"frame\":" + arq::json_str(frame_name(r.frame)) + ",\"occurrence\":" + std::to_string(r.occurrence)
            + ",\"applied\":" + (applied_[i] ? "true" : "false") + "}";
    }
    return out + ']';
}
std::string LossPlan::trace_json() const {
    std::string out = "[";
    for (const auto& row : trace_) { if (out.size() > 1) out += ','; out += row; }
    return out + ']';
}
bool LossPlan::applied() const { return std::all_of(applied_.begin(), applied_.end(), [](bool b) { return b; }); }
int LossPlan::suppressed() const { return static_cast<int>(std::count(applied_.begin(), applied_.end(), true)); }

LossEngine::LossEngine(std::string call, arq::EngineConfig cfg, arq::EngineHooks hooks, int endpoint, LossPlan& plan)
    : Engine(std::move(call), cfg, std::move(hooks)), endpoint_(endpoint), plan_(plan) {
    if (cfg.worker) throw std::invalid_argument("loss harness requires synchronous engines");
}
std::vector<double> LossEngine::tx_audio(const arq::TxBurst& burst) {
    auto audio = Engine::tx_audio(burst);
    pending_.push_back({plan_.decide(endpoint_, burst), burst.submode, audio.size()});
    return audio;
}
std::vector<double> LossEngine::render_tx(const Channel& channel, std::span<const double> audio, std::size_t first) {
    std::size_t cursor = static_cast<std::size_t>(config().ptt_delay_s * config::FS);
    std::size_t total = cursor;
    for (const auto& p : pending_) total += p.samples;
    if (total != audio.size() || pending_.empty()) throw std::logic_error("unmatched TX bundle in loss harness");
    std::vector<SampleRange> erasures;
    for (const auto& p : pending_) {
        // Include the leading PTT silence for a suppressed first frame:
        // the full-bundle analytic transform can ring into that prefix.
        if (p.decision.rule >= 0) erasures.push_back({&p == &pending_.front() ? 0 : cursor, cursor + p.samples});
        plan_.record(endpoint_, p.decision, p.mode, first + cursor, p.samples);
        cursor += p.samples;
    }
    pending_.clear();
    return channel.render(audio, first, erasures);
}

}  // namespace data2g::lab
