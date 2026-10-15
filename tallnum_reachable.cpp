#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <regex>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

using namespace std;

static int CAPACITY = 5;       // active physical cells, excluding F
static int TARGET = 48;
static int MAX_VALUE = 0; // Zero resolves to TARGET for legacy callers.
static bool ABOVE_ONLY = true;
static int MAX_GOAL_CELLS = 5;
// Library consumers explicitly load this from model/cache metadata. The
// generator enables it by default; old artifacts retain their old semantics.
static bool SUCCESS_NO_EXTRA_COMBOS = false;
static bool MATCH_EDGE_GUARD = false;
static bool SINGLE_EDGE_GUARD = false;
static bool SINGLE_TIDY_EXIT = false;
static int SINGLE_PROTECTED_HEAD = -1;
static int SINGLE_PROTECTED_VALUE = -1;
static bool DISABLE_EDGE = false;
static bool EXTENSION_EXIT = false;
static vector<int> BASES = {1,3,5,15};
static int INITIAL_ORDINARY = 0;
static bool KEEP_WARM_BASE = false;
static constexpr array<int,6> SPAWN = {2,4,6,8,10,15};

struct Block {
    uint16_t value = 0;
    uint8_t span = 1;       // physical cells occupied; ordinary block always 1
    bool combo = false;
    bool operator==(const Block&) const = default;
};

// blocks are stored bottom -> top, with the indivisible fixed large-number
// segment F inserted at the gap fpos (0..blocks.size()).
// Example fpos=2: [b0,b1] F [b2,b3].
struct Board {
    vector<Block> blocks;
    uint8_t fpos = 0;
    bool operator==(const Board&) const = default;
};

struct State {
    Board board;
    uint8_t q1 = 0; // index into SPAWN
    uint8_t q2 = 0;
    bool operator==(const State&) const = default;
};

static inline void hashMix(size_t& h, uint64_t x) {
    h ^= std::hash<uint64_t>{}(x) + 0x9e3779b97f4a7c15ULL + (h<<6) + (h>>2);
}

struct BoardHash {
    size_t operator()(Board const& b) const noexcept {
        size_t h = 0x12345678;
        hashMix(h, b.fpos);
        hashMix(h, b.blocks.size());
        for (auto const& x : b.blocks) {
            uint64_t z = x.value | (uint64_t(x.span) << 16) | (uint64_t(x.combo) << 24);
            hashMix(h, z);
        }
        return h;
    }
};
struct StateHash {
    size_t operator()(State const& s) const noexcept {
        size_t h = BoardHash{}(s.board);
        hashMix(h, s.q1);
        hashMix(h, s.q2);
        return h;
    }
};


// Board IDs replace fixed-width block packing so capacity is configurable.
static constexpr int BOARD_BITS = 54;
static constexpr int Q1_SHIFT = BOARD_BITS;
static constexpr int Q2_SHIFT = BOARD_BITS + 3;
static constexpr uint64_t BOARD_MASK = (1ULL << BOARD_BITS) - 1;
static vector<Board> boardRegistry;
static unordered_map<Board,uint64_t,BoardHash> boardIds;
static uint64_t encodeBoard(const Board& b) {
    if (b.fpos > b.blocks.size()) throw runtime_error("invalid F position");
    auto it=boardIds.find(b);
    if(it!=boardIds.end()) return it->second;
    uint64_t id=boardRegistry.size();
    if(id>BOARD_MASK) throw runtime_error("too many boards");
    boardRegistry.push_back(b); boardIds.emplace(b,id); return id;
}
static Board decodeBoard(uint64_t id) {
    if(id>=boardRegistry.size()) throw runtime_error("invalid board ID");
    return boardRegistry[id];
}

static uint64_t encodeState(const State& s) {
    return encodeBoard(s.board)
         | (uint64_t(s.q1) << Q1_SHIFT)
         | (uint64_t(s.q2) << Q2_SHIFT);
}

static State decodeState(uint64_t x) {
    State s;
    s.board = decodeBoard(x & BOARD_MASK);
    s.q1 = uint8_t((x >> Q1_SHIFT) & 0x7ULL);
    s.q2 = uint8_t((x >> Q2_SHIFT) & 0x7ULL);
    if (s.q1 >= SPAWN.size() || s.q2 >= SPAWN.size())
        throw runtime_error("invalid preview code");
    return s;
}

// board' + next q1, with q3 deliberately omitted.
static uint64_t encodePostDraw(uint64_t boardCode, uint8_t nextQ1) {
    return boardCode | (uint64_t(nextQ1) << Q1_SHIFT);
}

// Recover one of the six complete successor state codes.
static uint64_t addNewPreview(uint64_t postDrawCode, uint8_t q3) {
    return postDrawCode | (uint64_t(q3) << Q2_SHIFT);
}

static int usedCells(const Board& b) {
    int s = 0;
    for (auto const& x : b.blocks) s += x.span;
    return s;
}

static bool hasCombo(const Board& b) {
    for (auto const& x : b.blocks) if (x.combo) return true;
    return false;
}

static bool isAllowedOrdinary(int v) {
    if (v <= 0 || v > (MAX_VALUE ? MAX_VALUE : TARGET)) return false;
    if ((v & 1) && v != 15) return false; // preserve original odd-value rule
    while ((v & 1) == 0) v >>= 1;
    return find(BASES.begin(),BASES.end(),v)!=BASES.end();
}

static bool boardWithinModel(const Board& b) {
    if (b.fpos > b.blocks.size()) return false;
    if (usedCells(b) > CAPACITY) return false;
    if(KEEP_WARM_BASE && none_of(b.blocks.begin(),b.blocks.end(),[](const Block& x){
        return !x.combo && (x.value==INITIAL_ORDINARY || x.value==TARGET);
    }))return false;
    int combos = 0;
    for (auto const& x : b.blocks) {
        if (x.value <= 0 || x.value > (MAX_VALUE ? MAX_VALUE : TARGET)) return false;
        if (x.combo) {
            ++combos;
            if (x.span < 2 || x.span > 5) return false;
        } else {
            if (x.span != 1) return false;
            // Dealt values may remain on the board regardless of BASES.
            // Newly synthesized values are checked at their creation sites.
            if (!isAllowedOrdinary(x.value) &&
                find(SPAWN.begin(), SPAWN.end(), int(x.value)) == SPAWN.end()) return false;
        }
    }
    return combos <= 1;
}

