#include <bits/stdc++.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <optional>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

// Reuse the exact saved model and table reader. Only the replay instrumentation
// below is new; every detailed operation is checked against the model function.
namespace game {
#define main saved_reachable_main
#include "tallnum_reachable.cpp"
#undef main
}
namespace solver {
#define main saved_vi_main
#include "tallnum_vi.cpp"
#undef main
}
using namespace std;
using game::Board;
using game::Block;
using game::DrawMode;

static string quote(const string& s) {
    string out = "\"";
    for (char c : s) {
        if (c == '\\' || c == '"') { out += '\\'; out += c; }
        else if (c == '\n') out += "\\n";
        else out += c;
    }
    return out + "\"";
}
static string boardJSON(const Board& b) {
    ostringstream out;
    out << "{\"fpos\":" << int(b.fpos) << ",\"blocks\":[";
    for (size_t i = 0; i < b.blocks.size(); ++i) {
        if (i) out << ',';
        const auto& x = b.blocks[i];
        out << "{\"value\":" << x.value << ",\"span\":" << int(x.span)
            << ",\"combo\":" << (x.combo ? "true" : "false") << '}';
    }
    return out.str() + "]}";
}
struct Recorder {
    vector<string> frames;
    int macro = 0, q1 = 2, q2 = 4, draws = 0;
    uint32_t sid = 0;
    double value = 0;
    void emit(const Board& b, const string& type, const string& label,
              const string& detail, bool temporary = false, const string& extra = "") {
        ostringstream out;
        out << setprecision(17) << "{\"index\":" << frames.size()
            << ",\"macro\":" << macro << ",\"draws\":" << draws
            << ",\"q1\":" << q1 << ",\"q2\":" << q2 << ",\"sid\":" << sid
            << ",\"value\":" << value << ",\"type\":" << quote(type)
            << ",\"label\":" << quote(label) << ",\"detail\":" << quote(detail)
            << ",\"temporary\":" << (temporary ? "true" : "false")
            << ",\"board\":" << boardJSON(b) << extra << '}';
        frames.push_back(out.str());
    }
} rec;

static optional<Board> detailedNormalize(Board b) {
    auto expected = game::normalize(b);
    while (true) {
        bool changed = false;
        for (int i = int(b.blocks.size()) - 2; i >= 0; --i) {
            if (i + 1 == b.fpos || b.blocks[i].value != b.blocks[i+1].value) continue;
            int v = b.blocks[i].value;
            int cells = b.blocks[i].span + b.blocks[i+1].span;
            if (!game::mergePair(b, i)) {
                if (expected) throw runtime_error("normalization rejection mismatch");
                return nullopt;
            }
            rec.emit(b, "merge", "自动合并", to_string(v) + " + " + to_string(v)
                + " → " + to_string(2*v) + "；原占 " + to_string(cells)
                + " 格，合成后占 1 格。程序从栈顶向下扫描，合并后重新扫描。");
            changed = true;
            break;
        }
        if (!changed) break;
    }
    optional<Board> result = game::boardWithinModel(b) ? optional<Board>(b) : nullopt;
    if (result != expected) throw runtime_error("normalization trace differs from model");
    return result;
}

struct Op { int kind = 0, l = 0, r = 0; }; // 0=combo, 1=right turn
struct Node { Board b; int parent = -1; Op op; };
struct Plan { vector<Op> freeOps; int mode = -1; };

static vector<pair<Board,Op>> freeMoves(const Board& b) {
    vector<pair<Board,Op>> result;
    if (!game::hasCombo(b)) {
        for (int l=0; l<int(b.blocks.size()); ++l) {
            int sum=0;
            for (int r=l; r<int(b.blocks.size()) && r-l+1<=5; ++r) {
                if (b.blocks[r].span!=1 || b.blocks[r].combo) break;
                sum += b.blocks[r].value;
                if (r==l || game::crossesF(b,l,r) || sum>(game::MAX_VALUE ? game::MAX_VALUE : game::TARGET)) continue;
                Board nb=b;
                nb.blocks.erase(nb.blocks.begin()+l,nb.blocks.begin()+r+1);
                nb.blocks.insert(nb.blocks.begin()+l,Block{uint16_t(sum),uint8_t(r-l+1),true});
                if (r<b.fpos) nb.fpos=uint8_t(int(b.fpos)-(r-l));
                if (auto z=game::normalizeGroupMove(nb)) result.push_back({*z,Op{0,l,r}});
            }
        }
    }
    if (auto z=game::applyRightTurn(b)) result.push_back({*z,Op{1,0,0}});
    return result;
}

