#include "risk.h"
#include <array>
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <chrono>
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

static constexpr int BOARD_BITS = 54;
static constexpr int Q1_SHIFT = BOARD_BITS;
static constexpr int Q2_SHIFT = BOARD_BITS + 3;
static constexpr uint64_t POST_MASK = (1ULL << Q2_SHIFT) - 1ULL; // bits [0,56]
static constexpr uint32_t INVALID_ID = numeric_limits<uint32_t>::max();
static constexpr uint8_t SUCCESS_FLAG = 1u << 0;

static uint64_t fileFingerprint(const string& path) {
    ifstream in(path,ios::binary); if(!in) throw runtime_error("cannot fingerprint table");
    uint64_t h=14695981039346656037ULL; array<char,65536> buf{};
    while(in) { in.read(buf.data(),buf.size()); for(streamsize i=0;i<in.gcount();++i) { h^=uint8_t(buf[size_t(i)]);h*=1099511628211ULL; } }
    return h;
}
static void replaceFile(const string& temporary,const string& finalPath) {
    filesystem::rename(filesystem::u8path(temporary),filesystem::u8path(finalPath));
}
static void saveValues(const string& path,uint64_t completed,const vector<double>& values) {
    string temp=path+".tmp"; ofstream out(filesystem::u8path(temp),ios::binary);
    out.write("TALLAVA1",8);tallnumRisk::write(out);out.write(reinterpret_cast<const char*>(&completed),8);
    uint64_t n=values.size();out.write(reinterpret_cast<const char*>(&n),8);
    out.write(reinterpret_cast<const char*>(values.data()),streamsize(n*sizeof(double)));
    out.close();if(!out) throw runtime_error("failed writing VI values");replaceFile(temp,path);
}
static void saveCheckpoint(const string& path,uint64_t signature,uint64_t completed,const vector<double>& values) {
    string temp=path+".tmp";ofstream out(filesystem::u8path(temp),ios::binary);
    out.write("TALLACK1",8);tallnumRisk::write(out);out.write(reinterpret_cast<const char*>(&signature),8);
    out.write(reinterpret_cast<const char*>(&completed),8);uint64_t n=values.size();
    out.write(reinterpret_cast<const char*>(&n),8);
    out.write(reinterpret_cast<const char*>(values.data()),streamsize(n*sizeof(double)));
    out.close();if(!out) throw runtime_error("failed writing VI checkpoint");replaceFile(temp,path);
}


template<class T>
static T readPod(ifstream& in) {
    T x{};
    in.read(reinterpret_cast<char*>(&x), sizeof(T));
    if (!in) throw runtime_error("unexpected end of transition table");
    return x;
}

struct Header {
    uint32_t version = 0;
    uint32_t capacity = 0;
    uint32_t target = 0;
    uint64_t states = 0;
    uint32_t maxGoalCells=5, aboveOnly=1;
    vector<uint32_t> bases;
};

static Header readHeader(ifstream& in) {
    array<char,8> magic{};
    in.read(magic.data(), magic.size());
    if (!in) throw runtime_error("cannot read transition-table header");
    const array<char,8> expected = {'T','A','L','L','T','R','N','4'};
    if (magic != expected) throw runtime_error("not a TALLTRN4 table; regenerate using configurable generator");

    Header h;
    h.version = readPod<uint32_t>(in);
    h.capacity = readPod<uint32_t>(in);
    h.target = readPod<uint32_t>(in);
    h.states = readPod<uint64_t>(in);
    if (h.version != 4) throw runtime_error("unsupported transition-table version");
    if (h.states > numeric_limits<uint32_t>::max())
        throw runtime_error("too many states for 32-bit dense IDs");
    h.maxGoalCells=readPod<uint32_t>(in);
    h.aboveOnly=readPod<uint32_t>(in);
    auto count=readPod<uint32_t>(in);
    if(h.capacity<1 || h.capacity>255 || h.target<1 || h.target>65535 ||
       h.maxGoalCells<1 || h.maxGoalCells>5 || h.aboveOnly>1 || count<1 || count>32768 || h.states<36)
        throw runtime_error("invalid model configuration in table");
    for(uint32_t i=0;i<count;++i) {
        auto base=readPod<uint32_t>(in);
        if(base<1 || base>65535 || !(base&1)) throw runtime_error("invalid base in table");
        h.bases.push_back(base);
    }
    return h;
}