static bool isSuccess(const Board& b) {
    // Ordinary or combination TARGET adjacent to F, within the goal span limit.
    auto acceptable = [&](size_t index) {
        auto const& goal=b.blocks[index];
        if(goal.value!=TARGET || goal.span>MAX_GOAL_CELLS)return false;
        if(EXTENSION_EXIT && goal.combo)return false;
        if(SUCCESS_NO_EXTRA_COMBOS)
            for(size_t i=0;i<b.blocks.size();++i)
                if(i!=index && b.blocks[i].combo)return false;
        if(SINGLE_TIDY_EXIT) {
            unsigned residual=0;
            for(size_t i=0;i<b.blocks.size();++i)if(i!=index) {
                const auto& x=b.blocks[i];
                if(x.combo || x.value>8 || (residual+=x.span)>1)return false;
            }
        }
        return true;
    };
    if (!ABOVE_ONLY && b.fpos > 0) {
        if (acceptable(b.fpos - 1)) return true;
    }
    if (b.fpos < b.blocks.size()) {
        if (acceptable(b.fpos)) return true;
    }
    return false;
}

static bool crossesF(const Board& b, int i, int j) {
    // interval [i,j] of block indices crosses F iff F gap is inside it.
    // F gap k lies between k-1 and k.
    return i < int(b.fpos) && int(b.fpos) <= j;
}

// Merge blocks i and i+1, known not to cross F and known equal-valued.
static bool mergePair(Board& b, int i) {
    if (i < 0 || i+1 >= (int)b.blocks.size()) return false;
    if (i+1 == b.fpos) return false; // separated by F
    if (b.blocks[i].value != b.blocks[i+1].value) return false;

    int nv = int(b.blocks[i].value) * 2;
    if (!isAllowedOrdinary(nv)) return false; // leaves our bounded model

    bool belowF = (i+1 < b.fpos);
    b.blocks[i] = Block{uint16_t(nv), 1, false};
    b.blocks.erase(b.blocks.begin() + i + 1);
    if (belowF) --b.fpos;
    return true;
}

// Ordinary automatic merge. Assumption: scan top -> bottom, and after each
// merge restart from the top so chain merges happen immediately.
static optional<Board> normalize(Board b) {
    // The real engine resolves the protected/active ordinary boundary first.
    // Two active equal blocks cannot shield an already equal anchor.
    if(SINGLE_PROTECTED_VALUE>=0 && SINGLE_PROTECTED_VALUE!=TARGET &&
       b.fpos<b.blocks.size() && b.blocks[b.fpos].value==SINGLE_PROTECTED_VALUE)
        return nullopt;
    while (true) {
        bool changed = false;
        for (int i = (int)b.blocks.size() - 2; i >= 0; --i) {
            if (i+1 == b.fpos) continue;
            if (b.blocks[i].value == b.blocks[i+1].value) {
                if (!mergePair(b, i)) return nullopt;
                changed = true;
                break;
            }
        }
        if (!changed) break;
    }
    if (!boardWithinModel(b)) return nullopt;
    if(SINGLE_PROTECTED_VALUE>=0 && b.fpos<b.blocks.size() &&
       b.blocks[b.fpos].value==SINGLE_PROTECTED_VALUE &&
       (SINGLE_PROTECTED_VALUE!=TARGET || !isSuccess(b)))return nullopt;
    return b;
}

// Right-turn rule:
//   * a one-digit value becomes an unmergeable empty value;
//   * v >= 10 temporarily becomes floor(v/10).
// We represent the empty value with valid=false rather than a numeric sentinel,
// so two one-digit blocks can never accidentally merge with each other.
struct TempValue {
    int value = 0;
    bool valid = false;
};

static TempValue rightTurnDigitMap(int v) {
    if (v < 10) return TempValue{0, false};
    return TempValue{v / 10, true};
}

struct TempBlock {
    int cur = 0;
    bool curValid = false;
    Block orig{};
    bool participated = false;
};

static optional<Board> applyRightTurn(const Board& src) {
    if(DISABLE_EDGE)return nullopt;
    // Guarded singles assume the protected anchor equals TARGET, as matches do.
    int protectedHead=SINGLE_EDGE_GUARD && SINGLE_PROTECTED_HEAD>=0 ? SINGLE_PROTECTED_HEAD : TARGET/10;
    if (SINGLE_PROTECTED_VALUE<0 && (MATCH_EDGE_GUARD || SINGLE_EDGE_GUARD) && src.fpos < src.blocks.size() &&
        protectedHead == src.blocks[src.fpos].value / 10) return nullopt;
    Board out;
    out.fpos = src.fpos;
    vector<TempBlock> t;
    t.reserve(src.blocks.size());
    for (auto const& b : src.blocks) {
        TempValue tv = rightTurnDigitMap(b.value);
        t.push_back(TempBlock{tv.value, tv.valid, b, false});
    }

    bool anyMerge = false;
    while (true) {
        bool changed = false;
        for (int i = (int)t.size() - 2; i >= 0; --i) {
            if (i+1 == out.fpos) continue;
            // One-digit blocks map to unmergeable empty values.
            if (!t[i].curValid || !t[i+1].curValid) continue;
            if (t[i].cur != t[i+1].cur) continue;

            int nv = 2 * t[i].cur;
            // A right-turn synthesis result is an ordinary 1-cell block.
            // Each subsequent EDGE comparison removes the ones digit from
            // this *new* physical value again (48 -> 4, not 48).
            TempValue next = rightTurnDigitMap(nv);
            TempBlock merged;
            merged.cur = next.value;
            merged.curValid = next.valid;
            merged.orig = Block{uint16_t(nv), 1, false};
            merged.participated = true;

            bool belowF = (i+1 < out.fpos);
            t[i] = merged;
            t.erase(t.begin() + i + 1);
            if (belowF) --out.fpos;

            anyMerge = true;
            changed = true;
            break; // restart top -> bottom
        }
        if (!changed) break;
    }

    if (!anyMerge) return nullopt; // no-op; omit from free closure
    // An explicit real boundary allows upper pairs to shield F first. Reject
    // only if the completed EDGE would actually consume that boundary.
    if(SINGLE_PROTECTED_VALUE>=0 && out.fpos<t.size() && t[out.fpos].curValid &&
       t[out.fpos].cur==SINGLE_PROTECTED_VALUE/10)return nullopt;

    out.blocks.clear();
    out.blocks.reserve(t.size());
    for (auto const& x : t) {
        if (x.participated && !isAllowedOrdinary(x.orig.value)) return nullopt;
        if (x.participated)
            out.blocks.push_back(x.orig);
        else
            out.blocks.push_back(x.orig); // untouched blocks revert
    }

    return normalize(out); // normal automatic merging after restoration
}

static optional<Board> normalizeGroupMove(Board b) {
    auto result=normalize(std::move(b));
    if(!result || !EXTENSION_EXIT || result->fpos>=result->blocks.size())return result;
    auto& goal=result->blocks[result->fpos];
    if(!goal.combo || goal.value!=TARGET)return result;
    // Only a newly created adjacent group can include the real anchor in the
    // same physical Group action. An existing group cannot be nested later.
    if(goal.span>MAX_GOAL_CELLS)return nullopt;
    goal.span=1;goal.combo=false;
    if(!isSuccess(*result))return nullopt;
    return result;
}

