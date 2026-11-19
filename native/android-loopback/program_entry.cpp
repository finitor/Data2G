// Add accounting around an original, unmodified native test/tool entry point.
#ifdef main
#undef main
#endif
#include <cstdio>
#include <exception>
#include <unistd.h>
#include "metrics.hpp"
#ifdef DATA2G_LAB_TEST
#include "check.hpp"
int data2g_lab_program_main();
#else
int data2g_lab_program_main(int, char**);
#endif
int main(int argc, char** argv) {
    std::setvbuf(stdout, nullptr, _IOLBF, 0);
    std::setvbuf(stderr, nullptr, _IOLBF, 0);
    std::printf("LAB_PID %d\n", static_cast<int>(getpid()));
    std::printf("LAB_REVISION %s\n", DATA2G_LAB_REVISION);
    std::fflush(stdout);
    int result = 2;
    try {
#ifdef DATA2G_LAB_TEST
        (void)argc; (void)argv;
        result = data2g_lab_program_main();
#else
        result = data2g_lab_program_main(argc, argv);
#endif
    } catch (const std::exception& e) {
        std::fprintf(stderr, "uncaught exception: %s\n", e.what());
    }
    std::printf("LAB_SUMMARY {\"cpu_s\":%.9f,\"peak_rss_bytes\":%lld,\"exit_code\":%d"
#ifdef DATA2G_LAB_TEST
                ",\"checks\":%d,\"failures\":%d"
#endif
                "}\n", data2g::lab::cpu_seconds(), static_cast<long long>(data2g::lab::peak_rss()), result
#ifdef DATA2G_LAB_TEST
                , data2g::check::checks, data2g::check::failures
#endif
    );
    std::fflush(stdout);
    return result;
}
