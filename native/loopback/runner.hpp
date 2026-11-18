#pragma once

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>

namespace data2g::lab {

struct Options {
    std::string channel = "clean";
    std::string record_dir;  // optional existing Recorder format, a/ and b/
    double snr_db = 12, horizon_s = 180, cfo_hz = 0;
    std::uint64_t seed = 1;
    std::size_t bytes_each_way = 64;
    int bandwidth_cap = 2;  // 0=500, 1=1700, 2=2400 Hz
};
// Returns a complete JSON record, including failed/cancelled trials. Progress
// callbacks run on the caller's thread; all modem state stays on that thread.
std::string run(const Options& o, const std::atomic_bool& cancel,
                const std::function<void(const std::string&)>& progress = {});

}  // namespace data2g::lab