static Plan recoverPlan(const game::State& state, bool success, uint64_t wanted,
                        const function<uint64_t(const Board&)>& boardId = game::encodeBoard) {
    vector<Node> nodes{{state.board,-1,{}}};
    unordered_set<Board,game::BoardHash> seen{state.board};
    for (size_t i=0; i<nodes.size(); ++i) {
        Board b=nodes[i].b;
        int found=-2;
        if (success && game::isSuccess(b)) found=-1;
        if (found==-2) {
            for (int m=0; m<3; ++m) {
                auto out=game::doDraw(b,DrawMode(m),game::SPAWN[state.q1]);
                if ((success && out.kind==game::OutcomeKind::Success) ||
                    (!success && out.kind==game::OutcomeKind::Next &&
                    game::encodePostDraw(boardId(out.board),state.q2)==wanted)) {
                    found=m; break;
                }
            }
        }
        if (found!=-2) {
            Plan p; p.mode=found;
            for (int j=int(i); nodes[j].parent!=-1; j=nodes[j].parent) p.freeOps.push_back(nodes[j].op);
            reverse(p.freeOps.begin(),p.freeOps.end());
            return p;
        }
        for (auto [nb,op]:freeMoves(b)) if (seen.insert(nb).second) nodes.push_back({nb,int(i),op});
    }
    throw runtime_error("could not expand chosen compressed action");
}

static Board detailedRightTurn(const Board& src) {
    auto expected=game::applyRightTurn(src);
    if (!expected) throw runtime_error("invalid right-turn plan");
    vector<game::TempBlock> t;
    int fpos=src.fpos;
    for (const auto& x:src.blocks) {
        auto tv=game::rightTurnDigitMap(x.value);
        t.push_back({tv.value,tv.valid,x,false});
    }
    auto tempBoard=[&]() {
        Board b; b.fpos=uint8_t(fpos);
        for (const auto& x:t) b.blocks.push_back(Block{uint16_t(x.curValid?x.cur:0),x.orig.span,x.orig.combo});
        return b;
    };
    rec.emit(tempBoard(),"right-temp","右转：临时去个位",
        "每个值临时变成 floor(值 / 10)；个位数显示为空且不能合并。未参与合并的块稍后恢复原值。",true);
    while (true) {
        bool changed=false;
        for (int i=int(t.size())-2;i>=0;--i) {
            if (i+1==fpos || !t[i].curValid || !t[i+1].curValid || t[i].cur!=t[i+1].cur) continue;
            int old=t[i].cur, nv=2*old;
            auto next=game::rightTurnDigitMap(nv);
            game::TempBlock merged{next.value,next.valid,Block{uint16_t(nv),1,false},true};
            bool below=i+1<fpos;
            t[i]=merged; t.erase(t.begin()+i+1);
            if (below) --fpos;
            rec.emit(tempBoard(),"right-merge","右转：临时数字合并",
                to_string(old)+" + "+to_string(old)+" → "+to_string(nv)+"，程序把结果记为普通单格块。",true);
            changed=true; break;
        }
        if (!changed) break;
    }
    Board b; b.fpos=uint8_t(fpos);
    for (const auto& x:t) b.blocks.push_back(x.orig);
    rec.emit(b,"right-restore","右转：恢复未合并块",
        "参与临时合并的块保留新值；其余块恢复右转前的原值、组合状态和占格数。随后执行普通自动合并。");
    auto z=detailedNormalize(b);
    if (z!=expected) throw runtime_error("right-turn trace differs from model");
    return *z;
}

