// Reuse the checked macro-action recovery and the original board dictionary.
#define TALLNUM_REPLAY_LIBRARY
#include "../export_replay_128_a001_no_death.cpp"
#include <regex>
#ifndef TALLNUM_POLICY_MAX_CAPACITY
#define TALLNUM_POLICY_MAX_CAPACITY 5
#endif
#ifndef TALLNUM_POLICY_MIN_CAPACITY
#define TALLNUM_POLICY_MIN_CAPACITY 5
#endif

struct PolicyService {
    static bool validBases(const vector<uint32_t>& bases) {
        return !bases.empty() && bases.size()<=32768 && is_sorted(bases.begin(),bases.end()) &&
               adjacent_find(bases.begin(),bases.end())==bases.end() &&
               all_of(bases.begin(),bases.end(),[](uint32_t b){return b>0 && b<=65535 && (b&1);});
    }
    solver::LoadedMDP mdp;
    vector<uint64_t> codes;
    vector<pair<uint64_t,uint32_t>> byCode;
    vector<uint64_t> chosenPost;
    vector<uint32_t> policy;
    uint64_t signature=14695981039346656037ULL;
    double aggression=0;
    string exitKind;

    // Compact query cache has sorted state codes, chosen successors and the
    // original board dictionary; no all-action MDP is loaded during play.
    PolicyService(const string& cache,const string& kind):exitKind(kind){
        if(kind!="single" && kind!="match" && kind!="extend")throw runtime_error("invalid exit");
        ifstream in(cache,ios::binary);array<char,8> magic{};in.read(magic.data(),8);
        bool legacy=string(magic.data(),8)=="TNQUERY1";
        bool strictCache=string(magic.data(),8)=="TNQUERY5";
        bool guardedCache=strictCache||string(magic.data(),8)=="TNQUERY4";
        bool cleanCache=guardedCache||string(magic.data(),8)=="TNQUERY3";
        if(!legacy&&!cleanCache&&string(magic.data(),8)!="TNQUERY2")throw runtime_error("bad query cache");
        auto& h=mdp.header;
        h.version=4;h.capacity=solver::readPod<uint32_t>(in);h.target=solver::readPod<uint32_t>(in);
        game::MAX_VALUE=legacy ? h.target : solver::readPod<uint32_t>(in);
        game::SUCCESS_NO_EXTRA_COMBOS=cleanCache ? bool(solver::readPod<uint32_t>(in)) : false;
        game::MATCH_EDGE_GUARD=guardedCache ? bool(solver::readPod<uint32_t>(in)) : false;
        game::SINGLE_EDGE_GUARD=strictCache ? bool(solver::readPod<uint32_t>(in)) : false;
        game::SINGLE_TIDY_EXIT=strictCache ? bool(solver::readPod<uint32_t>(in)) : false;
        if(game::MATCH_EDGE_GUARD && kind!="match")throw runtime_error("match EDGE guard requires match exit");
        h.maxGoalCells=solver::readPod<uint32_t>(in);h.aboveOnly=solver::readPod<uint32_t>(in);
        auto count=solver::readPod<uint32_t>(in);if(count>32768)throw runtime_error("bad bases");
        for(uint32_t i=0;i<count;++i)h.bases.push_back(solver::readPod<uint32_t>(in));
        h.states=solver::readPod<uint64_t>(in);signature=solver::readPod<uint64_t>(in);
        if(h.capacity<TALLNUM_POLICY_MIN_CAPACITY||h.capacity>TALLNUM_POLICY_MAX_CAPACITY||game::MAX_VALUE<int(h.target)||game::MAX_VALUE>65535||!h.aboveOnly||h.states>0xffffffffu||!validBases(h.bases)||
           (kind=="single"&&h.maxGoalCells!=1)||(kind=="extend"&&h.maxGoalCells>4))throw runtime_error("query rules mismatch");
        codes.resize(h.states);chosenPost.resize(h.states);policy.resize(h.states);
        in.read(reinterpret_cast<char*>(codes.data()),streamsize(h.states*8));
        in.read(reinterpret_cast<char*>(chosenPost.data()),streamsize(h.states*8));
        in.read(reinterpret_cast<char*>(policy.data()),streamsize(h.states*4));
        if(!is_sorted(codes.begin(),codes.end()))throw runtime_error("unsorted query cache");
        game::CAPACITY=h.capacity;game::TARGET=h.target;game::MAX_GOAL_CELLS=h.maxGoalCells;
        game::ABOVE_ONLY=true;game::BASES.assign(h.bases.begin(),h.bases.end());
        game::boardRegistry.clear();game::boardIds.clear();
        auto boards=solver::readPod<uint64_t>(in);
        for(uint64_t i=0;i<boards;++i){Board b;auto n=solver::readPod<uint32_t>(in);b.fpos=solver::readPod<uint8_t>(in);
            if(n>h.capacity||b.fpos>n)throw runtime_error("invalid cached board");
            for(uint32_t j=0;j<n;++j){Block x;x.value=solver::readPod<uint16_t>(in);x.span=solver::readPod<uint8_t>(in);x.combo=solver::readPod<uint8_t>(in)!=0;b.blocks.push_back(x);}
            if(game::encodeBoard(b)!=i)throw runtime_error("cache dictionary mismatch");}
        if(!in||in.peek()!=ifstream::traits_type::eof())throw runtime_error("invalid cache size");
    }

