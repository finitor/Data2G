#pragma once
#include <cstdint>
namespace data2g::lab {
double cpu_seconds();  // whole process, all threads
std::int64_t peak_rss();  // process lifetime high-water mark, bytes
}
