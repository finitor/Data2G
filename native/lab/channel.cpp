#include "channel.hpp"

#include <algorithm>
#include <cmath>
#include <numbers>
#include <stdexcept>
#include <utility>

#include "dsp/dsp.hpp"
#include "dsp/fft.hpp"
#include "generated/config.hpp"

namespace data2g::lab {

Profile profile(const std::string& name) {
    if (name == "clean" || name == "awgn") return {name, 0, 0};
    if (name == "mpg") return {name, .5, .1};
    if (name == "mpp") return {name, 2, 1};
    if (name == "mps") return {name, 2, .15};  // empirical slow/selective profile, not an ITU preset
    if (name == "mpd") return {name, 4, 2};
    if (name == "flutter") return {name, .5, 10};
    if (name == "nvis" || name == "nvis-d") return {name, 7, 1};
    if (name == "lowlat-d") return {name, 6, 10};
    if (name == "hilat-m") return {name, 3, 10};
    if (name == "hilat" || name == "hilat-d") return {name, 7, 30};
    throw std::invalid_argument("unknown channel profile: " + name);
}

std::uint64_t Random::next() {
    auto z = (state_ += UINT64_C(0x9e3779b97f4a7c15));
    z = (z ^ (z >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)) * UINT64_C(0x94d049bb133111eb);
    return z ^ (z >> 31);
}
double Random::uniform() { return (static_cast<double>(next() >> 11) + .5) * 0x1p-53; }
double Random::normal() {
    const double u = uniform(), v = uniform();
    return std::sqrt(-2 * std::log(u)) * std::cos(2 * std::numbers::pi * v);
}

Channel::Channel(Profile p, std::uint64_t seed, double horizon, double cfo) : p_(std::move(p)), cfo_(cfo) {
    if (!std::isfinite(horizon) || horizon < 1 || horizon > 600 || !std::isfinite(cfo) || std::abs(cfo) > 100)
        throw std::invalid_argument("channel horizon must be 1..600 s and CFO within +/-100 Hz");
    if (!std::isfinite(p_.delay_ms) || p_.delay_ms < 0 || p_.delay_ms > 7
        || !std::isfinite(p_.spread_hz) || p_.spread_hz < 0 || p_.spread_hz > 30)
        throw std::invalid_argument("prototype channel limits: delay 0..7 ms, spread 0..30 Hz");
    delay_ = static_cast<std::size_t>(std::llround(p_.delay_ms * .001 * config::FS));
    if (!p_.spread_hz) return;
    // Same spectral shaping and expectation normalization as hfchannel.py's
    // _gaussian_taps. A different documented RNG; not the same Python seed.
    rate_ = std::max(64 * p_.spread_hz, 8.0);
    const auto n = static_cast<std::size_t>(std::ceil((horizon + 60) * rate_)) + 2;
    std::vector<double> shape(n);
    double energy = 0;
    for (std::size_t i = 0; i < n; ++i) {
        const double k = i < (n + 1) / 2 ? static_cast<double>(i) : static_cast<double>(i) - n;
        const double f = k * rate_ / n;
        shape[i] = std::exp(-f * f / (p_.spread_hz * p_.spread_hz));
        energy += shape[i] * shape[i];
    }
    const double norm = std::sqrt(2 * energy / n);
    Random rng(seed);
    for (int path = 0; path < 2; ++path) {
        std::vector<std::complex<double>> g(n);
        // Explicit draw order, also used by the Python parity check.
        for (auto& z : g) z.real(rng.normal());
        for (auto& z : g) z.imag(rng.normal());
        auto spectrum = dsp::fft(g, true);
        for (std::size_t i = 0; i < n; ++i) spectrum[i] *= shape[i];
        g = dsp::fft(spectrum, false);
        for (auto& z : g) z /= norm;
        taps_.push_back(std::move(g));
    }
}

std::complex<double> Channel::gain(int path, std::size_t sample) const {
    const double t = sample * rate_ / config::FS;
    const auto i = static_cast<std::size_t>(t);
    const auto& g = taps_.at(path);
    if (i + 1 >= g.size()) throw std::out_of_range("channel timeline exhausted");
    return g[i] + (g[i + 1] - g[i]) * (t - i);
}

std::vector<double> Channel::render(std::span<const double> x, std::size_t first,
                                    std::span<const SampleRange> erasures) const {
    for (const auto& r : erasures)
        if (r.begin > r.end || r.end > x.size()) throw std::invalid_argument("erasure outside TX samples");
    if (x.empty()) return {};
    auto z = dsp::hilbert(x);
    double mean = 0;
    for (double v : x) mean += v * v;
    const double threshold = .1 * std::sqrt(mean / x.size());
    double power = 0;
    std::size_t active = 0;
    for (std::size_t i = 0; i < x.size(); ++i) {
        if (std::abs(z[i]) > threshold) { power += x[i] * x[i]; ++active; }
    }
    if (!active || power == 0) return std::vector<double>(x.size() + delay_, 0);
    const double scale = std::sqrt(active / power);
    for (const auto& r : erasures)
        std::fill(z.begin() + static_cast<std::ptrdiff_t>(r.begin), z.begin() + static_cast<std::ptrdiff_t>(r.end), 0);
    std::vector<double> y(x.size() + delay_);
    for (std::size_t i = 0; i < y.size(); ++i) {
        std::complex<double> v = i < z.size() ? z[i] : 0;
        if (rate_) {
            const auto delayed = i >= delay_ && i - delay_ < z.size() ? z[i - delay_] : 0;
            v = (v * gain(0, first + i) + delayed * gain(1, first + i)) / std::sqrt(2.0);
        }
        const double cycles = std::remainder(cfo_ * ((first + i) / static_cast<double>(config::FS)), 1.0);
        y[i] = (v * std::polar(scale, 2 * std::numbers::pi * cycles)).real();
    }
    return y;
}

}  // namespace data2g::lab
