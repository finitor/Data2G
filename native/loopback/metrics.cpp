#include "metrics.hpp"

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <psapi.h>
#else
#include <sys/resource.h>
#endif

namespace data2g::lab {
double cpu_seconds() {
#ifdef _WIN32
    FILETIME created{}, exited{}, kernel{}, user{};
    if (!GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user)) return -1;
    auto ticks = [](FILETIME t) { return (static_cast<std::uint64_t>(t.dwHighDateTime) << 32) | t.dwLowDateTime; };
    return (ticks(kernel) + ticks(user)) * 1e-7;
#else
    rusage u{};
    if (getrusage(RUSAGE_SELF, &u)) return -1;
    return u.ru_utime.tv_sec + u.ru_stime.tv_sec + (u.ru_utime.tv_usec + u.ru_stime.tv_usec) * 1e-6;
#endif
}
std::int64_t peak_rss() {
#ifdef _WIN32
    PROCESS_MEMORY_COUNTERS u{};
    return GetProcessMemoryInfo(GetCurrentProcess(), &u, sizeof u) ? static_cast<std::int64_t>(u.PeakWorkingSetSize) : -1;
#else
    rusage u{};
    if (getrusage(RUSAGE_SELF, &u)) return -1;
#ifdef __APPLE__
    return u.ru_maxrss;
#else
    return static_cast<std::int64_t>(u.ru_maxrss) * 1024;
#endif
#endif
}
}