static vector<Board> formCombinationMoves(const Board& b) {
    vector<Board> ans;
    if (hasCombo(b)) return ans;

    const int n = (int)b.blocks.size();
    for (int l = 0; l < n; ++l) {
        int sum = 0;
        for (int r = l; r < n && r-l+1 <= 5; ++r) {
            if (b.blocks[r].span != 1 || b.blocks[r].combo) break;
            sum += b.blocks[r].value;
            int len = r-l+1;
            if (len < 2) continue;
            if (crossesF(b, l, r)) continue;
            if (sum > (MAX_VALUE ? MAX_VALUE : TARGET)) continue; // bounded-state assumption

            Board nb = b;
            bool belowF = (r < b.fpos);
            nb.blocks.erase(nb.blocks.begin()+l, nb.blocks.begin()+r+1);
            nb.blocks.insert(nb.blocks.begin()+l,
                             Block{uint16_t(sum), uint8_t(len), true});
            if (belowF) nb.fpos = uint8_t(int(nb.fpos) - (len-1));

            auto z = normalizeGroupMove(nb); // combo may immediately synthesize
            if (z) ans.push_back(std::move(*z));
        }
    }
    return ans;
}

struct Closure {
    vector<Board> boards; // non-success free-operation descendants incl. start
    bool canWinNow = false;
};

static Closure freeClosure(const Board& start) {
    Closure res;
    unordered_set<Board,BoardHash> seen;
    vector<Board> st;
    st.push_back(start);
    seen.insert(start);

    while (!st.empty()) {
        Board b = std::move(st.back());
        st.pop_back();

        if (isSuccess(b)) {
            res.canWinNow = true;
            continue;
        }
        res.boards.push_back(b);

        for (Board nb : formCombinationMoves(b)) {
            if (isSuccess(nb)) {
                res.canWinNow = true;
            } else if (seen.insert(nb).second) {
                st.push_back(std::move(nb));
            }
        }

        if (auto nb = applyRightTurn(b)) {
            if (isSuccess(*nb)) {
                res.canWinNow = true;
            } else if (seen.insert(*nb).second) {
                st.push_back(std::move(*nb));
            }
        }
    }
    return res;
}

enum class DrawMode : uint8_t { NoRotate, TopToBottom, BottomToTop };

// One cyclic rotation moves the active logical block at the corresponding end
// across the stack boundary. A combination block is one indivisible rotation
// unit even though it spans several physical cells.
//
// The fixed large-number segment F is NOT allowed to be split. Therefore:
//   * TopToBottom is illegal when F touches the top (fpos == n), because the
//     physical top cell belongs to F and moving it alone would split F.
//   * BottomToTop is illegal when F touches the bottom (fpos == 0).
//
// We never rotate F itself as a token.
static optional<Board> rotateOne(Board b, DrawMode mode) {
    const int n = (int)b.blocks.size();
    if (mode == DrawMode::NoRotate) return b;

    if (mode == DrawMode::TopToBottom) {
        if (b.fpos == n) return nullopt; // would split the fixed block

        Block x = b.blocks.back();       // combo moves as a whole if present
        b.blocks.pop_back();
        b.blocks.insert(b.blocks.begin(), x);
        ++b.fpos;
        return b;
    }

    // BottomToTop
    if (b.fpos == 0) return nullopt;     // would split the fixed block

    Block x = b.blocks.front();          // combo moves as a whole if present
    b.blocks.erase(b.blocks.begin());
    b.blocks.push_back(x);
    --b.fpos;
    return b;
}

enum class OutcomeKind : uint8_t { Next, Success, Dead, OutOfModel, Illegal };
struct DrawOutcome {
    OutcomeKind kind = OutcomeKind::Dead;
    Board board;
};

static DrawOutcome doDraw(const Board& src, DrawMode mode, int incoming) {
    auto rotated = rotateOne(src, mode);
    if (!rotated) return {OutcomeKind::Illegal,{}};
    Board b = std::move(*rotated);

    // Rotation itself can create automatic merges.
    auto r1 = normalize(b);
    if (!r1) return {OutcomeKind::OutOfModel,{}};
    b = std::move(*r1);
    // Equal matching has already consumed the produced group into the real
    // ordinary anchor. Keep a one-cell virtual goal for the post-draw check.
    if (SINGLE_PROTECTED_VALUE==TARGET && MATCH_EDGE_GUARD &&
        SINGLE_TIDY_EXIT && isSuccess(b) && b.fpos<b.blocks.size()) {
        b.blocks[b.fpos].span=1;
        b.blocks[b.fpos].combo=false;
    }
    // A strict single exit describes the completed physical action. UP/DOWN
    // always spawn the next tile after rotating, even if rotation made a goal.
    if (!SINGLE_TIDY_EXIT && isSuccess(b)) return {OutcomeKind::Success,std::move(b)};

    // Incoming number enters at the top of the full token sequence.
    // In our representation, this is appended to active block order; if F was
    // at top (fpos==old n), it remains immediately below the new block.
    b.blocks.push_back(Block{uint16_t(incoming),1,false});

    auto r2 = normalize(b);
    if (!r2) return {OutcomeKind::OutOfModel,{}};
    b = std::move(*r2);

    if (isSuccess(b)) return {OutcomeKind::Success,std::move(b)};

    // By the user's invariant, a stable living state has >=1 empty cell.
    if (usedCells(b) >= CAPACITY) return {OutcomeKind::Dead,{}};

    return {OutcomeKind::Next,std::move(b)};
}

class ReachableSearch {
public:
    // One row corresponds to one complete state code (board,q1,q2).
    // nextPostDraw contains one entry per distinct nonterminal macro action.
    // Each entry omits q3; its six stochastic successors are
    // addNewPreview(postCode, 0..5).
    struct TransitionRow {
        bool hasSuccessAction = false;
        bool hasDeadAction = false;
        vector<uint64_t> nextPostDraw;
    };

    struct StateRecord {
        uint64_t code = 0;
        TransitionRow trans;
    };

