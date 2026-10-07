#include "risk.h"
#ifndef TALLNUM_CORE_ONLY
#include <petscksp.h>
#endif
#include <cmath>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using namespace std;

// Compatible with tallnum_reachable.cpp / tallnum_vi.cpp.
static constexpr int BOARD_BITS = 54;
static constexpr int Q1_SHIFT = BOARD_BITS;
static constexpr int Q2_SHIFT = BOARD_BITS + 3;
static constexpr uint64_t POST_MASK = (1ULL << Q2_SHIFT) - 1ULL; // board + q1

static constexpr uint8_t SUCCESS_FLAG = 1u << 0;
static constexpr uint8_t DEAD_FLAG    = 1u << 1;
static constexpr uint32_t INVALID_ID = numeric_limits<uint32_t>::max();

// Policy file values. A normal value is the LOCAL action index in the row's
// postDrawCode array [0, actionCount). The two values below choose one of the
// compressed terminal-action classes stored in the transition table.
static constexpr uint32_t POLICY_SUCCESS = 0xFFFFFFFFu;
static constexpr uint32_t POLICY_DEAD    = 0xFFFFFFFEu;

template<class T>
static T readPod(ifstream& in) {
    T x{};
    in.read(reinterpret_cast<char*>(&x), sizeof(T));
    if (!in) throw runtime_error("unexpected end of file");
    return x;
}

template<class T>
static void writePod(ofstream& out, const T& x) {
    out.write(reinterpret_cast<const char*>(&x), sizeof(T));
    if (!out) throw runtime_error("failed while writing file");
}

struct TransitionHeader {
    uint32_t version = 0;
    uint32_t capacity = 0;
    uint32_t target = 0;
    uint64_t states = 0;
    uint32_t maxGoalCells=5, aboveOnly=1;
    vector<uint32_t> bases;
    uint64_t signature=14695981039346656037ULL;
};

static TransitionHeader readTransitionHeader(ifstream& in) {
    array<char,8> magic{};
    in.read(magic.data(), magic.size());
    const array<char,8> expected = {'T','A','L','L','T','R','N','4'};
    if (!in || magic != expected) throw runtime_error("not a TALLTRN4 transition table");

    TransitionHeader h;
    h.version  = readPod<uint32_t>(in);
    h.capacity = readPod<uint32_t>(in);
    h.target   = readPod<uint32_t>(in);
    h.states   = readPod<uint64_t>(in);
    if (h.version != 4) throw runtime_error("unsupported transition-table version");
    if (h.states > numeric_limits<uint32_t>::max())
        throw runtime_error("more than 2^32-1 states are not supported by this evaluator");
    h.maxGoalCells=readPod<uint32_t>(in); h.aboveOnly=readPod<uint32_t>(in);
    uint32_t count=readPod<uint32_t>(in);
    if(h.capacity<1 || h.capacity>255 || h.target<1 || h.target>65535 ||
       h.maxGoalCells<1 || h.maxGoalCells>5 || h.aboveOnly>1 || count<1 || count>32768 || h.states<36)
        throw runtime_error("invalid v4 model configuration");
    for(uint32_t i=0;i<count;++i) {
        auto base=readPod<uint32_t>(in);
        if(base<1 || base>65535 || !(base&1)) throw runtime_error("invalid base");
        h.bases.push_back(base);
    }
    return h;
}

static uint8_t q2FromStateCode(uint64_t code) {
    return uint8_t((code >> Q2_SHIFT) & 0x7ULL);
}

static uint64_t prefixFromStateCode(uint64_t code) {
    return code & POST_MASK;
}

using SuccessorGroup = array<uint32_t,6>;

// Pass 1 index. We exploit the fact that postDrawCode is exactly the
// (board,next-q1) prefix of six complete states differing only in q2/q3.
struct StateIndex {
    TransitionHeader header;
    uint64_t initialStateCode = 0;
    vector<SuccessorGroup> groups;
    unordered_map<uint64_t,uint32_t> groupByPrefix;
};

static StateIndex buildStateIndex(const string& tablePath) {
    ifstream in(tablePath, ios::binary);
    if (!in) throw runtime_error("cannot open transition table: " + tablePath);

    StateIndex idx;
    idx.header = readTransitionHeader(in);
    const uint32_t n = uint32_t(idx.header.states);

    // There are normally close to N/6 distinct (board,q1) prefixes.
    idx.groupByPrefix.reserve(size_t(n / 4 + 1024));
    idx.groups.reserve(size_t(n / 5 + 1024));

    for (uint32_t sid = 0; sid < n; ++sid) {
        const uint64_t code = readPod<uint64_t>(in);
        if (sid == 0) idx.initialStateCode = code;
        if(sid<36 && code!=((uint64_t(sid/6)<<Q1_SHIFT)|(uint64_t(sid%6)<<Q2_SHIFT)))
            throw runtime_error("v4 table must start with all 36 empty-board preview states");
        auto mix=[&](uint64_t x) { for(int k=0;k<8;++k) { idx.header.signature^=(x&255); idx.header.signature*=1099511628211ULL; x>>=8; } };
        mix(code);

        const uint8_t q2 = q2FromStateCode(code);
        if (q2 >= 6) throw runtime_error("invalid q2 in state code");
        const uint64_t prefix = prefixFromStateCode(code);

        auto [it, inserted] = idx.groupByPrefix.emplace(prefix, uint32_t(idx.groups.size()));
        if (inserted) {
            SuccessorGroup g;
            g.fill(INVALID_ID);
            idx.groups.push_back(g);
        }
        auto& g = idx.groups[it->second];
        if (g[q2] != INVALID_ID) throw runtime_error("duplicate state prefix/q2 pair");
        g[q2] = sid;

        uint8_t flags=readPod<uint8_t>(in);
        if(flags&~3u) throw runtime_error("invalid transition flags");
        const uint32_t na = readPod<uint32_t>(in);
        mix(flags); mix(na);
        for(uint32_t a=0;a<na;++a) mix(readPod<uint64_t>(in));
        if (!in) throw runtime_error("corrupt transition table");
    }

    return idx;
}