static Board replayFree(Board b, const Op& op) {
    if (op.kind==1) return detailedRightTurn(b);
    int sum=0; string terms;
    for (int i=op.l;i<=op.r;++i) { if(i>op.l) terms+=" + "; terms+=to_string(b.blocks[i].value); sum+=b.blocks[i].value; }
    Board original=b;
    b.blocks.erase(b.blocks.begin()+op.l,b.blocks.begin()+op.r+1);
    b.blocks.insert(b.blocks.begin()+op.l,Block{uint16_t(sum),uint8_t(op.r-op.l+1),true});
    if(op.r<b.fpos) b.fpos=uint8_t(int(b.fpos)-(op.r-op.l));
    rec.emit(b,"combo","创建组合块",terms+" = "+to_string(sum)+"；组合占 "+to_string(op.r-op.l+1)+" 格。该操作在模型中不消耗落数。");
    auto z=detailedNormalize(b);
    if(!z) throw runtime_error("combination failed in replay");
    auto moves=game::formCombinationMoves(original);
    if(find(moves.begin(),moves.end(),*z)==moves.end()) throw runtime_error("combination trace differs from model");
    return *z;
}

static pair<Board,bool> replayDraw(const Board& src, int mode) {
    auto expected=game::doDraw(src,DrawMode(mode),rec.q1);
    auto rotated=game::rotateOne(src,DrawMode(mode));
    if(!rotated) throw runtime_error("illegal rotation in chosen plan");
    string label=mode==0?"不循环移动":(mode==1?"栈顶移到栈底":"栈底移到栈顶");
    rec.emit(*rotated,"rotate",label,
        "这一步与随后落数属于同一宏动作。组合块整体移动；不能把固定块 F 拆开。先检查循环移动引起的自动合并。");
    auto z=detailedNormalize(*rotated);
    if(!z) throw runtime_error("rotation left model");
    Board b=*z;
    if(game::isSuccess(b)) {
        if(expected.kind!=game::OutcomeKind::Success) throw runtime_error("success mismatch");
        return {b,true};
    }
    b.blocks.push_back(Block{uint16_t(rec.q1),1,false});
    ++rec.draws;
    rec.emit(b,"draw","预览 q1 落入栈顶",to_string(rec.q1)+" 从顶部进入。模型先插入、再自动合并、最后判断是否满格失败。");
    z=detailedNormalize(b);
    if(!z) throw runtime_error("draw left model");
    b=*z;
    bool win=game::isSuccess(b);
    auto kind=win?game::OutcomeKind::Success:(game::usedCells(b)>=5?game::OutcomeKind::Dead:game::OutcomeKind::Next);
    if(kind!=expected.kind || (kind==game::OutcomeKind::Next && b!=expected.board))
        throw runtime_error("draw trace differs from model");
    return {b,win};
}