    struct Stats {
        uint64_t states = 0;
        uint64_t expanded = 0;
        uint64_t macroCacheHits = 0;
        uint64_t macroCacheMisses = 0;
        uint64_t macroBoards = 0;
        uint64_t distinctNextActions = 0;
        uint64_t stochasticEdges = 0;
        uint64_t successActions = 0;
        uint64_t deadActions = 0;
        uint64_t outOfModelActions = 0;
        uint64_t illegalActions = 0;
    } stats;
    string checkpointPath,controlPath,eventsPath;
    int checkpointSeconds=120;
    chrono::steady_clock::time_point lastCheckpoint=chrono::steady_clock::now();
    void emit(const string& type) const {
        if(eventsPath.empty()) return;
        ofstream out(filesystem::u8path(eventsPath),ios::app);
        out<<"{\"type\":\""<<type<<"\",\"stage\":\"generate\",\"states\":"<<records.size()
           <<",\"expanded\":"<<stats.expanded<<",\"queue\":"<<q.size()<<"}\n";
    }
    void saveCheckpoint() const {
        if(checkpointPath.empty()) return;
        string temp=checkpointPath+".tmp";
        ofstream out(filesystem::u8path(temp),ios::binary);
        out.write("TALLGCK5",8);
        writePod(out,uint32_t(CAPACITY));writePod(out,uint32_t(TARGET));writePod(out,uint32_t(MAX_VALUE));
        writePod(out,uint32_t(MAX_GOAL_CELLS));writePod(out,uint32_t(ABOVE_ONLY));
        writePod(out,uint32_t(SUCCESS_NO_EXTRA_COMBOS));
        writePod(out,uint32_t(MATCH_EDGE_GUARD));
        writePod(out,uint32_t(SINGLE_EDGE_GUARD));
        writePod(out,uint32_t(SINGLE_TIDY_EXIT));
        writePod(out,uint32_t(BASES.size()));for(int b:BASES)writePod(out,uint32_t(b));
        writePod(out,uint64_t(boardRegistry.size()));
        for(const auto& b:boardRegistry) {
            writePod(out,uint32_t(b.blocks.size()));writePod(out,b.fpos);
            for(const auto& z:b.blocks) {writePod(out,z.value);writePod(out,z.span);writePod(out,uint8_t(z.combo));}
        }
        writePod(out,uint64_t(records.size()));
        for(const auto& r:records) {
            writePod(out,r.code);writePod(out,uint8_t(r.trans.hasSuccessAction));
            writePod(out,uint8_t(r.trans.hasDeadAction));writePod(out,uint32_t(r.trans.nextPostDraw.size()));
            for(uint64_t x:r.trans.nextPostDraw)writePod(out,x);
        }
        writePod(out,uint64_t(q.size()));for(uint32_t x:q)writePod(out,x);
        out.write(reinterpret_cast<const char*>(&stats),sizeof(stats));
        out.close();if(!out)throw runtime_error("failed writing generator checkpoint");
        filesystem::rename(filesystem::u8path(temp),filesystem::u8path(checkpointPath));
        emit("checkpoint");
    }
    void loadCheckpoint(const string& path) {
        ifstream in(filesystem::u8path(path),ios::binary);if(!in)throw runtime_error("cannot open generator checkpoint");
        auto get=[&]<class T>() {T v{};in.read(reinterpret_cast<char*>(&v),sizeof(v));if(!in)throw runtime_error("truncated generator checkpoint");return v;};
        char magic[8];in.read(magic,8);string format(magic,8);
        if(!in||(format!="TALLGCK2"&&format!="TALLGCK3"&&format!="TALLGCK4"&&format!="TALLGCK5"))throw runtime_error("invalid generator checkpoint");
        if(get.template operator()<uint32_t>()!=uint32_t(CAPACITY)||get.template operator()<uint32_t>()!=uint32_t(TARGET)||
           get.template operator()<uint32_t>()!=uint32_t(MAX_VALUE)||
           get.template operator()<uint32_t>()!=uint32_t(MAX_GOAL_CELLS)||get.template operator()<uint32_t>()!=uint32_t(ABOVE_ONLY))throw runtime_error("generator checkpoint rules mismatch");
        bool clean=(format!="TALLGCK2") ? bool(get.template operator()<uint32_t>()) : false;
        bool guard=(format=="TALLGCK4"||format=="TALLGCK5") ? bool(get.template operator()<uint32_t>()) : false;
        bool singleGuard=format=="TALLGCK5" ? bool(get.template operator()<uint32_t>()) : false;
        bool tidy=format=="TALLGCK5" ? bool(get.template operator()<uint32_t>()) : false;
        if(singleGuard!=SINGLE_EDGE_GUARD || tidy!=SINGLE_TIDY_EXIT)
            throw runtime_error("generator checkpoint single rules mismatch");
        if(guard!=MATCH_EDGE_GUARD)throw runtime_error("generator checkpoint match EDGE rules mismatch");
        if(clean!=SUCCESS_NO_EXTRA_COMBOS || get.template operator()<uint32_t>()!=BASES.size())
            throw runtime_error("generator checkpoint success rules mismatch");
        for(int b:BASES)if(get.template operator()<uint32_t>()!=uint32_t(b))throw runtime_error("generator checkpoint bases mismatch");
        uint64_t nb=get.template operator()<uint64_t>();if(nb>UINT32_MAX)throw runtime_error("checkpoint board count out of range");
        boardRegistry.clear();boardIds.clear();boardRegistry.reserve(size_t(nb));
        for(uint64_t i=0;i<nb;++i) {
            Board b;uint32_t n=get.template operator()<uint32_t>();b.fpos=get.template operator()<uint8_t>();
            if(n>CAPACITY)throw runtime_error("invalid checkpoint board");
            for(uint32_t j=0;j<n;++j) {Block z;z.value=get.template operator()<uint16_t>();z.span=get.template operator()<uint8_t>();z.combo=get.template operator()<uint8_t>()!=0;b.blocks.push_back(z);}
            boardIds.emplace(b,i);boardRegistry.push_back(std::move(b));
        }
        uint64_t nr=get.template operator()<uint64_t>();if(nr>UINT32_MAX)throw runtime_error("checkpoint state count out of range");
        records.clear();clearStateIndex(size_t(nr));q.clear();
#ifndef TALLNUM_PAGED_STATE_RECORDS
#ifdef TALLNUM_RESUME_HEADROOM_PERCENT
        // Optional headroom avoids an immediate 2x vector allocation when a
        // large restored search discovers its first additional state.
        records.reserve(size_t(nr+nr*TALLNUM_RESUME_HEADROOM_PERCENT/100));
#else
        records.reserve(size_t(nr));
#endif
#endif
        for(uint64_t i=0;i<nr;++i) {
            StateRecord r;r.code=get.template operator()<uint64_t>();r.trans.hasSuccessAction=get.template operator()<uint8_t>()!=0;
            r.trans.hasDeadAction=get.template operator()<uint8_t>()!=0;uint32_t n=get.template operator()<uint32_t>();
            if(n>10000000)throw runtime_error("invalid checkpoint action count");
            r.trans.nextPostDraw.reserve(n);for(uint32_t j=0;j<n;++j)r.trans.nextPostDraw.push_back(get.template operator()<uint64_t>());
            records.push_back(std::move(r));insertStateIndex(records.back().code,uint32_t(i));
        }
        uint64_t nq=get.template operator()<uint64_t>();if(nq>nr)throw runtime_error("invalid checkpoint queue");
        for(uint64_t i=0;i<nq;++i) {uint32_t id=get.template operator()<uint32_t>();if(id>=nr)throw runtime_error("invalid queued state");q.push_back(id);}
        in.read(reinterpret_cast<char*>(&stats),sizeof(stats));if(!in||in.peek()!=ifstream::traits_type::eof())throw runtime_error("invalid checkpoint length");
        lastCheckpoint=chrono::steady_clock::now();emit("resumed");
    }