struct ValueFile {
    uint32_t capacity = 0;
    uint32_t target = 0;
    uint64_t iterations = 0;
    vector<double> value;
    bool policyValues=false;
};

static void checkIdentity(ifstream& in,const TransitionHeader& h);
static ValueFile loadVIValues(const string& path, const TransitionHeader& header,bool approximate=false) {
    ifstream in(path,ios::binary);
    if(!in) throw runtime_error("cannot open value snapshot: "+path);
    array<char,8> magic{}; in.read(magic.data(),8);
    if(!in) throw runtime_error("missing value header");
    ValueFile vf; uint64_t n=header.states;
    if(string(magic.data(),8)=="TALLAVA1") {
        tallnumRisk::check(in);
        vf.iterations=readPod<uint64_t>(in); n=readPod<uint64_t>(in);
        if(n!=header.states) throw runtime_error("value snapshot state count differs from table");
    } else if(string(magic.data(),8)=="TALLAPA1") {
        checkIdentity(in,header); vf.policyValues=true;
    } else throw runtime_error("expected TALLAVA1 or TALLAPA1 values");
    vf.value.resize(size_t(n));
    in.read(reinterpret_cast<char*>(vf.value.data()),streamsize(n*sizeof(double)));
    if(!in || in.peek()!=ifstream::traits_type::eof()) throw runtime_error("invalid snapshot length");
    double slack=vf.policyValues?1e-9:0;
    for(double v:vf.value) if(!isfinite(v) || (!approximate && (v < -slack || v > 1+slack))) throw runtime_error("invalid probability in value file");
    return vf;
}

static void writeIdentity(ofstream& out,const TransitionHeader& h) {
    tallnumRisk::write(out);
    writePod(out,uint32_t(4)); writePod(out,h.capacity); writePod(out,h.target); writePod(out,h.states);
    writePod(out,h.maxGoalCells); writePod(out,h.aboveOnly); writePod(out,uint32_t(h.bases.size()));
    for(auto b:h.bases) writePod(out,b);
    writePod(out,h.signature);
}
static void checkIdentity(ifstream& in,const TransitionHeader& h) {
    tallnumRisk::check(in);
    if(readPod<uint32_t>(in)!=4 || readPod<uint32_t>(in)!=h.capacity ||
       readPod<uint32_t>(in)!=h.target || readPod<uint64_t>(in)!=h.states ||
       readPod<uint32_t>(in)!=h.maxGoalCells || readPod<uint32_t>(in)!=h.aboveOnly)
        throw runtime_error("policy configuration mismatch");
    if(readPod<uint32_t>(in)!=h.bases.size()) throw runtime_error("policy base-list mismatch");
    for(auto b:h.bases) if(readPod<uint32_t>(in)!=b) throw runtime_error("policy base-list mismatch");
    if(readPod<uint64_t>(in)!=h.signature) throw runtime_error("policy transition fingerprint mismatch");
}

static vector<uint32_t> loadPolicyFile(const string& path, const TransitionHeader& h) {
    ifstream in(path, ios::binary);
    if (!in) throw runtime_error("cannot open policy file: " + path);

    array<char,8> magic{};
    in.read(magic.data(), magic.size());
    const array<char,8> expected = {'T','A','L','L','A','P','O','1'};
    if (!in || magic != expected) throw runtime_error("not a TALLAPO1 policy file");

    checkIdentity(in,h);
    const uint64_t states=h.states;
    vector<uint32_t> policy(static_cast<size_t>(states));
    in.read(reinterpret_cast<char*>(policy.data()), streamsize(states * sizeof(uint32_t)));
    if (!in) throw runtime_error("truncated policy file");
    return policy;
}

static void savePolicyFile(const string& path,
                           const TransitionHeader& h,
                           const vector<uint32_t>& policy) {
    ofstream out(path, ios::binary);
    if (!out) throw runtime_error("cannot create policy file: " + path);
    const array<char,8> magic = {'T','A','L','L','A','P','O','1'};
    out.write(magic.data(), magic.size());
    writeIdentity(out,h);
    out.write(reinterpret_cast<const char*>(policy.data()),
              streamsize(policy.size() * sizeof(uint32_t)));
    if (!out) throw runtime_error("failed while saving policy");
}

// Resolve a postDrawCode into the six dense full-state IDs.
static const SuccessorGroup& resolveGroup(const StateIndex& idx, uint64_t post) {
    auto it = idx.groupByPrefix.find(post);
    if (it == idx.groupByPrefix.end())
        throw runtime_error("transition points to a prefix absent from reachable-state table");
    const auto& group=idx.groups[it->second];
    for(auto sid:group) if(sid==INVALID_ID) throw runtime_error("incomplete successor group");
    return group;
}

