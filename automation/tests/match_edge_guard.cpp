#define TALLNUM_REPLAY_LIBRARY
#include "../../export_replay_128_a001_no_death.cpp"
#include <cassert>
int main(){
 game::CAPACITY=5;game::TARGET=32;game::MAX_VALUE=64;
 game::Board b{{{2,1,false},{30,1,false},{15,1,false},{10,1,false}},1};
 game::MATCH_EDGE_GUARD=false;
 auto original=game::applyRightTurn(b);assert(original && original->blocks.size()==3);
 game::MATCH_EDGE_GUARD=true;assert(!game::applyRightTurn(b));
 b.blocks[1].value=24;assert(game::applyRightTurn(b));
 b.blocks[0].value=30;assert(game::applyRightTurn(b)); // Below-F residual is not the adjacent active block.
 b.fpos=b.blocks.size();assert(game::applyRightTurn(b));
 for(int target:{40,48}){game::TARGET=target;b.fpos=1;b.blocks[1].value=40;assert(!game::applyRightTurn(b));}
 game::MATCH_EDGE_GUARD=false;assert(game::applyRightTurn(b)); // Single/buffer retain the original rules.
}
