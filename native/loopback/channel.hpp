// Diagnostic only: continuous two-path Gaussian-scatter fading, not on the live path.
#pragma once

#include <complex>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

namespace data2g::lab {

struct Profile {
    std::string name;
    double delay_ms = 0, spread_hz = 0;
};
Profile profile(const std::string& name);  // clean, awgn, mpg, mpp, mpd, nvis, hilat

// Fixed SplitMix64/uniform/Box-Muller algorithm, version 1. Unlike
// std::normal_distribution it has a specified sequence across C++ libraries.
// Transcendental/FFT rounding remains tolerance-class across platforms.
class Random {
public:
    explicit Random(std::uint64_t seed) : state_(seed) {}
    std::uint64_t next();
    double uniform();
    double normal();
private:
    std::uint64_t state_;
};

class Channel {
public:
    Channel(Profile p, std::uint64_t seed, double horizon_s, double cfo_hz = 0);
    // A complete TX burst -> noiseless RX samples. Absolute sample time
    // indexes fading even across silent gaps; includes the delayed tail.
    // Active mean TX power is normalized to 1, before fading (never after).
    std::vector<double> render(std::span<const double> x, std::size_t first) const;
    const std::vector<std::complex<double>>& tap(int path) const { return taps_.at(path); }
    double tap_rate() const { return rate_; }
private:
    Profile p_;
    double cfo_, rate_ = 0;
    std::size_t delay_ = 0;
    std::vector<std::vector<std::complex<double>>> taps_;
    std::complex<double> gain(int path, std::size_t sample) const;
};

}  // namespace data2g::lab