static uint64_t loadValues(const string& path,const Header& h,uint64_t signature,vector<double>& values,bool checkpoint) {
    ifstream in(filesystem::u8path(path),ios::binary);if(!in) throw runtime_error("cannot open initial values/checkpoint");
    array<char,8> magic{};in.read(magic.data(),8);string kind(magic.data(),8);
    if(kind!="TALLACK1" && kind!="TALLAVA1" && kind!="TALLAPA1") throw runtime_error("expected aggressiveness-aware value file");
    tallnumRisk::check(in);
    uint64_t completed=0,n=0;
    if(checkpoint) {
        if(kind!="TALLACK1" || readPod<uint64_t>(in)!=signature) throw runtime_error("VI checkpoint fingerprint mismatch");
        completed=readPod<uint64_t>(in);n=readPod<uint64_t>(in);
    } else if(kind=="TALLAVA1") {
        (void)readPod<uint64_t>(in);n=readPod<uint64_t>(in);
    } else if(kind=="TALLAPA1") {
        if(readPod<uint32_t>(in)!=4 || readPod<uint32_t>(in)!=h.capacity ||
           readPod<uint32_t>(in)!=h.target || readPod<uint64_t>(in)!=h.states ||
           readPod<uint32_t>(in)!=h.maxGoalCells || readPod<uint32_t>(in)!=h.aboveOnly ||
           readPod<uint32_t>(in)!=h.bases.size()) throw runtime_error("policy values configuration mismatch");
        for(auto b:h.bases) if(readPod<uint32_t>(in)!=b) throw runtime_error("policy values bases mismatch");
        (void)readPod<uint64_t>(in);n=h.states;
    } else throw runtime_error("unsupported initial value file");
    if(n!=values.size()) throw runtime_error("value state count mismatch");
    in.read(reinterpret_cast<char*>(values.data()),streamsize(n*sizeof(double)));
    if(!in || in.peek()!=ifstream::traits_type::eof()) throw runtime_error("truncated or excessive value file");
    for(double v:values) if(!isfinite(v)||v< -1e-9||v>1+1e-9) throw runtime_error("non-finite initial value");
    return completed;
}


// One macro action points to a group containing its six equally probable
// successors, one for each newly generated preview number q3.
using SuccessorGroup = array<uint32_t,6>;

struct Row {
    uint32_t actionBegin = 0;
    uint32_t actionCount = 0;
    uint8_t flags = 0;
};

struct LoadedMDP {
    Header header;
    uint64_t initialStateCode = 0; // first state in the BFS table
    vector<Row> rows;
    vector<uint32_t> actionGroups; // flattened group ID per nonterminal action
    vector<SuccessorGroup> groups;
};

static uint8_t q2FromStateCode(uint64_t stateCode) {
    return uint8_t((stateCode >> Q2_SHIFT) & 0x7ULL);
}

static uint64_t prefixFromStateCode(uint64_t stateCode) {
    // board + q1, i.e. exactly the format of postDrawCode
    return stateCode & POST_MASK;
}

