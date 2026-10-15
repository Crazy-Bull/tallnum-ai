#define main saved_generator_main
#include "../../tallnum_reachable.cpp"
#undef main
#include <cassert>

int main() {
    TARGET=24; MAX_VALUE=48; CAPACITY=6; MAX_GOAL_CELLS=1;
    SUCCESS_NO_EXTRA_COMBOS=true; ABOVE_ONLY=true;
    Board clean{{{24,1,false},{8,1,false}},0};
    Board dirty{{{24,1,false},{12,2,true}},0};
    Board below{{{12,2,true},{24,1,false}},1};
    assert(isSuccess(clean));
    assert(!isSuccess(dirty));
    assert(!isSuccess(below)); // A Group below the fixed boundary also blocks success.
    assert(!isSuccess(Board{{{24,2,true}},0}));
    MAX_GOAL_CELLS=4;
    assert(isSuccess(Board{{{24,3,true},{8,1,false}},0}));
    assert(!isSuccess(Board{{{24,5,true}},0}));
    assert(!isSuccess(Board{{{24,2,true},{12,2,true}},0}));
    ABOVE_ONLY=false;
    assert(isSuccess(Board{{{24,1,false}},1}));
    assert(!isSuccess(Board{{{24,1,false},{12,2,true}},1}));
    SUCCESS_NO_EXTRA_COMBOS=false;
    assert(isSuccess(dirty)); // Old artifacts retain their historical semantics.
    std::cout << "clean exit model assertions passed\n";
}