// Derive a deterministic greedy policy from a previously saved VI value vector.
// Terminal success always wins. Otherwise we maximize the mean of the six q3
// successors. A dead action (Q=0) is only selected if there is no nonterminal
// action, or if all alternatives are numerically negative (which reachability
// values should never be).
static vector<uint32_t> deriveGreedyPolicy(const string& tablePath,
                                           const StateIndex& idx,
                                           const vector<double>& V,
                                           const vector<uint32_t>& previous = {}) {
    ifstream in(tablePath, ios::binary);
    if (!in) throw runtime_error("cannot reopen transition table");
    const auto h = readTransitionHeader(in);
    const uint32_t n = uint32_t(h.states);

    vector<uint32_t> policy(n, POLICY_DEAD);
    for (uint32_t sid = 0; sid < n; ++sid) {
        (void)readPod<uint64_t>(in);
        const uint8_t flags = readPod<uint8_t>(in);
        const uint32_t na = readPod<uint32_t>(in);

        if (flags & SUCCESS_FLAG) {
            policy[sid] = POLICY_SUCCESS;
            in.seekg(streamoff(na) * streamoff(sizeof(uint64_t)), ios::cur);
            continue;
        }

        double oldScore=0;
        if(!previous.empty() && previous[sid]!=POLICY_DEAD && previous[sid]>=na)
            throw runtime_error("previous policy action out of range");
        double best = -numeric_limits<double>::infinity();
        uint32_t bestAction = POLICY_DEAD;
        for (uint32_t a = 0; a < na; ++a) {
            const uint64_t post = readPod<uint64_t>(in);
            const auto& g = resolveGroup(idx, post);
            double q = 0.0;
            for (uint32_t t : g) q += V[t];
            q *= tallnumRisk::survival / 6.0;
            if(!previous.empty() && previous[sid]==a) oldScore=q;
            if (q > best) {
                best = q;
                bestAction = a;
            }
        }
        if(!previous.empty() && best <= oldScore+1e-12) policy[sid]=previous[sid];
        else if (bestAction != POLICY_DEAD) policy[sid] = bestAction;
        else if ((flags & DEAD_FLAG) || na==0) policy[sid] = POLICY_DEAD;
        else throw runtime_error("state has no selectable action");
    }
    return policy;
}

// Build a first policy directly from the transition graph. Distance is the
// smallest number of selected actions along any positive-probability path to
// an immediate success. This is a reachability heuristic, not a VI result.
static vector<uint32_t> deriveAutomaticPolicy(const string& tablePath,const StateIndex& idx) {
    const uint32_t n=uint32_t(idx.header.states);
    constexpr uint16_t FAR=UINT16_MAX;
    vector<uint16_t> distance(n,FAR);
    bool changed=true;uint32_t sweep=0;
    while(changed) {
        changed=false;++sweep;
        ifstream in(tablePath,ios::binary);(void)readTransitionHeader(in);
        for(uint32_t s=0;s<n;++s) {
            (void)readPod<uint64_t>(in);uint8_t flags=readPod<uint8_t>(in);uint32_t na=readPod<uint32_t>(in);
            uint16_t best=(flags&SUCCESS_FLAG)?0:distance[s];
            for(uint32_t a=0;a<na;++a) {
                const auto& g=resolveGroup(idx,readPod<uint64_t>(in));
                for(uint32_t t:g) if(distance[t]!=FAR && distance[t]<FAR-1) best=min(best,uint16_t(distance[t]+1));
            }
            if(best<distance[s]) {distance[s]=best;changed=true;}
        }
        if(!in)throw runtime_error("failed scanning table for automatic policy");
        cout<<"auto policy distance sweep="<<sweep<<" changed="<<changed<<'\n';
        if(sweep>=255 && changed) throw runtime_error("automatic policy distance did not settle in 255 sweeps");
    }
    uint64_t unreachable=count(distance.begin(),distance.end(),FAR);
    cout<<"auto policy unreachable states="<<unreachable<<'\n';
    vector<uint32_t> policy(n,POLICY_DEAD);
    ifstream in(tablePath,ios::binary);(void)readTransitionHeader(in);
    for(uint32_t s=0;s<n;++s) {
        (void)readPod<uint64_t>(in);uint8_t flags=readPod<uint8_t>(in);uint32_t na=readPod<uint32_t>(in);
        double best=-1;uint32_t choice=POLICY_DEAD;
        for(uint32_t a=0;a<na;++a) {
            const auto& g=resolveGroup(idx,readPod<uint64_t>(in));double score=0;
            bool descending=false;
            for(uint32_t t:g) if(distance[t]!=FAR) {
                score+=1.0/(1.0+distance[t]);
                descending|=distance[t]<distance[s];
            }
            if(distance[s]!=FAR && !descending)continue;
            if(score>best) {best=score;choice=a;}
        }
        if(flags&SUCCESS_FLAG)policy[s]=POLICY_SUCCESS;
        else if(choice!=POLICY_DEAD)policy[s]=choice;
        else if(na>0 && distance[s]!=FAR)throw runtime_error("automatic policy lost a descending action");
    }
    if(!in)throw runtime_error("failed selecting automatic policy");
    return policy;
}

// Under a fixed policy, keep only one selected action per full state.
struct FixedPolicyGraph {
    TransitionHeader header;
    uint64_t initialStateCode = 0;
    vector<uint8_t> kind;                  // 0=normal, 1=success, 2=dead
    vector<SuccessorGroup> next;           // meaningful only for normal rows
};

static FixedPolicyGraph buildFixedPolicyGraph(const string& tablePath,
                                              const StateIndex& idx,
                                              const vector<uint32_t>& policy) {
    ifstream in(tablePath, ios::binary);
    if (!in) throw runtime_error("cannot reopen transition table");
    FixedPolicyGraph g;
    g.header = readTransitionHeader(in);
    g.header.signature=idx.header.signature;
    g.initialStateCode = idx.initialStateCode;
    const uint32_t n = uint32_t(g.header.states);
    if (policy.size() != n) throw runtime_error("policy size mismatch");

    g.kind.assign(n, 2);
    g.next.resize(n);
    for (auto& x : g.next) x.fill(INVALID_ID);

    for (uint32_t sid = 0; sid < n; ++sid) {
        (void)readPod<uint64_t>(in);
        const uint8_t flags = readPod<uint8_t>(in);
        const uint32_t na = readPod<uint32_t>(in);
        const uint32_t choice = policy[sid];

        if (choice == POLICY_SUCCESS) {
            if (!(flags & SUCCESS_FLAG)) throw runtime_error("policy selects nonexistent success action");
            g.kind[sid] = 1;
            in.seekg(streamoff(na) * streamoff(sizeof(uint64_t)), ios::cur);
        } else if (choice == POLICY_DEAD) {
            if (!(flags & DEAD_FLAG) && na!=0) throw runtime_error("policy selects nonexistent dead action");
            g.kind[sid] = 2;
            in.seekg(streamoff(na) * streamoff(sizeof(uint64_t)), ios::cur);
        } else {
            if (choice >= na) throw runtime_error("policy action index out of range at state " + to_string(sid));
            // Jump to the chosen postDrawCode, resolve it, then skip the rest.
            if (choice > 0) in.seekg(streamoff(choice) * streamoff(sizeof(uint64_t)), ios::cur);
            const uint64_t post = readPod<uint64_t>(in);
            g.kind[sid] = 0;
            g.next[sid] = resolveGroup(idx, post);
            const uint32_t after = na - choice - 1;
            if (after) in.seekg(streamoff(after) * streamoff(sizeof(uint64_t)), ios::cur);
        }
        if (!in) throw runtime_error("corrupt transition table while applying policy");
    }
    return g;
}