    uint32_t internCode(uint64_t code) {
        auto existing = findId(code);
        if (existing) return *existing;
        if(records.size() >= UINT32_MAX) throw runtime_error("too many states for 32-bit IDs");
#ifdef TALLNUM_STATE_INDEX_BITS
        if(stateIndex.empty())clearStateIndex();
        if(records.size()+1 > stateIndex.size()*4/5)growStateIndex(stateIndex.size()*2);
#endif
        uint32_t idx = uint32_t(records.size());
        records.push_back(StateRecord{code,{}});
        insertStateIndex(code, idx);
        q.push_back(idx);
        return idx;
    }

    optional<uint32_t> findId(uint64_t code) const {
#ifdef TALLNUM_STATE_INDEX_BITS
        if(stateIndex.empty())return nullopt;
        size_t slot=stateHash(code)&(stateIndex.size()-1);
        for(;;slot=(slot+1)&(stateIndex.size()-1)) {
            uint32_t id=stateIndex[slot];
            if(id==UINT32_MAX)return nullopt;
            if(records[id].code==code)return id;
        }
#else
        auto it = idByCode.find(code);
        if (it == idByCode.end()) return nullopt;
        return it->second;
#endif
    }

    const TransitionRow* findTransitions(uint64_t code) const {
        auto id = findId(code);
        if (!id) return nullptr;
        return &records[*id].trans;
    }

    void run(State initial, uint64_t maxStates = UINT64_MAX) {
        internCode(encodeState(initial));

        while (!q.empty()) {
            uint32_t sid = q.front();
            q.pop_front();
            const uint64_t scode = records[sid].code;
            State s = decodeState(scode);
            ++stats.expanded;

            const MacroResult& mr = getMacroResult(s.board, s.q1);

            TransitionRow row;
            row.hasSuccessAction = mr.hasSuccessAction;
            row.hasDeadAction = mr.hasDeadAction;
            row.nextPostDraw.reserve(mr.nextBoards.size());

            // q2 becomes the next visible q1. q3 is intentionally not stored.
            for (uint64_t nextBoard : mr.nextBoards) {
                uint64_t post = encodePostDraw(nextBoard, s.q2);
                row.nextPostDraw.push_back(post);

                // Reachability still has to insert all six q3 branches.
                for (uint8_t q3 = 0; q3 < SPAWN.size(); ++q3) {
                    internCode(addNewPreview(post, q3));
                    ++stats.stochasticEdges;
                    if (records.size() >= maxStates) {
                        records[sid].trans = std::move(row);
                        stats.states = records.size();
                        return;
                    }
                }
            }

            stats.distinctNextActions += row.nextPostDraw.size();
            records[sid].trans = std::move(row);

            if(!checkpointPath.empty() && chrono::duration_cast<chrono::seconds>(chrono::steady_clock::now()-lastCheckpoint).count()>=checkpointSeconds) {
                saveCheckpoint();lastCheckpoint=chrono::steady_clock::now();
            }
            if(!controlPath.empty() && stats.expanded%32==0) {
                ifstream control(filesystem::u8path(controlPath));string command;control>>command;
                if(command=="pause"||command=="cancel") {if(command=="pause")saveCheckpoint();emit(command);throw runtime_error("generation stopped by "+command);}
            }

            if ((stats.expanded % 100000) == 0) {
                cerr << "expanded=" << stats.expanded
                     << " discovered=" << records.size()
                     << " queue=" << q.size()
                     << " macro-cache=" << macroCache.size() << '\n';
            }
        }
        stats.states = records.size();
    }

    // Tightening success can only change rows which had a success action.
    // Legacy terminal boards were pruned, so those rows must be expanded again
    // and their newly reachable successors explored; all other rows are exact.
    void reuseTransitionTable(const string& path) {
        if(MATCH_EDGE_GUARD || SINGLE_EDGE_GUARD)throw runtime_error("EDGE guard requires fresh transitions");
        if(!SUCCESS_NO_EXTRA_COMBOS)throw runtime_error("reuse requires clean success condition");
        ifstream in(path,ios::binary);
        auto get=[&]<typename T>() {T x{};in.read(reinterpret_cast<char*>(&x),sizeof(x));
            if(!in)throw runtime_error("truncated reused table");return x;};
        array<char,8> magic{};in.read(magic.data(),8);
        if(string(magic.data(),8)!="TALLTRN4" || get.template operator()<uint32_t>()!=4 ||
           get.template operator()<uint32_t>()!=uint32_t(CAPACITY) ||
           get.template operator()<uint32_t>()!=uint32_t(TARGET))throw runtime_error("reuse table parameters mismatch");
        uint64_t count=get.template operator()<uint64_t>();
        if(count>UINT32_MAX || get.template operator()<uint32_t>()!=uint32_t(MAX_GOAL_CELLS) ||
           get.template operator()<uint32_t>()!=uint32_t(ABOVE_ONLY) ||
           get.template operator()<uint32_t>()!=BASES.size())throw runtime_error("reuse table goal parameters mismatch");
        for(int base:BASES)if(get.template operator()<uint32_t>()!=uint32_t(base))throw runtime_error("reuse bases mismatch");
        int oldMaximum=TARGET;
        ifstream model(path+".model.json");
        if(model){string data((istreambuf_iterator<char>(model)),{});smatch match;
            if(!regex_search(data,match,regex("\"maxValue\"\\s*:\\s*([0-9]+)")))throw runtime_error("reuse model metadata invalid");
            oldMaximum=stoi(match[1]);}
        if(oldMaximum!=MAX_VALUE)throw runtime_error("reuse maximum value mismatch");
        records.clear();q.clear();macroCache.clear();clearStateIndex(size_t(count));stats={};
#ifndef TALLNUM_PAGED_STATE_RECORDS
        records.reserve(size_t(count));
#endif
        uint64_t kept=0;
        for(uint64_t i=0;i<count;++i){StateRecord record;
            record.code=get.template operator()<uint64_t>();auto flags=get.template operator()<uint8_t>();
            auto n=get.template operator()<uint32_t>();
            if(flags>3 || n>10000000)throw runtime_error("invalid reused transition row");
            if(flags&1){for(uint32_t j=0;j<n;++j)(void)get.template operator()<uint64_t>();q.push_back(uint32_t(i));}
            else {record.trans.hasDeadAction=flags&2;record.trans.nextPostDraw.reserve(n);
                for(uint32_t j=0;j<n;++j)record.trans.nextPostDraw.push_back(get.template operator()<uint64_t>());
                ++kept;stats.distinctNextActions+=n;stats.stochasticEdges+=uint64_t(n)*6;}
            records.push_back(std::move(record));insertStateIndex(records.back().code,uint32_t(i));
        }
        boardRegistry.clear();boardIds.clear();auto nb=get.template operator()<uint64_t>();
        if(nb>UINT32_MAX)throw runtime_error("reuse board count invalid");
        for(uint64_t i=0;i<nb;++i){Board b;auto n=get.template operator()<uint32_t>();b.fpos=get.template operator()<uint8_t>();
            if(n>uint32_t(CAPACITY)||b.fpos>n)throw runtime_error("reuse board invalid");
            for(uint32_t j=0;j<n;++j){Block z;z.value=get.template operator()<uint16_t>();z.span=get.template operator()<uint8_t>();
                z.combo=get.template operator()<uint8_t>()!=0;b.blocks.push_back(z);}
            if(encodeBoard(b)!=i)throw runtime_error("reuse board dictionary invalid");
        }
        if(in.peek()!=ifstream::traits_type::eof())throw runtime_error("reuse table trailing bytes");
        stats.states=count;stats.expanded=kept;
        cout<<"reused transition rows = "<<kept<<"; success rows to re-expand = "<<q.size()<<endl;
        emit("reuse-loaded");
    }

