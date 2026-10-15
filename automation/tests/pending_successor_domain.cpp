#define TALLNUM_PENDING_REALBOARD_LIBRARY
#include "../pending_value_realboard.cpp"
#include <cassert>

int main() {
    PendingValues p;
    p.header.capacity=6;p.header.target=32;p.header.maxGoalCells=1;
    p.header.aboveOnly=1;p.header.bases={1,3,5,15};p.maxValue=48;
    p.clean=true;
    PendingValues::configure(p);
    Board input;input.fpos=0;input.blocks={{15,1,false}};
    game::State state{input,0,1}; // previews 2,4
    auto successor=game::doDraw(input,DrawMode(1),2);
    assert(successor.kind==game::OutcomeKind::Next);
    p.sixBoardIdsByKey.push_back({PendingValues::makeBoardKey(successor.board),0});
    uint64_t wanted=game::encodePostDraw(0,state.q2);
    p.entries.push_back({wanted,.75});
    auto result=p.best(state);
    assert(!result.first && result.second==wanted);
    // Current input and earlier candidates are absent, yet the known
    // successor remains usable and recovers an actual action.
    std::ostringstream output;auto* previous=std::cout.rdbuf(output.rdbuf());
    p.query("0 1 2 4 15 1 0");
    std::cout.rdbuf(previous);
    assert(output.str().find("\"status\":\"ok\"")!=std::string::npos);
    p.entries.clear();
    bool rejected=false;
    try{p.best(state);}catch(const std::runtime_error& e){rejected=std::string(e.what())=="out-of-model-state";}
    assert(rejected); // Unknown values must never masquerade as certain death.
    PendingValues five;
    five.header.capacity=5;five.header.target=6;five.header.maxGoalCells=1;
    five.header.aboveOnly=1;five.header.bases={1,3,5,15};five.maxValue=48;
    five.clean=true;five.singleTidyExit=true;
    PendingValues::configure(five);
    Board exit;exit.fpos=0;exit.blocks={{6,1,false},{8,1,false}};
    assert(game::isSuccess(exit));
    exit.blocks[1].value=15;assert(!game::isSuccess(exit));
    exit.blocks={{4,1,false},{6,1,false},{2,1,false}};exit.fpos=1;
    assert(!game::isSuccess(exit)); // Both sides of F count toward the limit.
    five.singleEdgeGuard=true;five.singleProtectedHead=1;
    PendingValues::configure(five);
    Board guarded;guarded.fpos=0;guarded.blocks={{16,1,false},{10,1,false}};
    assert(!game::applyRightTurn(guarded));
    guarded.blocks={{32,1,false},{30,1,false}};
    auto safe=game::applyRightTurn(guarded);
    assert(safe && game::isSuccess(*safe));
    // Exact boundaries permit an active EDGE pair to shield the anchor.
    five.singleProtectedValue=18;
    PendingValues::configure(five);
    guarded.blocks={{15,1,false},{16,1,false}};
    assert(game::applyRightTurn(guarded));
    guarded.blocks={{15,1,false},{20,1,false}};
    assert(!game::applyRightTurn(guarded));
    // A matching group has collapsed into the ordinary anchor before UP
    // draws. Its old span must not produce a false capacity death.
    five.header.target=32;five.header.maxGoalCells=5;five.maxValue=48;
    five.singleProtectedValue=32;five.singleProtectedHead=3;
    five.singleEdgeGuard=false;five.matchEdgeGuard=true;
    PendingValues::configure(five);
    Board matching;matching.fpos=1;matching.blocks={{32,4,true}};
    auto drawn=game::doDraw(matching,DrawMode::BottomToTop,4);
    assert(drawn.kind==game::OutcomeKind::Success);
    drawn=game::doDraw(matching,DrawMode::BottomToTop,15);
    assert(drawn.kind!=game::OutcomeKind::Success);
    five.header.target=64;five.header.maxGoalCells=4;five.maxValue=64;
    five.singleProtectedValue=32;five.singleProtectedHead=3;five.extensionExit=true;
    PendingValues::configure(five);
    Board extension;extension.fpos=0;extension.blocks={{48,1,false},{16,1,false}};
    bool groupExit=false;
    for(auto move:freeMoves(extension))if(move.second.kind==0 && game::isSuccess(move.first)){
        groupExit=true;assert(!move.first.blocks[0].combo);
    }
    assert(groupExit);
    extension.blocks={{64,2,true}};assert(!game::isSuccess(extension));
    extension.fpos=1;
    drawn=game::doDraw(extension,DrawMode::BottomToTop,4);
    assert(drawn.kind==game::OutcomeKind::Next);
    extension.fpos=0;extension.blocks={{32,1,false},{32,1,false}};
    assert(!game::normalize(extension));
    std::cout << "successor-domain regression passed\n";
}