// Reverse reachability from policy-success states. Because every stored edge has
// probability 1/6 > 0, a state has V^pi > 0 iff a success state is reachable.
static vector<uint8_t> positiveReachability(const FixedPolicyGraph& g) {
    const uint32_t n = uint32_t(g.header.states);
    vector<uint64_t> indeg(n, 0);
    uint64_t edges = 0;
    for (uint32_t s = 0; s < n; ++s) {
        if (g.kind[s] != 0) continue;
        for (uint32_t t : g.next[s]) {
            ++indeg[t];
            ++edges;
        }
    }

    vector<uint64_t> off(size_t(n) + 1, 0);
    for (uint32_t i = 0; i < n; ++i) off[size_t(i) + 1] = off[i] + indeg[i];
    vector<uint32_t> rev(static_cast<size_t>(edges));
    vector<uint64_t> cur = off;
    for (uint32_t s = 0; s < n; ++s) {
        if (g.kind[s] != 0) continue;
        for (uint32_t t : g.next[s]) rev[size_t(cur[t]++)] = s;
    }

    vector<uint8_t> positive(n, 0);
    deque<uint32_t> q;
    for (uint32_t s = 0; s < n; ++s) {
        if (g.kind[s] == 1) {
            positive[s] = 1;
            q.push_back(s);
        }
    }
    while (!q.empty()) {
        uint32_t t = q.front();
        q.pop_front();
        for (uint64_t p = off[t]; p < off[size_t(t) + 1]; ++p) {
            uint32_t s = rev[size_t(p)];
            if (!positive[s]) {
                positive[s] = 1;
                q.push_back(s);
            }
        }
    }
    return positive;
}

// Unknowns exclude both boundary classes:
//   V=0 states (cannot reach success under this policy)
//   V=1 states (policy chooses immediate success)
// Remaining states are positive nonterminal states; some can still have value 1.
struct ReducedSystem {
    vector<int32_t> unknownId;               // full state -> unknown ID or -1
    vector<uint32_t> fullOfUnknown;          // unknown ID -> full state
    vector<SuccessorGroup> nextUnknown;      // INVALID_ID for boundary successors
    vector<double> rhs;                      // success-boundary contribution
    int32_t initialUnknown = -1;
    double initialBoundaryValue = -1.0;      // 0/1 if initial state is boundary
};

static ReducedSystem reduceSystem(const FixedPolicyGraph& g,
                                  const vector<uint8_t>& positive) {
    const uint32_t n = uint32_t(g.header.states);
    ReducedSystem r;
    r.unknownId.assign(n, -1);

    for (uint32_t s = 0; s < n; ++s) {
        if (positive[s] && g.kind[s] == 0) {
            if(r.fullOfUnknown.size()>=size_t(INT32_MAX)) throw runtime_error("too many reduced unknowns");
            r.unknownId[s] = int32_t(r.fullOfUnknown.size());
            r.fullOfUnknown.push_back(s);
        }
    }

    const uint32_t m = uint32_t(r.fullOfUnknown.size());
    r.nextUnknown.resize(m);
    r.rhs.assign(m, 0.0);

    for (uint32_t i = 0; i < m; ++i) {
        const uint32_t s = r.fullOfUnknown[i];
        SuccessorGroup z;
        z.fill(INVALID_ID);
        unsigned successCount = 0;
        for (int k = 0; k < 6; ++k) {
            const uint32_t t = g.next[s][k];
            if (g.kind[t] == 1) {
                ++successCount;
            } else if (positive[t] && g.kind[t] == 0) {
                const int32_t j = r.unknownId[t];
                if (j < 0) throw runtime_error("internal reduction inconsistency");
                z[k] = uint32_t(j);
            }
            // zero-value states contribute nothing.
        }
        r.nextUnknown[i] = z;
        r.rhs[i] = tallnumRisk::survival * double(successCount) / 6.0;
    }

    // File order is BFS order and state 0 is the initial state.
    const uint32_t init = 0;
    if (!positive[init]) r.initialBoundaryValue = 0.0;
    else if (g.kind[init] == 1) r.initialBoundaryValue = 1.0;
    else r.initialUnknown = r.unknownId[init];
    return r;
}

#ifndef TALLNUM_CORE_ONLY
// Matrix-free A = I-Q on the reduced unknown set.
struct ShellCtx {
    const ReducedSystem* sys = nullptr;
};

static PetscErrorCode TallnumMatMult(Mat A, Vec x, Vec y) {
    PetscFunctionBeginUser;
    ShellCtx* ctx = nullptr;
    PetscCall(MatShellGetContext(A, &ctx));
    const auto& next = ctx->sys->nextUnknown;

    const PetscScalar* xa = nullptr;
    PetscScalar* ya = nullptr;
    PetscCall(VecGetArrayRead(x, &xa));
    PetscCall(VecGetArray(y, &ya));
    const PetscInt n = PetscInt(next.size());

    #ifdef _OPENMP
    #pragma omp parallel for schedule(static)
    #endif
    for (PetscInt i = 0; i < n; ++i) {
        PetscScalar v = xa[i];
        const auto& g = next[size_t(i)];
        for (uint32_t j : g) {
            if (j != INVALID_ID) v -= xa[j] * (PetscScalar(tallnumRisk::survival) / PetscScalar(6.0));
        }
        ya[i] = v;
    }

    PetscCall(VecRestoreArrayRead(x, &xa));
    PetscCall(VecRestoreArray(y, &ya));
    PetscFunctionReturn(PETSC_SUCCESS);
}