static LoadedMDP loadMDP(const string& path) {
    LoadedMDP mdp;

    // ------------------------------------------------------------------
    // Pass 1: assign dense IDs to all states and construct, for every
    // (board,q1) prefix, the six dense IDs corresponding to q2=0..5.
    // This lets VI avoid hash lookups inside the iteration loop.
    // ------------------------------------------------------------------
    ifstream in(path, ios::binary);
    if (!in) throw runtime_error("cannot open transition table: " + path);
    mdp.header = readHeader(in);

    unordered_map<uint64_t,uint32_t> groupByPrefix;
    groupByPrefix.reserve(size_t(mdp.header.states / 4 + 1024));
    mdp.groups.reserve(size_t(mdp.header.states / 5 + 1024));

    for (uint32_t sid = 0; sid < uint32_t(mdp.header.states); ++sid) {
        uint64_t code = readPod<uint64_t>(in);
        if (sid == 0) mdp.initialStateCode = code;

        uint8_t q2 = q2FromStateCode(code);
        if (q2 >= 6) throw runtime_error("state has invalid q2 preview index");
        uint64_t prefix = prefixFromStateCode(code);

        auto [it, inserted] = groupByPrefix.emplace(prefix, uint32_t(mdp.groups.size()));
        if (inserted) {
            SuccessorGroup g;
            g.fill(INVALID_ID);
            mdp.groups.push_back(g);
        }
        uint32_t gid = it->second;
        if (mdp.groups[gid][q2] != INVALID_ID)
            throw runtime_error("duplicate state code/prefix-q2 pair in table");
        mdp.groups[gid][q2] = sid;

        (void)readPod<uint8_t>(in);      // flags
        uint32_t na = readPod<uint32_t>(in);
#ifdef TALLNUM_STREAM_TABLE_READS
        in.ignore(streamsize(na) * streamsize(sizeof(uint64_t)));
#else
#ifdef TALLNUM_STREAM_TABLE_READS
        in.ignore(streamsize(na) * streamsize(sizeof(uint64_t)));
#else
        in.seekg(streamoff(na) * streamoff(sizeof(uint64_t)), ios::cur);
#endif
#endif
        if (!in) throw runtime_error("corrupt transition table while skipping actions");
    }
    in.close();

    // ------------------------------------------------------------------
    // Pass 2: convert each stored postDrawCode to its dense successor-group
    // ID. From this point onward VI uses only uint32_t IDs.
    // ------------------------------------------------------------------
    in.open(path, ios::binary);
    if (!in) throw runtime_error("cannot reopen transition table: " + path);
    Header h2 = readHeader(in);
    if (h2.states != mdp.header.states || h2.capacity != mdp.header.capacity ||
        h2.target != mdp.header.target || h2.maxGoalCells != mdp.header.maxGoalCells ||
        h2.aboveOnly != mdp.header.aboveOnly || h2.bases != mdp.header.bases)
        throw runtime_error("transition table changed between passes");

    mdp.rows.resize(size_t(mdp.header.states));

    // A rough reserve. It grows automatically if the average action count is larger.
    mdp.actionGroups.reserve(size_t(mdp.header.states) * 4);

    for (uint32_t sid = 0; sid < uint32_t(mdp.header.states); ++sid) {
        (void)readPod<uint64_t>(in); // state code; dense ID is file order
        uint8_t flags = readPod<uint8_t>(in);
        uint32_t na = readPod<uint32_t>(in);

        if (mdp.actionGroups.size() + uint64_t(na) > numeric_limits<uint32_t>::max())
            throw runtime_error("too many actions for 32-bit flat action offsets");

        Row row;
        row.actionBegin = uint32_t(mdp.actionGroups.size());
        row.actionCount = na;
        row.flags = flags;

        for (uint32_t j = 0; j < na; ++j) {
            uint64_t post = readPod<uint64_t>(in);
            auto it = groupByPrefix.find(post);
            if (it == groupByPrefix.end())
                throw runtime_error("transition points to a successor prefix absent from reachable table");
            uint32_t gid = it->second;

            // Every stochastic macro action must have all six q3 outcomes.
            for (uint8_t q3 = 0; q3 < 6; ++q3) {
                if (mdp.groups[gid][q3] == INVALID_ID)
                    throw runtime_error("transition target is missing one or more q3 successor states");
            }
            mdp.actionGroups.push_back(gid);
        }
        mdp.rows[sid] = row;
    }
    if (!in) throw runtime_error("failed while loading transition table");

    // Hash map is no longer needed during VI.
    groupByPrefix.clear();
    groupByPrefix.rehash(0);
    return mdp;
}

