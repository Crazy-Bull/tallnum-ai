#define main saved_generator_main
#include "../../tallnum_reachable.cpp"
#undef main
#include <cassert>
int main(){
    CAPACITY=6;TARGET=32;MAX_VALUE=48;MAX_GOAL_CELLS=1;
    ABOVE_ONLY=true;SUCCESS_NO_EXTRA_COMBOS=true;
    SINGLE_EDGE_GUARD=true;SINGLE_TIDY_EXIT=true;
    assert(isSuccess(Board{{{32,1,false}},0}));
    assert(isSuccess(Board{{{32,1,false},{8,1,false}},0}));
    assert(isSuccess(Board{{{8,1,false},{32,1,false}},1}));
    assert(!isSuccess(Board{{{32,1,false},{10,1,false}},0}));
    assert(!isSuccess(Board{{{32,1,false},{2,1,false},{4,1,false}},0}));
    assert(!isSuccess(Board{{{32,1,false},{6,2,true}},0}));
    assert(!applyRightTurn(Board{{{30,1,false},{15,1,false},{10,1,false}},0}));
    assert(applyRightTurn(Board{{{24,1,false},{15,1,false},{10,1,false}},0}));
    Board rotatesToGoal{{{16,1,false},{4,1,false},{16,3,true}},2};
    auto fullAction=doDraw(rotatesToGoal,DrawMode::BottomToTop,4);
    assert(fullAction.kind!=OutcomeKind::Success);
    assert(fullAction.board.blocks.size()==3);
    assert(fullAction.board.blocks.back().value==4);
    SINGLE_EDGE_GUARD=false;SINGLE_TIDY_EXIT=false;
    assert(doDraw(rotatesToGoal,DrawMode::BottomToTop,4).kind==OutcomeKind::Success);
    assert(isSuccess(Board{{{32,1,false},{10,1,false},{2,1,false}},0}));
    assert(applyRightTurn(Board{{{30,1,false},{15,1,false},{10,1,false}},0}));
}