// Enables -pc_type jacobi with MATSHELL. The diagonal is
// 1 - (# self-transition outcomes)/6.
static PetscErrorCode TallnumGetDiagonal(Mat A, Vec d) {
    PetscFunctionBeginUser;
    ShellCtx* ctx = nullptr;
    PetscCall(MatShellGetContext(A, &ctx));
    const auto& next = ctx->sys->nextUnknown;
    PetscScalar* da = nullptr;
    PetscCall(VecGetArray(d, &da));
    const PetscInt n = PetscInt(next.size());

    #ifdef _OPENMP
    #pragma omp parallel for schedule(static)
    #endif
    for (PetscInt i = 0; i < n; ++i) {
        unsigned selfCount = 0;
        for (uint32_t j : next[size_t(i)]) if (j == uint32_t(i)) ++selfCount;
        da[i] = PetscScalar(1.0 - tallnumRisk::survival * double(selfCount) / 6.0);
    }
    PetscCall(VecRestoreArray(d, &da));
    PetscFunctionReturn(PETSC_SUCCESS);
}

static Mat createShellMatrix(const ReducedSystem& sys) {
    Mat A = nullptr;
    auto* ctx = new ShellCtx{&sys};
    const PetscInt n = PetscInt(sys.nextUnknown.size());
    PetscCallAbort(PETSC_COMM_SELF,
        MatCreateShell(PETSC_COMM_SELF, n, n, n, n, ctx, &A));
    PetscCallAbort(PETSC_COMM_SELF,
        MatShellSetOperation(A, MATOP_MULT, (void(*)(void))TallnumMatMult));
    PetscCallAbort(PETSC_COMM_SELF,
        MatShellSetOperation(A, MATOP_GET_DIAGONAL, (void(*)(void))TallnumGetDiagonal));
    return A;
}

static Mat createExplicitMatrix(const ReducedSystem& sys) {
    const PetscInt n = PetscInt(sys.nextUnknown.size());
    Mat A = nullptr;
    // At most 7 structural entries per row before duplicate merging.
    PetscCallAbort(PETSC_COMM_SELF, MatCreateSeqAIJ(PETSC_COMM_SELF, n, n, 7, nullptr, &A));

    for (PetscInt i = 0; i < n; ++i) {
        PetscCallAbort(PETSC_COMM_SELF, MatSetValue(A, i, i, 1.0, ADD_VALUES));
        for (uint32_t j : sys.nextUnknown[size_t(i)]) {
            if (j != INVALID_ID)
                PetscCallAbort(PETSC_COMM_SELF,
                    MatSetValue(A, i, PetscInt(j), -tallnumRisk::survival/6.0, ADD_VALUES));
        }
    }
    PetscCallAbort(PETSC_COMM_SELF, MatAssemblyBegin(A, MAT_FINAL_ASSEMBLY));
    PetscCallAbort(PETSC_COMM_SELF, MatAssemblyEnd(A, MAT_FINAL_ASSEMBLY));
    return A;
}

static void saveFullValues(const string& path,
                           const FixedPolicyGraph& g,
                           const vector<uint8_t>& positive,
                           const ReducedSystem& r,
                           Vec x) {
    const uint32_t n = uint32_t(g.header.states);
    vector<double> full(n, 0.0);
    for (uint32_t s = 0; s < n; ++s) if (g.kind[s] == 1) full[s] = 1.0;

    const PetscScalar* xa = nullptr;
    PetscCallAbort(PETSC_COMM_SELF, VecGetArrayRead(x, &xa));
    for (uint32_t i = 0; i < r.fullOfUnknown.size(); ++i)
        full[r.fullOfUnknown[i]] = PetscRealPart(xa[i]);
    PetscCallAbort(PETSC_COMM_SELF, VecRestoreArrayRead(x, &xa));

    ofstream out(path, ios::binary);
    if (!out) throw runtime_error("cannot create policy-value file: " + path);
    const array<char,8> magic = {'T','A','L','L','A','P','A','1'};
    out.write(magic.data(), magic.size());
    writeIdentity(out,g.header);
    out.write(reinterpret_cast<const char*>(full.data()), streamsize(full.size()*sizeof(double)));
    if (!out) throw runtime_error("failed while saving policy values");
}

struct KspCheckpointContext {
    const FixedPolicyGraph* graph;
    const vector<uint8_t>* positive;
    const ReducedSystem* system;
    string checkpointPath,controlPath,eventsPath;
    int seconds=120;
    chrono::steady_clock::time_point last=chrono::steady_clock::now();
};
static void emitPetscEvent(const string& path,const string& type,PetscInt iteration,double residual,uint64_t states) {
    if(path.empty())return;
    ofstream out(filesystem::u8path(path),ios::app);
    out<<setprecision(17)<<"{\"type\":\""<<type<<"\",\"stage\":\"petsc\",\"iteration\":"<<iteration
       <<",\"residual\":"<<residual<<",\"states\":"<<states<<"}\n";
}
static PetscErrorCode tallnumKspMonitor(KSP ksp,PetscInt it,PetscReal rnorm,void* pointer) {
    PetscFunctionBeginUser;
    auto& c=*static_cast<KspCheckpointContext*>(pointer);
    bool due=!c.checkpointPath.empty() && chrono::duration_cast<chrono::seconds>(chrono::steady_clock::now()-c.last).count()>=c.seconds;
    string command;
    if(!c.controlPath.empty()) {ifstream in(filesystem::u8path(c.controlPath));in>>command;}
    if(it>0 && (due || command=="pause") && !c.checkpointPath.empty()) {
        Vec approximation=nullptr;PetscCall(KSPBuildSolution(ksp,nullptr,&approximation));
        string temp=c.checkpointPath+".tmp";
        saveFullValues(temp,*c.graph,*c.positive,*c.system,approximation);
        filesystem::rename(filesystem::u8path(temp),filesystem::u8path(c.checkpointPath));
        c.last=chrono::steady_clock::now();
        cout<<"KSP checkpoint iteration="<<it<<" residual="<<rnorm<<'\n';
        emitPetscEvent(c.eventsPath,"checkpoint",it,rnorm,c.graph->header.states);
    }
    if(it%25==0) emitPetscEvent(c.eventsPath,"progress",it,rnorm,c.graph->header.states);
    if(command=="pause" || command=="cancel") PetscFunctionReturn(PETSC_ERR_USER);
    PetscFunctionReturn(PETSC_SUCCESS);
}

