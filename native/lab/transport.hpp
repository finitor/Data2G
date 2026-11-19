#pragma once

#include <cstddef>
#include <cstdint>
#include <deque>
#include <span>
#include <vector>

#include "channel.hpp"
#include "generated/config.hpp"

namespace data2g::lab {

// Additive receiver noise is drawn on every channel-clock sample, whether
// a signal is queued, suppressed or absent. Erasures affect only signal.
struct Lane {
    std::deque<double> signal;
    Random noise;
    double sigma;
    Lane(std::uint64_t seed, double s) : noise(seed), sigma(s) {}
    std::vector<double> read() {
        std::vector<double> x(config::FS / 10);
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

}  // namespace data2g::lab