    // Binary format, designed for fast reload before VI / PI.
    // For each state we save:
    //   uint64 stateCode
    //   uint8  flags: bit0=hasSuccessAction, bit1=hasDeadAction
    //   uint32 numberOfDistinctNextActions
    //   uint64 postDrawCode[numberOfDistinctNextActions]
    // q3 is never stored.
    void saveTransitionTable(const string& path) const {
        ofstream out(path, ios::binary);
        if (!out) throw runtime_error("cannot open transition table for writing");

        const array<char,8> magic = {'T','A','L','L','T','R','N','4'};
        out.write(magic.data(), magic.size());
        writePod(out, uint32_t(4));
        writePod(out, uint32_t(CAPACITY));
        writePod(out, uint32_t(TARGET));
        writePod(out, uint64_t(records.size()));
        writePod(out, uint32_t(MAX_GOAL_CELLS));
        writePod(out, uint32_t(ABOVE_ONLY));
        writePod(out, uint32_t(BASES.size()));
        for(int base:BASES) writePod(out,uint32_t(base));

        for (auto const& rec : records) {
            writePod(out, rec.code);
            uint8_t flags = uint8_t(rec.trans.hasSuccessAction)
                          | (uint8_t(rec.trans.hasDeadAction) << 1);
            writePod(out, flags);
            writePod(out, uint32_t(rec.trans.nextPostDraw.size()));
            for (uint64_t x : rec.trans.nextPostDraw) writePod(out, x);
        }
        // Board dictionary follows all rows; state codes use its dense IDs.
        writePod(out,uint64_t(boardRegistry.size()));
        for(const auto& b:boardRegistry) {
            writePod(out,uint32_t(b.blocks.size())); writePod(out,b.fpos);
            for(const auto& z:b.blocks) {
                writePod(out,z.value); writePod(out,z.span); writePod(out,uint8_t(z.combo));
            }
        }
        if (!out) throw runtime_error("failed while writing transition table");
    }

    // Dense list of all reachable state records. Lookup by encoded state is
    // available through findId()/findTransitions().
#ifdef TALLNUM_PAGED_STATE_RECORDS
    deque<StateRecord> records;
#else
    vector<StateRecord> records;
#endif

private:
    struct MacroResult {
        bool hasSuccessAction = false;
        bool hasDeadAction = false;
        vector<uint64_t> nextBoards; // q2/q3 independent
    };

    // Cache key = boardCode + q1. q2 does not affect the physical transition.
    unordered_map<uint64_t,MacroResult> macroCache;
#ifdef TALLNUM_STATE_INDEX_BITS
    // Only store IDs in the hash index; keys already live in state records.
    // Linear probing preserves insertion order and all serialized formats.
    vector<uint32_t> stateIndex;
    static uint64_t stateHash(uint64_t x) {
        x^=x>>30;x*=0xbf58476d1ce4e5b9ULL;
        x^=x>>27;x*=0x94d049bb133111ebULL;
        return x^(x>>31);
    }
    void insertStateIndex(uint64_t code,uint32_t id) {
        size_t slot=stateHash(code)&(stateIndex.size()-1);
        while(stateIndex[slot]!=UINT32_MAX)slot=(slot+1)&(stateIndex.size()-1);
        stateIndex[slot]=id;
    }
    void growStateIndex(size_t capacity) {
        stateIndex.assign(capacity,UINT32_MAX);
        for(uint32_t id=0;id<records.size();++id)insertStateIndex(records[id].code,id);
    }
    void clearStateIndex(size_t count=0) {
        size_t capacity=size_t(1)<<TALLNUM_STATE_INDEX_BITS;
        while(count>capacity*4/5)capacity*=2;
        stateIndex.assign(capacity,UINT32_MAX);
    }
#else
    unordered_map<uint64_t,uint32_t> idByCode;
    void clearStateIndex(size_t=0){idByCode.clear();}
    void insertStateIndex(uint64_t code,uint32_t id){idByCode.emplace(code,id);}
#endif
    deque<uint32_t> q;

    static uint64_t macroKey(uint64_t boardCode, uint8_t q1) {
        return boardCode | (uint64_t(q1) << Q1_SHIFT);
    }

    const MacroResult& getMacroResult(const Board& board, uint8_t q1) {
        uint64_t bc = encodeBoard(board);
        uint64_t key = macroKey(bc, q1);
#ifdef TALLNUM_MACRO_CACHE_LIMIT
        // Cached macro actions are an acceleration only. Keep their memory
        // bounded; clearing them cannot change state IDs or transitions.
        if (macroCache.size() >= TALLNUM_MACRO_CACHE_LIMIT) macroCache.clear();
#endif
        auto it = macroCache.find(key);
        if (it != macroCache.end()) {
            ++stats.macroCacheHits;
            return it->second;
        }
        ++stats.macroCacheMisses;

        MacroResult mr;
        Closure cl = freeClosure(board);
        stats.macroBoards += cl.boards.size();
        if (cl.canWinNow) {
            mr.hasSuccessAction = true;
            ++stats.successActions;
        }

        unordered_set<uint64_t> nextSet;
        for (auto const& b : cl.boards) {
            for (DrawMode mode : {DrawMode::NoRotate,
                                  DrawMode::TopToBottom,
                                  DrawMode::BottomToTop}) {
                DrawOutcome out = doDraw(b, mode, SPAWN[q1]);
                switch (out.kind) {
                    case OutcomeKind::Success:
                        mr.hasSuccessAction = true;
                        ++stats.successActions;
                        break;
                    case OutcomeKind::Dead:
                        mr.hasDeadAction = true;
                        ++stats.deadActions;
                        break;
                    case OutcomeKind::OutOfModel:
                        ++stats.outOfModelActions;
                        break;
                    case OutcomeKind::Illegal:
                        ++stats.illegalActions;
                        break;
                    case OutcomeKind::Next:
                        nextSet.insert(encodeBoard(out.board));
                        break;
                }
            }
        }

        mr.nextBoards.assign(nextSet.begin(), nextSet.end());
        sort(mr.nextBoards.begin(), mr.nextBoards.end());
        auto [jt, inserted] = macroCache.emplace(key, std::move(mr));
        return jt->second;
    }