static double stateValue(uint32_t s,const FixedPolicyGraph& g,const ReducedSystem& r,const PetscScalar* xa) {
    if(g.kind[s]==1) return 1;
    int32_t j=r.unknownId[s]; return j<0?0:PetscRealPart(xa[j]);
}
static void reportResult(const string& path,const FixedPolicyGraph& g,const ReducedSystem& r,
                         Vec x,int reason,uint64_t iterations,double kspResidual) {
    const PetscScalar* xa=nullptr;
    PetscCallAbort(PETSC_COMM_SELF,VecGetArrayRead(x,&xa));
    double weighted=0,residual=0,minValue=1,maxValue=0;
    for(uint32_t s=0;s<36;++s) weighted+=stateValue(s,g,r,xa)/36.0;
    for(uint32_t s=0;s<g.header.states;++s) {
        double v=stateValue(s,g,r,xa),q=0;
        if(!isfinite(v)) throw runtime_error("non-finite policy solution");
        minValue=min(minValue,v); maxValue=max(maxValue,v);
        if(g.kind[s]==1) q=1;
        else if(g.kind[s]==0) for(auto t:g.next[s]) q+=tallnumRisk::survival*stateValue(t,g,r,xa)/6.0;
        residual=max(residual,abs(v-q));
    }
    PetscCallAbort(PETSC_COMM_SELF,VecRestoreArrayRead(x,&xa));
    cout<<setprecision(17)<<"weighted policy value   = "<<weighted<<'\n'
        <<"true policy residual inf= "<<residual<<'\n'
        <<"solution min/max        = "<<minValue<<" / "<<maxValue<<'\n';
    ofstream out(path); if(!out) throw runtime_error("cannot write result JSON: "+path);
    out<<setprecision(17)<<"{\"target\":"<<g.header.target<<",\"cells\":"<<g.header.capacity
       <<",\"max_goal_cells\":"<<g.header.maxGoalCells<<",\"above_only\":"<<g.header.aboveOnly
       <<",\"states\":"<<g.header.states<<",\"unknowns\":"<<r.fullOfUnknown.size()
       <<",\"input_aggressiveness\":"<<tallnumRisk::inputAggressiveness<<",\"aggressiveness\":"<<tallnumRisk::aggressiveness<<",\"sudden_death_probability\":"<<tallnumRisk::deathProbability<<",\"success_step_exempt\":true,\"weighted_policy_value\":"<<weighted<<",\"ksp_reason\":"<<reason
       <<",\"converged\":"<<(reason>0?"true":"false")<<",\"iterations\":"<<iterations
       <<",\"reported_residual\":"<<kspResidual<<",\"true_residual_inf\":"<<residual
       <<",\"min_value\":"<<minValue<<",\"max_value\":"<<maxValue
       <<",\"global_optimality_certified\":false,\"bases\":[";
    for(size_t i=0;i<g.header.bases.size();++i) {if(i)out<<',';out<<g.header.bases[i];} out<<"]}";
    if(!out) throw runtime_error("failed writing result JSON");
}

static string getStringOption(const char* name, const string& fallback = "") {
    char buf[PETSC_MAX_PATH_LEN]{};
    PetscBool set = PETSC_FALSE;
    PetscCallAbort(PETSC_COMM_SELF,
        PetscOptionsGetString(nullptr, nullptr, name, buf, sizeof(buf), &set));
    return set ? string(buf) : fallback;
}

