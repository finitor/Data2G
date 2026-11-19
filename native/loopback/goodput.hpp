// Application-byte accounting on channel time, never decoder processing time.
#pragma once
#include <algorithm>
#include <array>
#include <cstddef>
#include <deque>
#include <stdexcept>

namespace data2g::lab {
class Goodput {
public:
    struct Point { double t; std::array<std::size_t, 4> bytes; }; // delivered AB/BA, acknowledged AB/BA
    explicit Goodput(double window = 30) : window_(window) { history_.push_back({0, {}}); }
    void add(double t, std::array<std::size_t, 4> counts) {
        const auto& last = history_.back();
        if (t < last.t) throw std::logic_error("goodput time went backwards");
        for (int k = 0; k < 4; ++k)
            if (counts[k] < last.bytes[k]) throw std::logic_error("goodput byte counter went backwards");
        if (t == last.t) history_.back() = {t, counts}; else history_.push_back({t, counts});
        while (history_.size() > 1 && history_[1].t <= t - window_) history_.pop_front();
    }
    std::array<double, 4> bps() const {
        std::array<double, 4> out{};
        const double seconds = std::min(window_, history_.back().t);
        if (seconds > 0)
            for (int k = 0; k < 4; ++k) out[k] = 8.0 * (history_.back().bytes[k] - history_.front().bytes[k]) / seconds;
        return out;
    }
private:
    double window_;
    std::deque<Point> history_;
};
}