#ifndef TALLNUM_REPLAY_LIBRARY
int main(int argc,char** argv) {
    try {
        if(argc!=5) throw runtime_error("usage: exporter TABLE POLICY VALUES OUTPUT_JSON");
        const string table=argv[1], policyPath=argv[2], values=argv[3], output=argv[4];
        auto mdp=solver::loadMDP(table);
        if(mdp.header.capacity!=5 || mdp.header.target!=128) throw runtime_error("expected five-cell 128 table");
        constexpr double aggressiveness=0.01;
        const double deathProbability=aggressiveness*7.5/mdp.header.target;
        uint64_t policySignature=0;
        auto identity=[&](ifstream& f) {
            if(solver::readPod<double>(f)!=aggressiveness) throw runtime_error("input aggressiveness mismatch");
            const auto& h=mdp.header;
            if(solver::readPod<uint32_t>(f)!=4 || solver::readPod<uint32_t>(f)!=h.capacity ||
               solver::readPod<uint32_t>(f)!=h.target || solver::readPod<uint64_t>(f)!=h.states ||
               solver::readPod<uint32_t>(f)!=h.maxGoalCells || solver::readPod<uint32_t>(f)!=h.aboveOnly ||
               solver::readPod<uint32_t>(f)!=h.bases.size()) throw runtime_error("input configuration mismatch");
            for(auto b:h.bases) if(solver::readPod<uint32_t>(f)!=b) throw runtime_error("input bases mismatch");
            return solver::readPod<uint64_t>(f);
        };
        ifstream pf(policyPath,ios::binary); array<char,8> magic{}; pf.read(magic.data(),8);
        if(string(magic.data(),8)!="TALLAPO1") throw runtime_error("expected aggressiveness-aware TALLAPO1 policy");
        policySignature=identity(pf);
        vector<uint32_t> policy(mdp.header.states);
        pf.read(reinterpret_cast<char*>(policy.data()),streamsize(policy.size()*sizeof(uint32_t)));
        if(!pf || pf.peek()!=ifstream::traits_type::eof()) throw runtime_error("invalid policy file size");
        struct Snapshot { uint64_t iterations=0; vector<double> value; } snapshot;
        ifstream vf(values,ios::binary); vf.read(magic.data(),8);
        if(string(magic.data(),8)!="TALLAPA1" || identity(vf)!=policySignature) throw runtime_error("policy values mismatch");
        snapshot.value.resize(mdp.header.states);
        vf.read(reinterpret_cast<char*>(snapshot.value.data()),streamsize(snapshot.value.size()*sizeof(double)));
        if(!vf || vf.peek()!=ifstream::traits_type::eof()) throw runtime_error("invalid policy values size");
        game::CAPACITY=mdp.header.capacity; game::TARGET=mdp.header.target;
        game::MAX_GOAL_CELLS=mdp.header.maxGoalCells; game::ABOVE_ONLY=mdp.header.aboveOnly;
        game::BASES.assign(mdp.header.bases.begin(),mdp.header.bases.end());
        vector<uint64_t> codes;
        uint64_t signature=14695981039346656037ULL;
        auto mix=[&](uint64_t x) {for(int k=0;k<8;++k){signature^=x&255;signature*=1099511628211ULL;x>>=8;}};
        ifstream in(table,ios::binary); solver::readHeader(in);
        for(uint64_t i=0;i<mdp.header.states;++i) {
            codes.push_back(solver::readPod<uint64_t>(in)); mix(codes.back());
            mix(solver::readPod<uint8_t>(in));
            auto n=solver::readPod<uint32_t>(in);
            mix(n); for(uint32_t j=0;j<n;++j) mix(solver::readPod<uint64_t>(in));
        }
        if(!in) throw runtime_error("failed reading state codes");
        if(signature!=policySignature) throw runtime_error("policy transition fingerprint mismatch");
        auto boards=solver::readPod<uint64_t>(in);
        for(uint64_t id=0;id<boards;++id) {
            Board b; auto n=solver::readPod<uint32_t>(in); b.fpos=solver::readPod<uint8_t>(in);
            for(uint32_t j=0;j<n;++j) {
                Block x; x.value=solver::readPod<uint16_t>(in); x.span=solver::readPod<uint8_t>(in);
                x.combo=solver::readPod<uint8_t>(in)!=0; b.blocks.push_back(x);
            }
            if(game::encodeBoard(b)!=id) throw runtime_error("board dictionary mismatch");
        }
        mt19937_64 rng(20260926);
        uniform_int_distribution<int> die(0,5);
        int initialQ1=die(rng), initialQ2=die(rng);
        uint32_t sid=uint32_t(initialQ1*6+initialQ2);
        string outcome="limit";
        vector<int> randomDraws;
        vector<string> decisions;
        for(int macro=0;macro<10000;++macro) {
            auto state=game::decodeState(codes[sid]);
            rec.macro=macro; rec.sid=sid; rec.value=snapshot.value[sid];
            rec.q1=game::SPAWN[state.q1]; rec.q2=game::SPAWN[state.q2];
            const auto& row=mdp.rows[sid];
            uint32_t choice=policy[sid];
            bool success=choice==0xFFFFFFFFu;
            bool dead=choice==0xFFFFFFFEu;
            if(success && !(row.flags & solver::SUCCESS_FLAG)) throw runtime_error("invalid success policy action");
            if(dead && !(row.flags & 2u)) throw runtime_error("invalid dead policy action");
            if(!success && !dead && choice>=row.actionCount) throw runtime_error("invalid policy action index");
            double best=0;
            uint32_t gid=solver::INVALID_ID;
            ostringstream alternatives; alternatives<<setprecision(17)<<'[';
            for(uint32_t j=0;j<row.actionCount;++j) {
                uint32_t g=mdp.actionGroups[row.actionBegin+j];
                double q=0; for(auto next:mdp.groups[g]) q+=snapshot.value[next]; q*=(1-deathProbability)/6;
                if(j) alternatives<<',';
                alternatives<<"{\"index\":"<<j<<",\"score\":"<<q<<",\"post\":"
                    <<quote(to_string(solver::prefixFromStateCode(codes[mdp.groups[g][0]])))<<'}';
                if(!success && !dead && j==choice) {best=q;gid=g;}
            }
            alternatives<<']';
            uint64_t post=(success || gid==solver::INVALID_ID)?0:solver::prefixFromStateCode(codes[mdp.groups[gid][0]]);
            ostringstream extra; extra<<setprecision(17)<<",\"alternatives\":"<<alternatives.str()
                <<",\"chosenPost\":"<<quote(to_string(post))<<",\"chosenScore\":"<<(success?1:best)
                <<",\"successAction\":"<<(success?"true":"false")<<",\"stateCode\":"<<quote(to_string(codes[sid]));
            rec.emit(state.board,"decision","策略选择宏动作",
                "只使用当前局面和已知的 q1、q2。优先执行能立即成功的动作；否则直接执行保存的 PETSc 策略动作；候选评分仅供核对。此时尚未生成 q3。",false,extra.str());
            if(!success && gid==solver::INVALID_ID) {
                outcome="policy-dead";
                rec.emit(state.board,"end","保存策略选择终止失败动作","回放在该终止策略动作之前停止，未展开具体失败操作；这不表示此状态的全部动作都必败。");
                break;
            }
            Plan p=recoverPlan(state,success,post);
            Board b=state.board;
            for(const auto& op:p.freeOps) b=replayFree(b,op);
            bool win=game::isSuccess(b);
            if(p.mode>=0) {auto result=replayDraw(b,p.mode);b=result.first;win=result.second;}
            if(win) {
                outcome="success";
                rec.emit(b,"end","程序判定成功","固定块 F 上方紧邻一个值为 128 的普通块或组合块，占用不超过 5 格。");
                break;
            }
            if(game::encodePostDraw(game::encodeBoard(b),state.q2)!=post) throw runtime_error("chosen post code mismatch");
            int q3=die(rng); randomDraws.push_back(game::SPAWN[q3]);
            uint32_t nextSid=mdp.groups[gid][q3];
            auto expectedState=game::decodeState(codes[nextSid]);
            if(expectedState.board!=b || expectedState.q1!=state.q2 || expectedState.q2!=q3)
                throw runtime_error("random successor mismatch");
            rec.q1=game::SPAWN[state.q2];rec.q2=game::SPAWN[q3];
            rec.emit(b,"preview","预览队列前移，并抽取新 q2",
                "原 q2 前移为 q1；新抽到 "+to_string(game::SPAWN[q3])+"。六种数字各 1/6。这个随机结果在操作结束后才生成。",
                false,",\"sampled\":"+to_string(game::SPAWN[q3]));
            sid=nextSid;
        }
        ofstream out(output);
        out<<"{\"target\":128,\"capacity\":5,\"seed\":20260926,\"valueIterations\":"<<snapshot.iterations
            <<",\"initialQ1\":"<<game::SPAWN[initialQ1]<<",\"initialQ2\":"<<game::SPAWN[initialQ2]
            <<",\"outcome\":"<<quote(outcome)<<",\"draws\":"<<rec.draws
            <<",\"sourcePolicy\":"<<quote(policyPath)<<",\"aggressiveness\":0.01,\"suddenDeathProbability\":"<<deathProbability<<",\"successStepExempt\":true,\"mortalitySeed\":"<<(20260926ULL ^ 0xDEADBEEFULL)<<",\"sourceTable\":"<<quote(table)<<",\"sourceValues\":"<<quote(values)
            <<",\"frames\":[";
        for(size_t i=0;i<rec.frames.size();++i) {if(i)out<<',';out<<rec.frames[i];}
        out<<"],\"randomDraws\":[";
        for(size_t i=0;i<randomDraws.size();++i){if(i)out<<',';out<<randomDraws[i];}
        out<<"]}";
        if(!out) throw runtime_error("failed writing replay");

        cout<<"outcome="<<outcome<<" draws="<<rec.draws<<" frames="<<rec.frames.size()<<"\n";
    } catch(const exception& e) {cerr<<e.what()<<'\n';return 1;}
}
#endif