    uint64_t identity(ifstream& in) {
        const auto& h=mdp.header;
        if(solver::readPod<uint32_t>(in)!=4 || solver::readPod<uint32_t>(in)!=h.capacity ||
           solver::readPod<uint32_t>(in)!=h.target || solver::readPod<uint64_t>(in)!=h.states ||
           solver::readPod<uint32_t>(in)!=h.maxGoalCells || solver::readPod<uint32_t>(in)!=h.aboveOnly ||
           solver::readPod<uint32_t>(in)!=h.bases.size()) throw runtime_error("policy rules mismatch");
        for(auto b:h.bases) if(solver::readPod<uint32_t>(in)!=b) throw runtime_error("policy bases mismatch");
        return solver::readPod<uint64_t>(in);
    }
    PolicyService(const string& table,const string& input,const string& kind):exitKind(kind) {
        if(kind!="single" && kind!="match" && kind!="extend") throw runtime_error("invalid exit");
        mdp=solver::loadMDP(table);
        const auto& h=mdp.header;
        if(h.capacity<TALLNUM_POLICY_MIN_CAPACITY || h.capacity>TALLNUM_POLICY_MAX_CAPACITY || !h.aboveOnly || !validBases(h.bases))
            throw runtime_error("requires five-cell above-only table with valid odd bases");
        if((kind=="single" && h.maxGoalCells!=1) || (kind=="extend" && h.maxGoalCells>4))
            throw runtime_error("table goal span incompatible with exit");
        game::CAPACITY=h.capacity; game::TARGET=h.target; game::MAX_GOAL_CELLS=h.maxGoalCells;
        game::MAX_VALUE=h.target;
        game::SUCCESS_NO_EXTRA_COMBOS=false;
        game::MATCH_EDGE_GUARD=false;
        game::SINGLE_EDGE_GUARD=false;game::SINGLE_TIDY_EXIT=false;
        ifstream model(table+".model.json");
        if(model) {
            string data((istreambuf_iterator<char>(model)),istreambuf_iterator<char>());
            smatch match;
            if(!regex_search(data,match,regex("\\\"maxValue\\\"\\s*:\\s*([0-9]+)"))) throw runtime_error("invalid model bound metadata");
            game::MAX_VALUE=stoi(match[1]);
            if(game::MAX_VALUE<int(h.target)||game::MAX_VALUE>65535)throw runtime_error("invalid model bound");
            if(data.find("successNoExtraCombos")!=string::npos){
                if(!regex_search(data,match,regex("\\\"successNoExtraCombos\\\"\\s*:\\s*(true|false)")))
                    throw runtime_error("invalid success condition metadata");
                game::SUCCESS_NO_EXTRA_COMBOS=match[1]=="true";
            }
        }
        {
            ifstream guardModel(table+".model.json");
            string data((istreambuf_iterator<char>(guardModel)),istreambuf_iterator<char>());
            if(data.find("matchEdgeGuard")!=string::npos){
                smatch match;
                if(!regex_search(data,match,regex(R"("matchEdgeGuard"\s*:\s*(true|false))")))
                    throw runtime_error("invalid match EDGE guard metadata");
                game::MATCH_EDGE_GUARD=match[1]=="true";
            }
            smatch m;
            if(regex_search(data,m,regex(R"("singleEdgeGuard"\s*:\s*(true|false))")))game::SINGLE_EDGE_GUARD=m[1]=="true";
            if(regex_search(data,m,regex(R"("singleTidyExit"\s*:\s*(true|false))")))game::SINGLE_TIDY_EXIT=m[1]=="true";
        }
        if(game::MATCH_EDGE_GUARD && kind!="match")throw runtime_error("match EDGE guard requires match exit");
        game::ABOVE_ONLY=h.aboveOnly; game::BASES.assign(h.bases.begin(),h.bases.end());
        game::boardRegistry.clear();game::boardIds.clear();
        ifstream in(table,ios::binary);solver::readHeader(in);
        auto mix=[&](uint64_t x){for(int k=0;k<8;++k){signature^=x&255;signature*=1099511628211ULL;x>>=8;}};
        for(uint32_t i=0;i<h.states;++i){
            auto code=solver::readPod<uint64_t>(in);codes.push_back(code);byCode.emplace_back(code,i);mix(code);
            mix(solver::readPod<uint8_t>(in));auto n=solver::readPod<uint32_t>(in);mix(n);
            for(uint32_t j=0;j<n;++j)mix(solver::readPod<uint64_t>(in));
        }
        auto boards=solver::readPod<uint64_t>(in);
        for(uint64_t id=0;id<boards;++id){
            Board b;auto n=solver::readPod<uint32_t>(in);b.fpos=solver::readPod<uint8_t>(in);
            for(uint32_t j=0;j<n;++j){Block x;x.value=solver::readPod<uint16_t>(in);x.span=solver::readPod<uint8_t>(in);x.combo=solver::readPod<uint8_t>(in)!=0;b.blocks.push_back(x);}
            if(game::encodeBoard(b)!=id)throw runtime_error("board dictionary mismatch");
        }
        if(in.peek()!=ifstream::traits_type::eof())throw runtime_error("trailing table bytes");
        sort(byCode.begin(),byCode.end());
        ifstream f(input,ios::binary);array<char,8> magic{};f.read(magic.data(),8);string tag(magic.data(),8);
        bool isPolicy=tag=="TALLPOL4" || tag=="TALLAPO1";
        bool risk=tag=="TALLAPO1" || tag=="TALLAPA1" || tag=="TALLAVA1";
        if(risk){aggression=solver::readPod<double>(f);if(!isfinite(aggression)||aggression<0||aggression>h.target/7.5)throw runtime_error("bad aggression");}
        if(isPolicy || tag=="TALLPVA4" || tag=="TALLAPA1"){
            if(identity(f)!=signature)throw runtime_error("transition fingerprint mismatch");
        }else if(tag=="TALLVAL4" || tag=="TALLAVA1"){
            (void)solver::readPod<uint64_t>(f);
            if(solver::readPod<uint64_t>(f)!=h.states)throw runtime_error("value count mismatch");
        }else throw runtime_error("unsupported input; expected policy or complete values");
        policy.resize(h.states,0xFFFFFFFEu);
        if(isPolicy)f.read(reinterpret_cast<char*>(policy.data()),streamsize(policy.size()*4));
        else{
            vector<double> values(h.states);f.read(reinterpret_cast<char*>(values.data()),streamsize(values.size()*8));
            for(double x:values)if(!isfinite(x)||x < -1e-8 || x>1+1e-8)throw runtime_error("invalid values");
            for(uint32_t s=0;s<h.states;++s){
                const auto& row=mdp.rows[s];if(row.flags&1){policy[s]=0xFFFFFFFFu;continue;}
                double best=-numeric_limits<double>::infinity();
                for(uint32_t a=0;a<row.actionCount;++a){double q=0;for(auto t:mdp.groups[mdp.actionGroups[row.actionBegin+a]])q+=values[t];
                    if(q>best){best=q;policy[s]=a;}}
            }
        }
        if(!f || f.peek()!=ifstream::traits_type::eof())throw runtime_error("invalid input length");
        for(uint32_t s=0;s<h.states;++s){auto a=policy[s];auto row=mdp.rows[s];
            if(a==0xFFFFFFFFu){if(!(row.flags&1))throw runtime_error("invalid success action");}
            else if(a==0xFFFFFFFEu){if(!(row.flags&2)&&row.actionCount)throw runtime_error("invalid dead action");}
            else if(a>=row.actionCount)throw runtime_error("policy action outside row");}
    }
    Plan plan(uint32_t sid){
        auto choice=policy[sid];if(choice==0xFFFFFFFEu)throw runtime_error("policy-dead");
        uint64_t post=0;
        if(choice!=0xFFFFFFFFu){
            if(!chosenPost.empty())post=chosenPost[sid];
            else{auto row=mdp.rows[sid];auto g=mdp.actionGroups[row.actionBegin+choice];post=solver::prefixFromStateCode(codes[mdp.groups[g][0]]);}}
        return recoverPlan(game::decodeState(codes[sid]),choice==0xFFFFFFFFu,post);
    }
    void compactForQueries(){
        chosenPost.resize(codes.size());
        for(uint32_t s=0;s<codes.size();++s)if(policy[s]<0xFFFFFFFEu){
            auto row=mdp.rows[s];auto g=mdp.actionGroups[row.actionBegin+policy[s]];
            chosenPost[s]=solver::prefixFromStateCode(codes[mdp.groups[g][0]]);}
        mdp.rows.clear();mdp.rows.shrink_to_fit();mdp.actionGroups.clear();mdp.actionGroups.shrink_to_fit();mdp.groups.clear();mdp.groups.shrink_to_fit();
    }
    void saveQuery(const string& path){
        bool strict=game::SINGLE_EDGE_GUARD||game::SINGLE_TIDY_EXIT;
        ofstream out(path,ios::binary);out.write(strict?"TNQUERY5":(game::MATCH_EDGE_GUARD?"TNQUERY4":(game::SUCCESS_NO_EXTRA_COMBOS?"TNQUERY3":"TNQUERY2")),8);
        auto put=[&](auto x){out.write(reinterpret_cast<char*>(&x),sizeof(x));};auto h=mdp.header;
        put(h.capacity);put(h.target);put(uint32_t(game::MAX_VALUE));
        if(game::SUCCESS_NO_EXTRA_COMBOS||game::MATCH_EDGE_GUARD)put(uint32_t(game::SUCCESS_NO_EXTRA_COMBOS));
        if(game::MATCH_EDGE_GUARD||strict)put(uint32_t(game::MATCH_EDGE_GUARD));
        if(strict){put(uint32_t(game::SINGLE_EDGE_GUARD));put(uint32_t(game::SINGLE_TIDY_EXIT));}
        put(h.maxGoalCells);put(h.aboveOnly);put(uint32_t(h.bases.size()));for(auto b:h.bases)put(b);
        put(h.states);put(signature);
        for(auto [code,s]:byCode)put(code);
        for(auto [code,s]:byCode){uint64_t post=0;if(policy[s]<0xFFFFFFFEu){auto row=mdp.rows[s];auto g=mdp.actionGroups[row.actionBegin+policy[s]];post=solver::prefixFromStateCode(codes[mdp.groups[g][0]]);}put(post);}
        for(auto [code,s]:byCode)put(policy[s]);
        put(uint64_t(game::boardRegistry.size()));for(const auto& b:game::boardRegistry){put(uint32_t(b.blocks.size()));put(b.fpos);for(auto x:b.blocks){put(x.value);put(x.span);put(uint8_t(x.combo));}}
        out.close();if(!out)throw runtime_error("query cache write failed");
    }
    // Extension is allowed either for an ordinary final b, or when the final
    // free action creates the b group directly. Never nest an existing group.
    bool extensible(uint32_t sid,const Plan& p){
        Board b=game::decodeState(codes[sid]).board;Board before=b;
        for(const auto& op:p.freeOps){before=b;bool found=false;for(auto& move:freeMoves(b))
            if(move.second.kind==op.kind && move.second.l==op.l && move.second.r==op.r){b=move.first;found=true;break;}
            if(!found)throw runtime_error("free action recovery mismatch");}
        if(p.mode>=0)b=game::doDraw(b,DrawMode(p.mode),game::SPAWN[game::decodeState(codes[sid]).q1]).board;
        if(b.fpos>=b.blocks.size())return false;
        const auto& goal=b.blocks[b.fpos];
        if(goal.value!=game::TARGET)return false;
        if(!goal.combo)return !game::hasCombo(b);
        if(p.mode>=0 || p.freeOps.empty())return false;
        auto op=p.freeOps.back();
        if(op.kind!=0 || op.l!=before.fpos || op.r-op.l+1>4)return false;
        int sum=0;for(int i=op.l;i<=op.r;++i)sum+=before.blocks[i].value;
        return sum==game::TARGET;
    }
    void query(const string& line){
        istringstream ss(line);int fpos,n,q1,q2;ss>>fpos>>n>>q1>>q2;
        if(!ss||n<0||uint32_t(n)>mdp.header.capacity||fpos<0||fpos>n)throw runtime_error("invalid query");
        Board b;b.fpos=uint8_t(fpos);
        for(int i=0;i<n;++i){int v,span,combo;ss>>v>>span>>combo;if(!ss||v<1||v>65535||span<1||span>5||(combo!=0&&combo!=1))throw runtime_error("invalid block");b.blocks.push_back({uint16_t(v),uint8_t(span),bool(combo)});}
        auto bi=game::boardIds.find(b);if(bi==game::boardIds.end())throw runtime_error("out-of-model-board");
        auto qi=[](int v){for(int i=0;i<6;++i)if(game::SPAWN[i]==v)return i;throw runtime_error("invalid preview");};
        uint64_t code=bi->second|(uint64_t(qi(q1))<<54)|(uint64_t(qi(q2))<<57);
        uint32_t sid;
        if(byCode.empty()){auto it=lower_bound(codes.begin(),codes.end(),code);if(it==codes.end()||*it!=code)throw runtime_error("out-of-model-state");sid=uint32_t(it-codes.begin());}
        else{auto si=lower_bound(byCode.begin(),byCode.end(),make_pair(code,uint32_t(0)));if(si==byCode.end()||si->first!=code)throw runtime_error("out-of-model-state");sid=si->second;}
        if(policy[sid]==0xFFFFFFFEu){cout<<"{\"status\":\"dead\"}"<<endl;return;}
        auto p=plan(sid);bool success=policy[sid]==0xFFFFFFFFu;
        if(success && exitKind=="extend" && !extensible(sid,p)){cout<<"{\"status\":\"incompatible-exit\"}"<<endl;return;}
        cout<<"{\"status\":\"ok\",\"success\":"<<(success?"true":"false")<<",\"ops\":[";
        bool comma=false;
        Board end=b;
        for(auto op:p.freeOps){
            for(auto move:freeMoves(end))if(move.second.kind==op.kind && move.second.l==op.l && move.second.r==op.r){end=move.first;break;}
            if(comma)cout<<',';comma=true;cout<<"{\"kind\":"<<quote(op.kind==0?"group":"edge")<<",\"l\":"<<op.l<<",\"r\":"<<op.r<<",\"board\":"<<boardJSON(end)<<'}';}
        if(p.mode>=0){end=game::doDraw(end,DrawMode(p.mode),q1).board;
            if(comma)cout<<',';cout<<"{\"kind\":"<<quote(p.mode==0?"drop":p.mode==1?"down":"up")<<",\"board\":"<<boardJSON(end)<<'}';}
        cout<<"],\"board\":"<<boardJSON(end)<<"}"<<endl;
    }
    void exportGraph(const string& prefix){
        vector<uint32_t> dense(codes.size(),solver::INVALID_ID),order;
        for(uint32_t s=0;s<36;++s){dense[s]=order.size();order.push_back(s);}
        vector<uint8_t> kinds,costs;
        vector<array<uint32_t,6>> next;
        for(size_t k=0;k<order.size();++k){
            auto s=order[k],choice=policy[s];uint8_t kind=0,cost=1;array<uint32_t,6> ns{};
            if(choice==0xFFFFFFFEu){kind=2;cost=0;}
            else if(choice==0xFFFFFFFFu){auto p=plan(s);cost=p.mode>=0?1:0;kind=(exitKind=="extend"&&!extensible(s,p))?2:1;}
            else{auto row=mdp.rows[s];auto g=mdp.actionGroups[row.actionBegin+choice];
                for(int i=0;i<6;++i){auto t=mdp.groups[g][i];if(dense[t]==solver::INVALID_ID){dense[t]=order.size();order.push_back(t);}ns[i]=dense[t];}}
            kinds.push_back(kind);costs.push_back(cost);next.push_back(ns);
        }
        ofstream out(prefix+".graph.bin",ios::binary);out.write("TNGRAPH1",8);uint64_t n=order.size();out.write(reinterpret_cast<char*>(&n),8);
        out.write(reinterpret_cast<char*>(kinds.data()),n);out.write(reinterpret_cast<char*>(costs.data()),n);
        out.write(reinterpret_cast<char*>(next.data()),streamsize(n*24));out.close();if(!out)throw runtime_error("graph write failed");
        ofstream pf(prefix+".policy.bin",ios::binary);pf.write("TALLPOL4",8);
        auto put=[&](auto x){pf.write(reinterpret_cast<char*>(&x),sizeof(x));};const auto& h=mdp.header;
        put(uint32_t(4));put(h.capacity);put(h.target);put(h.states);put(h.maxGoalCells);put(h.aboveOnly);put(uint32_t(h.bases.size()));for(auto b:h.bases)put(b);put(signature);
        pf.write(reinterpret_cast<char*>(policy.data()),streamsize(policy.size()*4));pf.close();if(!pf)throw runtime_error("policy write failed");
        cout<<"{\"target\":"<<h.target<<",\"states\":"<<h.states<<",\"reachableStates\":"<<n<<",\"exit\":"<<quote(exitKind)<<",\"aggressiveness\":"<<aggression<<",\"maxGoalCells\":"<<h.maxGoalCells
            <<",\"successNoExtraCombos\":"<<(game::SUCCESS_NO_EXTRA_COMBOS?"true":"false")
            <<",\"matchEdgeGuard\":"<<(game::MATCH_EDGE_GUARD?"true":"false")
            <<",\"exitSemantics\":"<<quote(game::SUCCESS_NO_EXTRA_COMBOS?"success-board-clean-v3":"success-board-v2")<<"}"<<endl;
    }
};