    template<class T>
    static void writePod(ofstream& out, const T& x) {
        out.write(reinterpret_cast<const char*>(&x), sizeof(T));
    }
};

static Board makeInitialBoard() {
    // Empty active board. The indivisible fixed large-number segment F remains
    // in the stack; with no active blocks its only gap position is fpos = 0.
    Board b;
    b.fpos = 0;
    if(INITIAL_ORDINARY) b.blocks.push_back(Block{uint16_t(INITIAL_ORDINARY),1,false});
    auto z = normalize(b);
    if (!z) throw runtime_error("initial board leaves bounded model");
    return *z;
}

static int positiveInt(const string& s,int maximum,const string& name) {
    if(s.empty() || s.find_first_not_of("0123456789")!=string::npos)
        throw runtime_error(name+" must be a positive integer");
    auto v=stoull(s);
    if(v<1 || v>uint64_t(maximum)) throw runtime_error(name+" outside supported range 1.."+to_string(maximum));
    return int(v);
}
int main(int argc, char** argv) {
  try {
    SUCCESS_NO_EXTRA_COMBOS=true;
    string tablePath="tallnum_custom.bin"; bool allBases=false;
    string checkpointPath,controlPath,eventsPath,reuseTablePath;int checkpointSeconds=120;
    for(int i=1;i<argc;++i) {
        string key=argv[i];
        if(key=="--help") {
            cout<<"Usage: tallnum_reachable [--cells 5] [--target 48] [--max-value 48] [--max-goal-cells 5] "
                  "[--bases 1,3,5,15|all] [--success-side above|both] [--success-no-extra-combos 1|0] [--output tallnum_custom.bin]\n"
                  "cells: 1..255; target: 1..65535; max-goal-cells: 1..5.\n"
                  "Goal accepts ordinary blocks too. Odd ordinary values: only 15.\n";
            return 0;
        }
        if(i+1>=argc) throw runtime_error("missing value for "+key);
        string val=argv[++i];
        if(key=="--cells") CAPACITY=positiveInt(val,255,key);
        else if(key=="--target") TARGET=positiveInt(val,65535,key);
        else if(key=="--max-value") MAX_VALUE=positiveInt(val,65535,key);
        else if(key=="--initial-ordinary") INITIAL_ORDINARY=positiveInt(val,65535,key);
        else if(key=="--keep-warm-base") {
            if(val!="0" && val!="1")throw runtime_error("keep-warm-base must be 0 or 1");
            KEEP_WARM_BASE=val=="1";
        }
        else if(key=="--max-goal-cells") MAX_GOAL_CELLS=positiveInt(val,5,key);
        else if(key=="--success-no-extra-combos") {
            if(val!="0"&&val!="1")throw runtime_error("success-no-extra-combos must be0 or1");
            SUCCESS_NO_EXTRA_COMBOS=val=="1";
        }
        else if(key=="--match-edge-guard") {
            if(val!="0"&&val!="1")throw runtime_error("match-edge-guard must be 0 or 1");
            MATCH_EDGE_GUARD=val=="1";
        }
        else if(key=="--single-edge-guard" || key=="--single-tidy-exit") {
            if(val!="0"&&val!="1")throw runtime_error("single rule must be 0 or 1");
            (key=="--single-edge-guard" ? SINGLE_EDGE_GUARD : SINGLE_TIDY_EXIT)=val=="1";
        }
        else if(key=="--single-protected-head") {
            SINGLE_PROTECTED_HEAD=positiveInt(val,6553,key);
            SINGLE_EDGE_GUARD=true;
        }
        else if(key=="--single-protected-value") {
            SINGLE_PROTECTED_VALUE=positiveInt(val,65535,key);
            SINGLE_PROTECTED_HEAD=SINGLE_PROTECTED_VALUE/10;
            SINGLE_EDGE_GUARD=true;
        }
        else if(key=="--match-protected-value") {
            SINGLE_PROTECTED_VALUE=positiveInt(val,65535,key);
            SINGLE_PROTECTED_HEAD=SINGLE_PROTECTED_VALUE/10;
            MATCH_EDGE_GUARD=true;
        }
        else if(key=="--disable-edge") {
            if(val!="0" && val!="1")throw runtime_error("disable-edge must be 0 or 1");
            DISABLE_EDGE=val=="1";
        }
        else if(key=="--extension-exit") {
            if(val!="0" && val!="1")throw runtime_error("extension-exit must be 0 or 1");
            EXTENSION_EXIT=val=="1";
        }
        else if(key=="--output") { if(val.empty()) throw runtime_error("empty output path"); tablePath=val; }
        else if(key=="--reuse-table") reuseTablePath=val;
        else if(key=="--checkpoint") checkpointPath=val;
        else if(key=="--control") controlPath=val;
        else if(key=="--events") eventsPath=val;
        else if(key=="--checkpoint-seconds") checkpointSeconds=positiveInt(val,3600,key);
        else if(key=="--success-side") {
            if(val!="above" && val!="both") throw runtime_error("success-side must be above or both");
            ABOVE_ONLY=val=="above";
        } else if(key=="--bases") {
            allBases=val=="all";
            if(allBases) continue;
            BASES.clear(); size_t start=0;
            do {
                auto end=val.find(',',start);
                string token=val.substr(start,end==string::npos?end:end-start);
                int base=positiveInt(token,65535,"base");
                if(!(base&1)) throw runtime_error("bases must be odd (remove powers of two first)");
                BASES.push_back(base);
                if(end==string::npos) break;
                start=end+1;
            } while(true);
            sort(BASES.begin(),BASES.end()); BASES.erase(unique(BASES.begin(),BASES.end()),BASES.end());
        } else throw runtime_error("unknown option: "+key);
    }
    if (!MAX_VALUE) MAX_VALUE=TARGET;
    if (MAX_VALUE<TARGET) throw runtime_error("max-value must be at least target");
    if(KEEP_WARM_BASE && (!INITIAL_ORDINARY || INITIAL_ORDINARY*2!=TARGET ||
        INITIAL_ORDINARY%2 || !(INITIAL_ORDINARY/2%2) ||
        find(SPAWN.begin(),SPAWN.end(),INITIAL_ORDINARY)!=SPAWN.end() ||
        INITIAL_ORDINARY==30 || MAX_VALUE>=5*INITIAL_ORDINARY || MAX_VALUE>=2*TARGET))
        throw runtime_error("warm-base pruning requires a nonspawn minimal nonstandard half that cannot regenerate within the bound");
    if(INITIAL_ORDINARY && (!checkpointPath.empty() || !reuseTablePath.empty()))
        throw runtime_error("warm entrances require fresh transitions");
    if((SINGLE_EDGE_GUARD||SINGLE_TIDY_EXIT) &&
       ((CAPACITY!=5 && CAPACITY!=6) || (SINGLE_EDGE_GUARD && CAPACITY!=6 && SINGLE_PROTECTED_HEAD<0) ||
        (MAX_GOAL_CELLS!=1 && (!MATCH_EDGE_GUARD || SINGLE_EDGE_GUARD)) || !SUCCESS_NO_EXTRA_COMBOS))
        throw runtime_error("single rules require a clean five/six-cell single model; EDGE guard requires six cells");
    if(SINGLE_PROTECTED_HEAD>=0 && (!checkpointPath.empty() || !reuseTablePath.empty()))
        throw runtime_error("explicit boundary-head models require fresh transitions without legacy checkpoints");
    if(DISABLE_EDGE && (!checkpointPath.empty() || !reuseTablePath.empty()))
        throw runtime_error("no-EDGE models require fresh transitions without legacy checkpoints");
    if(EXTENSION_EXIT && (CAPACITY!=5 || MAX_GOAL_CELLS<2 || MAX_GOAL_CELLS>4 ||
        !SUCCESS_NO_EXTRA_COMBOS || !SINGLE_TIDY_EXIT || SINGLE_PROTECTED_VALUE<0))
        throw runtime_error("extension exits require a clean tidy five-cell model and its actual anchor");
    if(allBases) { BASES.clear(); for(int b=1;b<=MAX_VALUE;b+=2) BASES.push_back(b); }
    cout<<"cells="<<CAPACITY<<" target="<<TARGET<<" max-goal-cells="<<MAX_GOAL_CELLS
        <<" success-side="<<(ABOVE_ONLY?"above":"both")<<" success-no-extra-combos="<<SUCCESS_NO_EXTRA_COMBOS<<" bases=";
    for(int base:BASES) cout<<base<<',';
    cout<<endl;
    State init;
    init.board = makeInitialBoard();
    init.q1 = 0; // SPAWN[0] = 2
    init.q2 = 1; // SPAWN[1] = 4

    ReachableSearch rs;
    rs.checkpointPath=checkpointPath;rs.controlPath=controlPath;rs.eventsPath=eventsPath;
    rs.checkpointSeconds=checkpointSeconds;
    if(!checkpointPath.empty() && filesystem::exists(filesystem::u8path(checkpointPath))) rs.loadCheckpoint(checkpointPath);
    else if(!reuseTablePath.empty())rs.reuseTransitionTable(reuseTablePath);
    // Seed every random initial preview, not just the formerly fixed (2,4).
    if(rs.records.empty()) for (uint8_t a = 0; a < 6; ++a) for (uint8_t b = 0; b < 6; ++b) {
        State start;
        start.board = makeInitialBoard(); start.q1 = a; start.q2 = b;
        rs.internCode(encodeState(start));
    }
    rs.run(init);

    auto const& x = rs.stats;
    cout << "reachable states       = " << x.states << '\n';
    cout << "expanded states        = " << x.expanded << '\n';
    cout << "macro cache hits       = " << x.macroCacheHits << '\n';
    cout << "macro cache misses     = " << x.macroCacheMisses << '\n';
    cout << "free-closure boards    = " << x.macroBoards << '\n';
    cout << "distinct next actions  = " << x.distinctNextActions << '\n';
    cout << "stochastic edges       = " << x.stochasticEdges << '\n';
    cout << "success actions        = " << x.successActions << '\n';
    cout << "dead actions           = " << x.deadActions << '\n';
    cout << "out-of-model actions   = " << x.outOfModelActions << '\n';
    cout << "illegal rotations      = " << x.illegalActions << '\n';


    rs.saveCheckpoint();
    rs.saveTransitionTable(tablePath+".tmp");
    filesystem::rename(filesystem::u8path(tablePath+".tmp"),filesystem::u8path(tablePath));
    ofstream model(filesystem::u8path(tablePath+".model.json"));
    model << "{\"maxValue\":" << MAX_VALUE << ",\"successNoExtraCombos\":"
          <<(SUCCESS_NO_EXTRA_COMBOS?"true":"false")<<",\"matchEdgeGuard\":"
          <<(MATCH_EDGE_GUARD?"true":"false")<<",\"singleEdgeGuard\":"<<(SINGLE_EDGE_GUARD?"true":"false")
          <<",\"singleTidyExit\":"<<(SINGLE_TIDY_EXIT?"true":"false");
    if(SINGLE_PROTECTED_HEAD>=0)model<<",\"singleProtectedHead\":"<<SINGLE_PROTECTED_HEAD;
    if(SINGLE_PROTECTED_VALUE>=0)model<<",\"singleProtectedValue\":"<<SINGLE_PROTECTED_VALUE;
    if(DISABLE_EDGE)model<<",\"disableEdge\":true";
    if(EXTENSION_EXIT)model<<",\"extensionExit\":true";
    if(INITIAL_ORDINARY)model<<",\"initialOrdinary\":"<<INITIAL_ORDINARY;
    if(KEEP_WARM_BASE)model<<",\"keepWarmBase\":true";
    model<<"}\n";
    model.close(); if (!model) throw runtime_error("cannot save model bound");
    rs.emit("completed");
    cout << "transition table saved = " << tablePath << '\n';

    // Example: inspect the initial state's compressed successors.
    uint64_t initialCode = encodeState(init);
    if (auto row = rs.findTransitions(initialCode)) {
        cout << "initial state code      = " << initialCode << '\n';
        cout << "initial macro actions   = " << row->nextPostDraw.size() << '\n';
        cout << "can win immediately     = " << row->hasSuccessAction << '\n';
        for (uint64_t post : row->nextPostDraw) {
            cout << "  post-draw code = " << post << " -> ";
            for (uint8_t q3 = 0; q3 < SPAWN.size(); ++q3)
                cout << addNewPreview(post, q3) << (q3 + 1 == SPAWN.size() ? '\n' : ' ');
        }
    }
    return 0;
  } catch(const exception& e) { cerr<<e.what()<<endl; return 1; }
}