int main(int argc, char** argv) {
    PetscCall(PetscInitialize(&argc, &argv, nullptr,
        "Tallnum fixed-policy reachability evaluator\n"
        "Application options:\n"
        "  -tallnum_input_aggressiveness <A> explicit risk of input policy/values when changing objective\n"
        "  -tallnum_aggressiveness <A>    sudden death = A * 7.5 / target; success exempt\n"
        "  -tallnum_table <file>          transition table (default tallnum_transitions.bin)\n"
        "  -tallnum_policy <file>         fixed TALLAPO1 policy\n"
        "  -tallnum_values <file>         derive greedy policy from TALLAVA1/TALLAPA1 values\n"
        "  -tallnum_save_policy <file>    save derived/loaded policy\n"
        "  -tallnum_save_values <file>    save fixed-policy floating-point values (TALLAPA1)\n"
        "  -tallnum_explicit_matrix       build SeqAIJ instead of MatShell (allows ILU, etc.)\n"
        "Useful PETSc options:\n"
        "  -ksp_type gmres|dgmres|fgmres -ksp_rtol 1e-12 -ksp_max_it 10000 -ksp_monitor\n"
        "  -ksp_gmres_restart 100\n"
        "  -ksp_dgmres_eigen 20 -ksp_dgmres_max_eigen 100\n"
        "  -pc_type jacobi                cheap matrix-free default\n"
        "  with -tallnum_explicit_matrix: -pc_type ilu (or other installed PCs)\n"));

    cout<<unitbuf;
    int result = 0;
    try {
        PetscMPIInt mpiSize = 1;
        PetscCall(MPI_Comm_size(PETSC_COMM_WORLD, &mpiSize));
        if (mpiSize != 1)
            throw runtime_error("this first implementation is single-process; run without mpiexec or with -n 1");

        const string tablePath = getStringOption("-tallnum_table", "tallnum_transitions.bin");
        const string policyPath = getStringOption("-tallnum_policy");
        const string valuesPath = getStringOption("-tallnum_values");
        const string previousPath = getStringOption("-tallnum_previous_policy");
        PetscBool autoPolicy=PETSC_FALSE;
        PetscCall(PetscOptionsGetBool(nullptr,nullptr,"-tallnum_auto_policy",&autoPolicy,nullptr));
        if(!previousPath.empty() && valuesPath.empty()) throw runtime_error("previous policy requires -tallnum_values");
        const string savePolicyPath = getStringOption("-tallnum_save_policy");
        const string saveValuesPath = getStringOption("-tallnum_save_values");
        const string resultPath=getStringOption("-tallnum_result",tablePath+".policy.result.json");
        const string resumeValuesPath=getStringOption("-tallnum_resume_values");
        const string checkpointPath=getStringOption("-tallnum_checkpoint");
        const string controlPath=getStringOption("-tallnum_control");
        const string eventsPath=getStringOption("-tallnum_events");
        PetscInt checkpointSeconds=120;
        PetscCall(PetscOptionsGetInt(nullptr,nullptr,"-tallnum_checkpoint_seconds",&checkpointSeconds,nullptr));
        if(checkpointSeconds<10 || checkpointSeconds>3600) throw runtime_error("checkpoint seconds outside 10..3600");

        PetscBool explicitMatrix = PETSC_FALSE;
        PetscCall(PetscOptionsGetBool(nullptr, nullptr, "-tallnum_explicit_matrix", &explicitMatrix, nullptr));

        if (!policyPath.empty() && !valuesPath.empty())
            throw runtime_error("specify only one of -tallnum_policy and -tallnum_values");
        if (policyPath.empty() && valuesPath.empty() && !autoPolicy)
            throw runtime_error("provide -tallnum_policy, -tallnum_values, or -tallnum_auto_policy");
        if(autoPolicy && (!policyPath.empty()||!valuesPath.empty()))
            throw runtime_error("automatic policy cannot be combined with saved policy or values");
        if(!resumeValuesPath.empty() && policyPath.empty()) throw runtime_error("KSP resume requires saved fixed policy");

        cout << "building state prefix index...\n";
        StateIndex idx = buildStateIndex(tablePath);
        tallnumRisk::parse(getStringOption("-tallnum_aggressiveness", "0"));
        tallnumRisk::configure(idx.header.target);
        const string inputRisk=getStringOption("-tallnum_input_aggressiveness");
        if(!inputRisk.empty()) {
            size_t used=0; double a=stod(inputRisk,&used);
            if(used!=inputRisk.size() || !isfinite(a) || a<0 || a>double(idx.header.target)/7.5)
                throw runtime_error("invalid input aggressiveness");
            tallnumRisk::inputAggressiveness=a;
            cout<<"explicit input aggressiveness = "<<a<<"; evaluation aggressiveness = "<<tallnumRisk::aggressiveness<<'\n';
        }
        cout << "states                 = " << idx.header.states << '\n';
        emitPetscEvent(eventsPath,"started",0,0,idx.header.states);
        cout << "prefix groups          = " << idx.groups.size() << '\n';
        cout << "capacity               = " << idx.header.capacity << '\n';
        cout << "target                 = " << idx.header.target << '\n';

        vector<double> warmStart;
        vector<uint32_t> policy;
        if(autoPolicy) {
            cout<<"constructing automatic graph policy...\n";
            policy=deriveAutomaticPolicy(tablePath,idx);
        } else if (!policyPath.empty()) {
            cout << "loading policy          = " << policyPath << '\n';
            policy = loadPolicyFile(policyPath, idx.header);
        } else {
            cout << "loading VI values       = " << valuesPath << '\n';
            ValueFile vf = loadVIValues(valuesPath, idx.header);
            if(!vf.policyValues) cout<<"TALLAVA1 stores state count only; use the matching original table.\n";
            if(!vf.policyValues) cout << "VI iterations used      = " << vf.iterations << '\n';
            cout << "deriving greedy policy...\n";
            vector<uint32_t> previous;
            if(!previousPath.empty()) previous=loadPolicyFile(previousPath,idx.header);
            policy = deriveGreedyPolicy(tablePath, idx, vf.value,previous);
            if(!previous.empty()) {
                size_t changed=0; for(size_t i=0;i<policy.size();++i) changed+=(policy[i]!=previous[i]);
                cout<<"policy actions changed  = "<<changed<<'\n';
            }
            warmStart=std::move(vf.value);
        }
        if(!resumeValuesPath.empty()) warmStart=loadVIValues(resumeValuesPath,idx.header,true).value;
        if (!savePolicyPath.empty()) {
            savePolicyFile(savePolicyPath, idx.header, policy);
            cout << "policy saved            = " << savePolicyPath << '\n';
        }

        cout << "resolving selected transitions...\n";
        FixedPolicyGraph graph = buildFixedPolicyGraph(tablePath, idx, policy);
        // The prefix hash is no longer needed and can be a large allocation.
        idx.groupByPrefix.clear(); idx.groupByPrefix.rehash(0);
        vector<SuccessorGroup>().swap(idx.groups);
        vector<uint32_t>().swap(policy);

        uint64_t nSuccess = 0, nDead = 0, nNormal = 0;
        for (uint8_t k : graph.kind) {
            nSuccess += (k == 1);
            nDead    += (k == 2);
            nNormal  += (k == 0);
        }
        cout << "policy normal states    = " << nNormal << '\n';
        cout << "policy success states   = " << nSuccess << '\n';
        cout << "policy dead states      = " << nDead << '\n';

        cout << "reverse-searching V>0 states...\n";
        vector<uint8_t> positive = positiveReachability(graph);
        const uint64_t positiveCount = count(positive.begin(), positive.end(), uint8_t(1));
        cout << "positive-value states   = " << positiveCount << '\n';
        cout << "zero-value states       = " << (graph.header.states - positiveCount) << '\n';

        cout << "building reduced system...\n";
        ReducedSystem sys = reduceSystem(graph, positive);
        const PetscInt m = PetscInt(sys.fullOfUnknown.size());
        cout << "linear unknowns         = " << m << '\n';

        if (m == 0) {
            Vec dummy=nullptr; PetscCall(VecCreateSeq(PETSC_COMM_SELF,0,&dummy));
            reportResult(resultPath,graph,sys,dummy,1,0,0);
            if(!saveValuesPath.empty()) saveFullValues(saveValuesPath,graph,positive,sys,dummy);
            PetscCall(VecDestroy(&dummy)); PetscCall(PetscFinalize()); return 0;
        }

        Mat A = explicitMatrix ? createExplicitMatrix(sys) : createShellMatrix(sys);
        Vec b = nullptr, x = nullptr;
        PetscCall(VecCreateSeq(PETSC_COMM_SELF, m, &b));
        PetscCall(VecDuplicate(b, &x));
        PetscScalar* ba = nullptr;
        PetscCall(VecGetArray(b, &ba));
        for (PetscInt i = 0; i < m; ++i) ba[i] = PetscScalar(sys.rhs[size_t(i)]);
        PetscCall(VecRestoreArray(b, &ba));
        PetscCall(VecSet(x, 0.0));
        if(!warmStart.empty()) {
            PetscScalar* xa=nullptr; PetscCall(VecGetArray(x,&xa));
            for(PetscInt i=0;i<m;++i) xa[i]=warmStart[sys.fullOfUnknown[size_t(i)]];
            PetscCall(VecRestoreArray(x,&xa));
        }

        KSP ksp = nullptr;
        PetscCall(KSPCreate(PETSC_COMM_SELF, &ksp));
        PetscCall(KSPSetOperators(ksp, A, A));
        PetscCall(KSPSetType(ksp, KSPGMRES));
        PetscCall(KSPSetTolerances(ksp, 1e-12, PETSC_DEFAULT, PETSC_DEFAULT, 10000));
        PC pc = nullptr;
        PetscCall(KSPGetPC(ksp, &pc));
        PetscCall(PCSetType(pc, explicitMatrix ? PCILU : PCJACOBI));
        // User options override the defaults above, e.g. -ksp_type dgmres.
        if(!warmStart.empty()) PetscCall(KSPSetInitialGuessNonzero(ksp,PETSC_TRUE));
        vector<double>().swap(warmStart);
        PetscCall(KSPSetFromOptions(ksp));
        KspCheckpointContext checkpointContext{&graph,&positive,&sys,checkpointPath,controlPath,eventsPath,int(checkpointSeconds)};
        if(!checkpointPath.empty() || !controlPath.empty() || !eventsPath.empty()) PetscCall(KSPMonitorSet(ksp,tallnumKspMonitor,&checkpointContext,nullptr));

        if(!checkpointPath.empty()) {
            string temp=checkpointPath+".tmp";saveFullValues(temp,graph,positive,sys,x);
            filesystem::rename(filesystem::u8path(temp),filesystem::u8path(checkpointPath));
            emitPetscEvent(eventsPath,"checkpoint",0,0,graph.header.states);
        }

        cout << "solving (I-Q)V=b...\n";
        PetscCall(KSPSolve(ksp, b, x));

        KSPConvergedReason reason;
        PetscInt its = 0;
        PetscReal rnorm = 0.0;
        PetscCall(KSPGetConvergedReason(ksp, &reason));
        PetscCall(KSPGetIterationNumber(ksp, &its));
        PetscCall(KSPGetResidualNorm(ksp, &rnorm));

        double initialValue = sys.initialBoundaryValue;
        if (sys.initialUnknown >= 0) {
            const PetscScalar* xa = nullptr;
            PetscCall(VecGetArrayRead(x, &xa));
            initialValue = PetscRealPart(xa[sys.initialUnknown]);
            PetscCall(VecRestoreArrayRead(x, &xa));
        }

        cout << fixed << setprecision(15);
        cout << "KSP reason              = " << int(reason) << '\n';
        cout << "KSP iterations          = " << its << '\n';
        cout << "reported residual norm  = " << rnorm << '\n';
        cout << "initial policy value    = " << initialValue << '\n';

        reportResult(resultPath,graph,sys,x,int(reason),uint64_t(its),double(rnorm));
        if(reason<=0) { cerr<<"KSP did not converge; result is diagnostic only\n"; result=2; }
        if (!saveValuesPath.empty()) {
            saveFullValues(saveValuesPath, graph, positive, sys, x);
            cout << "policy values saved     = " << saveValuesPath << '\n';
        }
        if(!checkpointPath.empty()) {
            string temp=checkpointPath+".tmp";saveFullValues(temp,graph,positive,sys,x);
            filesystem::rename(filesystem::u8path(temp),filesystem::u8path(checkpointPath));
        }
        emitPetscEvent(eventsPath,reason>0?"completed":"diagnostic",its,rnorm,graph.header.states);

        // MatShell context was allocated with new; PETSc does not own it unless
        // MATOP_DESTROY is supplied. Retrieve and delete it explicitly.
        if (!explicitMatrix) {
            ShellCtx* ctx = nullptr;
            PetscCall(MatShellGetContext(A, &ctx));
            delete ctx;
        }
        PetscCall(KSPDestroy(&ksp));
        PetscCall(VecDestroy(&x));
        PetscCall(VecDestroy(&b));
        PetscCall(MatDestroy(&A));
    } catch (const exception& e) {
        cerr << "error: " << e.what() << '\n';
        result = 1;
    }

    PetscCall(PetscFinalize());
    return result;
}

#endif // TALLNUM_CORE_ONLY
