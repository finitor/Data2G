#pragma once
#include "runner.hpp"
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <string>
namespace data2g::lab {
struct CampaignCase { Options options; std::string kind; };
std::size_t campaign_size(const std::string& name, int trials);
CampaignCase campaign_case(const std::string& name, std::size_t ordinal, int trials, std::uint64_t first_seed);
std::string campaign_case_json(const CampaignCase& c);
// Native port of cpm_floor_study.py's baseline and supplied-information arms.
// Both arms receive exactly the same faded/noisy burst; no application session.
std::string run_cpm_burst(const Options& o, const std::atomic_bool& cancel,
                        const std::function<void(const std::string&)>& progress = {});
}
