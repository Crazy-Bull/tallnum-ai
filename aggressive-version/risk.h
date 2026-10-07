#pragma once
#include <cmath>
#include <fstream>
#include <stdexcept>
#include <string>
namespace tallnumRisk {
inline double aggressiveness=0, deathProbability=0, survival=1, inputAggressiveness=0;
inline void parse(const std::string& text) {
    size_t used=0; aggressiveness=std::stod(text,&used);
    if(used!=text.size() || !std::isfinite(aggressiveness) || aggressiveness<0)
        throw std::runtime_error("aggressiveness must be finite and nonnegative");
}
inline void configure(unsigned target) {
    if(aggressiveness>double(target)/7.5)
        throw std::runtime_error("aggressiveness exceeds target / 7.5");
    deathProbability=aggressiveness*7.5/double(target);
    if(deathProbability>1) deathProbability=1;
    survival=1-deathProbability;
    inputAggressiveness=aggressiveness;
}
inline void write(std::ofstream& out) {
    out.write(reinterpret_cast<const char*>(&aggressiveness),sizeof(double));
}
inline void check(std::ifstream& in) {
    double saved=0; in.read(reinterpret_cast<char*>(&saved),sizeof(double));
    if(!in || !std::isfinite(saved) || saved!=inputAggressiveness)
        throw std::runtime_error("aggressiveness mismatch in values/policy/checkpoint");
}
}
