#pragma once

#include "arq/policy.hpp"

namespace data2g::lab {

// Study only: the caller alternates existing CPM modes after the first
// robust retry. The peer retains the shipped policy and replies in the
// received mode. No channel knowledge is used before connecting.
// connect_mode also selects DISC retries, as in the shipped GearPolicy.
class AlternatingRetryPolicy final : public arq::GearPolicy {
public:
    std::string connect_mode(int cap, int tries) override {
        if (tries > 0 && tries % 2 == 0) return std::string(arq::ROBUST_FAST);
        return arq::GearPolicy::connect_mode(cap, tries);
    }
};

}  // namespace data2g::lab