// A synchronous Bellman update, with each shared six-successor average computed
// once per iteration. This is algebraically identical to the original VI.
int main(int argc, char** argv) {
    try {
        if (argc < 3) throw runtime_error("usage: tallnum_vi TABLE MAX_ROUNDS [TOLERANCE [VALUES_OUTPUT]] [--aggressiveness A --checkpoint FILE --checkpoint-seconds N --control FILE --events FILE --resume FILE --initial-values FILE]");
        string checkpointPath,controlPath,eventsPath,resumePath,initialPath;
        int positional=2; while(positional+1<argc && string(argv[positional+1]).rfind("--",0)!=0 && positional<4) ++positional;
        for(int i=positional+1;i<argc;i+=2) {
            if(i+1>=argc) throw runtime_error("missing VI option value");
            string key=argv[i],value=argv[i+1];
            if(key=="--checkpoint") checkpointPath=value;
            else if(key=="--control") controlPath=value;
            else if(key=="--events") eventsPath=value;
            else if(key=="--resume") resumePath=value;
            else if(key=="--initial-values") initialPath=value;
            else if(key=="--aggressiveness") tallnumRisk::parse(value);
            else if(key=="--checkpoint-seconds") { /* parsed below */ }
            else throw runtime_error("unknown VI option: "+key);
        }
        int checkpointSeconds=120;
        for(int i=positional+1;i<argc;i+=2) if(string(argv[i])=="--checkpoint-seconds") checkpointSeconds=stoi(argv[i+1]);
        if(checkpointSeconds<10 || checkpointSeconds>3600) throw runtime_error("checkpoint interval outside 10..3600 seconds");
        if(!resumePath.empty() && !initialPath.empty()) throw runtime_error("choose resume or initial values");
        double tolerance=1e-13;
        if(positional>=3) {
            size_t used=0; string arg=argv[3]; tolerance=stod(arg,&used);
            if(used!=arg.size() || !isfinite(tolerance) || tolerance<=0 || tolerance>=1)
                throw runtime_error("tolerance must be finite and in (0,1)");
        }
        string path=argv[1];
        string rounds=argv[2];
        if(rounds.empty() || rounds.find_first_not_of("0123456789")!=string::npos) throw runtime_error("rounds must be a positive integer");
        uint64_t limit=stoull(rounds);
        if(limit==0 || limit==UINT64_MAX) throw runtime_error("rounds outside supported range");
        auto mdp=loadMDP(path);
        tallnumRisk::configure(mdp.header.target);
        ifstream file(path,ios::binary); readHeader(file);
        // The weighted generator interns all 36 empty-board states first.
        for(uint32_t i=0;i<36;++i) {
            uint64_t code=readPod<uint64_t>(file);
            uint64_t expected=(uint64_t(i/6)<<Q1_SHIFT)|(uint64_t(i%6)<<Q2_SHIFT);
            if(code!=expected) throw runtime_error("table missing ordered 36 initial states");
            readPod<uint8_t>(file);auto actions=readPod<uint32_t>(file);
            file.seekg(streamoff(actions)*8,ios::cur);
        }
        vector<double> value(mdp.rows.size(),0), next(value.size(),0), means(mdp.groups.size(),0);
        auto weighted=[&](){double sum=0;for(size_t i=0;i<36;++i)sum+=value[i];return sum/36;};
        double delta=1;uint64_t completed=0;
        uint64_t signature=0;
        if(!checkpointPath.empty() || !resumePath.empty()) signature=fileFingerprint(path);
        if(!resumePath.empty()) completed=loadValues(resumePath,mdp.header,signature,value,true);
        else if(!initialPath.empty()) loadValues(initialPath,mdp.header,0,value,false);
        auto lastCheckpoint=chrono::steady_clock::now();
        auto emit=[&](const string& kind){ if(eventsPath.empty())return;ofstream out(filesystem::u8path(eventsPath),ios::app);
            out<<setprecision(17)<<"{\"type\":\""<<kind<<"\",\"stage\":\"vi\",\"iteration\":"<<completed
               <<",\"states\":"<<mdp.header.states<<",\"aggressiveness\":"<<tallnumRisk::aggressiveness<<",\"sudden_death_probability\":"<<tallnumRisk::deathProbability<<",\"success_step_exempt\":true,\"weighted\":"<<weighted()<<",\"delta\":"<<delta<<"}\n"; };
        cout<<fixed<<setprecision(15)<<"states="<<mdp.header.states<<" groups="<<mdp.groups.size()<<endl;
        emit("started");
        for(uint64_t it=completed+1;it<=limit;++it) {
            for(size_t j=0;j<mdp.groups.size();++j) {
                const auto& g=mdp.groups[j];
                means[j]=(value[g[0]]+value[g[1]]+value[g[2]]+value[g[3]]+value[g[4]]+value[g[5]])*(tallnumRisk::survival/6.0);
            }
            delta=0;
            for(size_t i=0;i<mdp.rows.size();++i) {
                const auto& r=mdp.rows[i];double best=0;
                if(r.flags&SUCCESS_FLAG)best=1;
                else for(uint32_t j=r.actionBegin;j<r.actionBegin+r.actionCount;++j)
                    best=max(best,means[mdp.actionGroups[j]]);
                next[i]=best;delta=max(delta,abs(best-value[i]));
            }
            value.swap(next);completed=it;
            if(it%500==0 || it==limit || delta<=tolerance)
                cout<<"iteration="<<it<<" weighted="<<weighted()<<" delta="<<delta<<endl;
            if(it%100==0 || it==limit || delta<=tolerance) emit("progress");
            if(!checkpointPath.empty() && chrono::duration_cast<chrono::seconds>(chrono::steady_clock::now()-lastCheckpoint).count()>=checkpointSeconds) {
                saveCheckpoint(checkpointPath,signature,completed,value);lastCheckpoint=chrono::steady_clock::now();emit("checkpoint");
            }
            if(!controlPath.empty() && it%5==0) {
                ifstream control(filesystem::u8path(controlPath));string command;control>>command;
                if(command=="pause" || command=="cancel") {
                    if(command=="pause" && !checkpointPath.empty()) saveCheckpoint(checkpointPath,signature,completed,value);
                    emit(command);return 3;
                }
            }
            if(delta<=tolerance)break;
        }
        if(positional>=4) saveValues(argv[4],completed,value);
        if(!checkpointPath.empty()) {saveCheckpoint(checkpointPath,signature,completed,value);emit("checkpoint");}
        ofstream csv(path+".initial.csv");csv<<"q1,q2,weight,value\n"<<setprecision(17);
        const array<int,6> spawn={2,4,6,8,10,15};
        for(size_t i=0;i<36;++i)csv<<spawn[i/6]<<','<<spawn[i%6]<<','<<1.0/36<<','<<value[i]<<'\n';
        if(!csv) throw runtime_error("failed to write initial CSV");
        ofstream result(path+".result.json");
        result<<"{\"cells\":"<<mdp.header.capacity<<",\"max_goal_cells\":"<<mdp.header.maxGoalCells
              <<",\"above_only\":"<<mdp.header.aboveOnly<<",\"ordinary_goal_allowed\":true,\"bases\":[";
        for(size_t i=0;i<mdp.header.bases.size();++i) { if(i) result<<','; result<<mdp.header.bases[i]; }
        result<<"],";
        result<<setprecision(17)<<"\"target\":"<<mdp.header.target
            <<",\"states\":"<<mdp.header.states<<",\"iterations\":"<<completed
            <<",\"aggressiveness\":"<<tallnumRisk::aggressiveness<<",\"sudden_death_probability\":"<<tallnumRisk::deathProbability<<",\"success_step_exempt\":true,\"weighted\":"<<weighted()<<",\"max_delta\":"<<delta
            <<",\"fixed_2_4\":"<<value[1]<<",\"tolerance\":"<<tolerance<<"}";
        if(!result) throw runtime_error("failed to write result JSON");
        cout<<"FINAL weighted="<<weighted()<<" fixed_2_4="<<value[1]<<endl;
        emit("completed");
        return 0;
    }catch(const exception& e){cerr<<e.what()<<endl;return 1;}
}
