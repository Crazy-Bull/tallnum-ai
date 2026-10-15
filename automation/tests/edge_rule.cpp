#include <bits/stdc++.h>
namespace game {
#define main saved_reachable_main
#include "../../tallnum_reachable.cpp"
#undef main
}

int main() {
    game::TARGET = 16;
    game::MAX_VALUE = 32;
    if (!game::isAllowedOrdinary(24) || !game::isAllowedOrdinary(32)
            || game::isAllowedOrdinary(48)) return 3;
    game::Board intermediate;
    intermediate.blocks.push_back(game::Block{24, 1, false});
    if (!game::boardWithinModel(intermediate) || game::isSuccess(intermediate)) return 4;
    game::MAX_VALUE = 16;
    if (game::boardWithinModel(intermediate)) return 5;
    game::MAX_VALUE = 256;
    game::TARGET = 256;
    for (const auto& example : std::vector<std::pair<std::vector<int>, std::vector<int>>>{
             {{10, 15, 24}, {2, 24}},
             {{240, 244, 40}, {8}}}) {
        game::Board board;
        for (int value : example.first)
            board.blocks.push_back(game::Block{static_cast<uint16_t>(value), 1, false});
        auto result = game::applyRightTurn(board);
        if (!result) return 1;
        std::vector<int> actual;
        for (const auto& block : result->blocks) actual.push_back(block.value);
        if (actual != example.second) return 2;
    }
    return 0;
}