#ifndef TALLNUM_FIXED_CACHE_LIBRARY
int main(int argc,char** argv){
    try{
        if(argc==4 && string(argv[1])=="query"){
            PolicyService service(argv[2],argv[3]);cout<<"{\"status\":\"ready\"}"<<endl;string line;
            while(getline(cin,line)){try{service.query(line);}catch(const exception& e){cout<<"{\"status\":\"error\",\"error\":"<<quote(e.what())<<"}"<<endl;}}
            return 0;
        }
        if(argc<5)throw runtime_error("usage: native_policy TABLE POLICY_OR_VALUES EXIT serve|export [PREFIX]");
        PolicyService service(argv[1],argv[2],argv[3]);
        if(string(argv[4])=="export"){if(argc!=6)throw runtime_error("missing export prefix");service.exportGraph(argv[5]);}
        else if(string(argv[4])=="cache"){if(argc!=6)throw runtime_error("missing cache path");service.saveQuery(argv[5]);}
        else if(string(argv[4])=="serve"){
            service.compactForQueries();
            cout<<"{\"status\":\"ready\"}"<<endl;string line;
            while(getline(cin,line)){try{service.query(line);}catch(const exception& e){cout<<"{\"status\":\"error\",\"error\":"<<quote(e.what())<<"}"<<endl;}}
        }else throw runtime_error("unknown command");
    }catch(const exception& e){cerr<<e.what()<<endl;return 1;}
}
#endif
