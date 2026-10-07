// Experimental pending-state policy: store one expected value per (board, next q1).
// The six possible newly revealed previews are averaged when the file is built.
#define TALLNUM_REPLAY_LIBRARY
#include "../export_replay_128_a001_no_death.cpp"

struct PendingValues {
    struct PackedBlock { uint16_t value=0; uint8_t span=0, combo=0; };
    struct BoardRow { uint8_t n=0, fpos=0; array<PackedBlock,6> blocks{}; };
    struct BoardKey {
        array<uint32_t,8> parts{};
        bool operator<(const BoardKey& other) const { return parts<other.parts; }
    };
    solver::Header header;
    uint32_t maxValue = 0;
    bool clean = false;
    bool matchEdgeGuard = false;
    bool singleEdgeGuard = false;
    bool singleTidyExit = false;
    uint64_t fullStates = 0;
    vector<pair<uint64_t,double>> entries;
    vector<BoardRow> sixBoardsById;
    vector<pair<BoardKey,uint32_t>> sixBoardIdsByKey;

    static BoardKey makeBoardKey(const Board& b) {
        if(b.blocks.size()>6)throw runtime_error("six-cell board key overflow");
        BoardKey k;k.parts[0]=b.fpos;k.parts[1]=uint32_t(b.blocks.size());
        for(size_t i=0;i<b.blocks.size();++i){const auto& x=b.blocks[i];
            k.parts[2+i]=uint32_t(x.value)|(uint32_t(x.span)<<16)|(uint32_t(x.combo)<<19);}
        return k;
    }
    uint64_t boardId(const Board& b) const {
        if(header.capacity!=6)return game::encodeBoard(b);
        auto key=makeBoardKey(b);
        auto it=lower_bound(sixBoardIdsByKey.begin(),sixBoardIdsByKey.end(),key,
            [](const auto& item,const BoardKey& k){return item.first<k;});
        if(it==sixBoardIdsByKey.end()||it->first.parts!=key.parts)
            throw runtime_error("out-of-model-board");
        return it->second;
    }

    static void configure(const PendingValues& p) {
        if((p.header.capacity!=5 && p.header.capacity!=6) || !p.header.aboveOnly ||
           p.maxValue<p.header.target || p.maxValue>65535)
            throw runtime_error("unsupported pending-state model");
        if((p.singleEdgeGuard||p.singleTidyExit) && (p.header.capacity!=6 || p.header.maxGoalCells!=1 || !p.clean))
            throw runtime_error("strict single requires a clean six-cell single model");
        game::CAPACITY=p.header.capacity;game::TARGET=p.header.target;
        game::MAX_VALUE=p.maxValue;game::MAX_GOAL_CELLS=p.header.maxGoalCells;
        game::ABOVE_ONLY=true;game::SUCCESS_NO_EXTRA_COMBOS=p.clean;
        game::MATCH_EDGE_GUARD=p.matchEdgeGuard;
        game::SINGLE_EDGE_GUARD=p.singleEdgeGuard;
        game::SINGLE_TIDY_EXIT=p.singleTidyExit;
        game::BASES.assign(p.header.bases.begin(),p.header.bases.end());
        game::boardRegistry.clear();game::boardIds.clear();
    }
    static void readBoards(ifstream& in,PendingValues& p) {
        configure(p);
        uint64_t count=solver::readPod<uint64_t>(in);
        if(p.header.capacity==6){
            if(count>SIZE_MAX/sizeof(BoardRow))throw runtime_error("six-cell board dictionary too large");
            p.sixBoardsById.resize(size_t(count));p.sixBoardIdsByKey.reserve(size_t(count));
            for(uint64_t id=0;id<count;++id){Board b;uint32_t n=solver::readPod<uint32_t>(in);
                b.fpos=solver::readPod<uint8_t>(in);
                if(n>6||b.fpos>n)throw runtime_error("invalid six-cell board dictionary");
                auto& row=p.sixBoardsById[size_t(id)];row.n=uint8_t(n);row.fpos=b.fpos;
                for(uint32_t j=0;j<n;++j){Block x;x.value=solver::readPod<uint16_t>(in);
                    x.span=solver::readPod<uint8_t>(in);x.combo=solver::readPod<uint8_t>(in)!=0;
                    row.blocks[j]={x.value,x.span,uint8_t(x.combo)};b.blocks.push_back(x);}
                p.sixBoardIdsByKey.emplace_back(makeBoardKey(b),uint32_t(id));}
            sort(p.sixBoardIdsByKey.begin(),p.sixBoardIdsByKey.end(),
                 [](const auto& a,const auto& b){return a.first<b.first;});
            for(size_t i=1;i<p.sixBoardIdsByKey.size();++i)
                if(p.sixBoardIdsByKey[i-1].first.parts==p.sixBoardIdsByKey[i].first.parts)
                    throw runtime_error("duplicate six-cell board dictionary entry");
            return;
        }
        for(uint64_t id=0;id<count;++id){
            Board b;uint32_t n=solver::readPod<uint32_t>(in);b.fpos=solver::readPod<uint8_t>(in);
            if(n>p.header.capacity||b.fpos>n)throw runtime_error("invalid board dictionary");
            for(uint32_t j=0;j<n;++j){Block x;
                x.value=solver::readPod<uint16_t>(in);x.span=solver::readPod<uint8_t>(in);
                x.combo=solver::readPod<uint8_t>(in)!=0;b.blocks.push_back(x);}
            if(game::encodeBoard(b)!=id)throw runtime_error("board dictionary order mismatch");
        }
    }
    void writeBoards(ofstream& out) const {
        auto put=[&](auto x){out.write(reinterpret_cast<const char*>(&x),sizeof(x));};
        if(header.capacity==6){
            put(uint64_t(sixBoardsById.size()));
            for(const auto& b:sixBoardsById){put(uint32_t(b.n));put(b.fpos);
                for(uint32_t j=0;j<b.n;++j){put(b.blocks[j].value);put(b.blocks[j].span);put(b.blocks[j].combo);}}
            return;
        }
        put(uint64_t(game::boardRegistry.size()));
        for(const auto& b:game::boardRegistry){put(uint32_t(b.blocks.size()));put(b.fpos);
            for(const auto& x:b.blocks){put(x.value);put(x.span);put(uint8_t(x.combo));}}
    }
    void build(const string& table,const string& valuesPath) {
        auto mdp=solver::loadMDP(table);header=mdp.header;fullStates=header.states;
        ifstream model(table+".model.json");
        if(model){string data((istreambuf_iterator<char>(model)),{});smatch m;
            if(!regex_search(data,m,regex("\\\"maxValue\\\"\\s*:\\s*([0-9]+)")))throw runtime_error("invalid model metadata");
            maxValue=stoul(m[1]);
            if(regex_search(data,m,regex("\\\"successNoExtraCombos\\\"\\s*:\\s*(true|false)")))clean=m[1]=="true";
            if(regex_search(data,m,regex("\\\"matchEdgeGuard\\\"\\s*:\\s*(true|false)")))matchEdgeGuard=m[1]=="true";
            if(regex_search(data,m,regex(R"("singleEdgeGuard"\s*:\s*(true|false))")))singleEdgeGuard=m[1]=="true";
            if(regex_search(data,m,regex(R"("singleTidyExit"\s*:\s*(true|false))")))singleTidyExit=m[1]=="true";
        }else maxValue=header.target;
        if(matchEdgeGuard && (header.capacity!=5 || header.maxGoalCells!=5))
            throw runtime_error("match EDGE guard requires a five-cell match model");
        configure(*this);
        vector<double> values(fullStates);
        solver::loadValues(valuesPath,header,0,values,false);
        ifstream in(table,ios::binary);solver::readHeader(in);
        if(header.capacity==6){
            // Six-cell tables are tens of millions of states. Stream their
            // already-contiguous six-preview groups instead of materializing
            // every MDP row/action/group in RAM.
            entries.reserve(size_t(fullStates/6+1));
            uint64_t i=0;
            for(;i<fullStates;){
                uint64_t code=solver::readPod<uint64_t>(in);
                uint64_t prefix=solver::prefixFromStateCode(code);
                if(solver::q2FromStateCode(code)!=0)throw runtime_error("six-cell preview group does not start at q2=0");
                double sum=values[i++];
                uint8_t flags=solver::readPod<uint8_t>(in);(void)flags;
                uint32_t n=solver::readPod<uint32_t>(in);in.seekg(streamoff(n)*8,ios::cur);
                if(!in)throw runtime_error("truncated six-cell transition table");
                for(uint8_t q=1;q<6;++q){
                    code=solver::readPod<uint64_t>(in);
                    if(solver::prefixFromStateCode(code)!=prefix||solver::q2FromStateCode(code)!=q)
                        throw runtime_error("incomplete or non-contiguous six-cell preview group");
                    sum+=values[i++];
                    (void)solver::readPod<uint8_t>(in);n=solver::readPod<uint32_t>(in);
                    in.seekg(streamoff(n)*8,ios::cur);
                    if(!in)throw runtime_error("truncated six-cell transition table");
                }
                entries.emplace_back(prefix,sum/6.0);
            }
            if(i!=fullStates)throw runtime_error("six-cell state count is not divisible by six");
            sort(entries.begin(),entries.end());
            for(size_t j=1;j<entries.size();++j)if(entries[j-1].first==entries[j].first)
                throw runtime_error("duplicate six-cell pending state");
            vector<double>().swap(values);
            readBoards(in,*this);
            if(in.peek()!=ifstream::traits_type::eof())throw runtime_error("extra table bytes");
            return;
        }
        for(uint64_t i=0;i<fullStates;++i){
            (void)solver::readPod<uint64_t>(in);(void)solver::readPod<uint8_t>(in);
            uint32_t n=solver::readPod<uint32_t>(in);
            in.seekg(streamoff(n)*8,ios::cur);
            if(!in)throw runtime_error("truncated transition table");
        }
        readBoards(in,*this);
        if(in.peek()!=ifstream::traits_type::eof())throw runtime_error("extra table bytes");
        entries.reserve(mdp.groups.size());
        for(const auto& group:mdp.groups){
            uint64_t prefix=UINT64_MAX;double sum=0;
            for(int q=0;q<6;++q){
                if(group[q]==solver::INVALID_ID)throw runtime_error("incomplete preview group");
                // Dense IDs follow the same file order as the value array.
                sum+=values[group[q]];
            }
            // The first state in each group has the group's prefix.
            // Read its code from the table's state-code index below.
            entries.emplace_back(group[0],sum/6.0);
        }
        in.clear();in.seekg(0);solver::readHeader(in);
        vector<uint64_t> codes(fullStates);
        for(uint64_t i=0;i<fullStates;++i){codes[i]=solver::readPod<uint64_t>(in);
            (void)solver::readPod<uint8_t>(in);uint32_t n=solver::readPod<uint32_t>(in);
            in.seekg(streamoff(n)*8,ios::cur);if(!in)throw runtime_error("truncated state codes");}
        for(auto& e:entries)e.first=solver::prefixFromStateCode(codes[e.first]);
        sort(entries.begin(),entries.end());
        for(size_t i=1;i<entries.size();++i)if(entries[i-1].first==entries[i].first)
            throw runtime_error("duplicate pending state");
        if(entries.size()*6!=fullStates)throw runtime_error("state count is not six per pending state");
    }
    void save(const string& path) const {
        ofstream out(path,ios::binary);out.write(singleEdgeGuard||singleTidyExit?"TNPEND03":"TNPEND02",8);
        auto put=[&](auto x){out.write(reinterpret_cast<const char*>(&x),sizeof(x));};
        put(header.capacity);put(header.target);put(maxValue);put(header.maxGoalCells);
        put(header.aboveOnly);put(uint32_t(clean));put(uint32_t(matchEdgeGuard));
        if(singleEdgeGuard||singleTidyExit){put(uint32_t(singleEdgeGuard));put(uint32_t(singleTidyExit));}
        put(uint32_t(header.bases.size()));
        for(auto b:header.bases)put(b);
        put(fullStates);put(uint64_t(entries.size()));
        for(const auto& [key,value]:entries){put(key);put(value);}
        writeBoards(out);out.close();if(!out)throw runtime_error("pending value write failed");
    }
    void load(const string& path) {
        ifstream in(path,ios::binary);array<char,8> magic{};in.read(magic.data(),8);
        bool strict=string(magic.data(),8)=="TNPEND03";
        if(!strict&&string(magic.data(),8)!="TNPEND02")throw runtime_error("invalid pending-value file");
        header.capacity=solver::readPod<uint32_t>(in);header.target=solver::readPod<uint32_t>(in);
        maxValue=solver::readPod<uint32_t>(in);header.maxGoalCells=solver::readPod<uint32_t>(in);
        header.aboveOnly=solver::readPod<uint32_t>(in);clean=solver::readPod<uint32_t>(in)!=0;
        matchEdgeGuard=solver::readPod<uint32_t>(in)!=0;
        singleEdgeGuard=strict&&solver::readPod<uint32_t>(in)!=0;
        singleTidyExit=strict&&solver::readPod<uint32_t>(in)!=0;
        uint32_t n=solver::readPod<uint32_t>(in);if(n==0||n>32768)throw runtime_error("invalid bases");
        for(uint32_t i=0;i<n;++i)header.bases.push_back(solver::readPod<uint32_t>(in));
        fullStates=solver::readPod<uint64_t>(in);uint64_t count=solver::readPod<uint64_t>(in);
        if(count==0||count>fullStates||count>SIZE_MAX/sizeof(entries[0]))throw runtime_error("invalid pending count");
        entries.resize(size_t(count));
        for(auto& e:entries){e.first=solver::readPod<uint64_t>(in);e.second=solver::readPod<double>(in);
            if(!isfinite(e.second)||e.second<0||e.second>1+1e-8)throw runtime_error("invalid pending probability");}
        for(size_t i=1;i<entries.size();++i)if(entries[i-1].first>=entries[i].first)
            throw runtime_error("unsorted pending values");
        readBoards(in,*this);
        if(in.peek()!=ifstream::traits_type::eof())throw runtime_error("extra pending bytes");
    }
    double lookup(uint64_t prefix) const {
        auto it=lower_bound(entries.begin(),entries.end(),prefix,
            [](const auto& e,uint64_t key){return e.first<key;});
        if(it==entries.end()||it->first!=prefix)throw runtime_error("missing pending state");
        return it->second;
    }
    void exportPolicy(const string& table,const string& output) const {
        ifstream in(table,ios::binary);auto h=solver::readHeader(in);
        if(h.capacity!=header.capacity||h.target!=header.target||h.maxGoalCells!=header.maxGoalCells||
           h.aboveOnly!=header.aboveOnly||h.bases!=header.bases||h.states!=fullStates)
            throw runtime_error("pending values and table rules differ");
        if(matchEdgeGuard && !clean)throw runtime_error("guarded match must use clean success condition");
        vector<uint32_t> choices;choices.reserve(fullStates);
        uint64_t signature=14695981039346656037ULL;
        auto mix=[&](uint64_t x){for(int i=0;i<8;++i){signature^=x&255;signature*=1099511628211ULL;x>>=8;}};
        for(uint64_t i=0;i<fullStates;++i){
            uint64_t code=solver::readPod<uint64_t>(in);uint8_t flags=solver::readPod<uint8_t>(in);
            uint32_t n=solver::readPod<uint32_t>(in);mix(code);mix(flags);mix(n);
            uint32_t choice=(flags&1)?0xFFFFFFFFu:0xFFFFFFFEu;double bestScore=-1;
            for(uint32_t j=0;j<n;++j){uint64_t post=solver::readPod<uint64_t>(in);mix(post);
                double score=lookup(post);
                if(!(flags&1)&&score>bestScore){bestScore=score;choice=j;}}
            choices.push_back(choice);
        }
        if(!in)throw runtime_error("truncated table while exporting policy");
        ofstream out(output,ios::binary);out.write("TALLPOL4",8);
        auto put=[&](auto x){out.write(reinterpret_cast<const char*>(&x),sizeof(x));};
        put(uint32_t(4));put(h.capacity);put(h.target);put(h.states);put(h.maxGoalCells);
        put(h.aboveOnly);put(uint32_t(h.bases.size()));for(auto b:h.bases)put(b);
        put(signature);out.write(reinterpret_cast<const char*>(choices.data()),streamsize(choices.size()*4));
        out.close();if(!out)throw runtime_error("policy export failed");
    }
    pair<bool,uint64_t> best(const game::State& state) const {
        vector<Board> queue{state.board};unordered_set<Board,game::BoardHash> seen{state.board};
        double highest=-1;uint64_t chosen=0;
        for(size_t i=0;i<queue.size();++i){const Board& b=queue[i];
            if(game::isSuccess(b))return {true,0};
            for(int mode=0;mode<3;++mode){auto out=game::doDraw(b,DrawMode(mode),game::SPAWN[state.q1]);
                if(out.kind==game::OutcomeKind::Success)return {true,0};
                if(out.kind!=game::OutcomeKind::Next)continue;
                uint64_t prefix=game::encodePostDraw(boardId(out.board),state.q2);
                double score=lookup(prefix);
                if(score>highest){highest=score;chosen=prefix;}
            }
            for(auto [next,op]:freeMoves(b))if(seen.insert(next).second)queue.push_back(next);
        }
        if(highest<0)return {false,UINT64_MAX};
        return {false,chosen};
    }
    void query(const string& line) const {
        istringstream ss(line);int fpos,n,q1,q2;ss>>fpos>>n>>q1>>q2;
        if(!ss||n<0||n>int(header.capacity)||fpos<0||fpos>n)throw runtime_error("invalid query");
        Board b;b.fpos=uint8_t(fpos);
        for(int i=0;i<n;++i){int v,span,combo;ss>>v>>span>>combo;
            if(!ss||v<1||v>65535||span<1||span>5||(combo!=0&&combo!=1))throw runtime_error("invalid block");
            b.blocks.push_back({uint16_t(v),uint8_t(span),bool(combo)});}
        if(ss>>ws && !ss.eof())throw runtime_error("extra query fields");
        // The pending-value dictionary is indexed by the state AFTER the
        // next real drop (and its two-preview tail), not by this live input
        // board. In particular, an entry board may contain protected blocks
        // on either side of F and be absent from the dictionary while every
        // legal post-action successor is represented. Keep the historical
        // registration for five-cell caches, whose IDs are built on demand;
        // for six-cell caches validate physical capacity but do not require
        // the current board itself to be a probability-cache key.
        if(header.capacity==5) (void)boardId(b);
        else if(game::usedCells(b)>header.capacity)
            throw runtime_error("query board exceeds physical capacity");
        auto qi=[](int v){for(int i=0;i<6;++i)if(game::SPAWN[i]==v)return uint8_t(i);
            throw runtime_error("invalid preview");};
        game::State state{b,qi(q1),qi(q2)};
        auto [success,post]=best(state);
        if(post==UINT64_MAX){cout<<"{\"status\":\"dead\"}"<<endl;return;}
        Plan plan=recoverPlan(state,success,post,[this](const Board& x){return boardId(x);});
        cout<<"{\"status\":\"ok\",\"success\":"<<(success?"true":"false")
            <<",\"score\":"<<setprecision(17)<<(success?1.0:lookup(post))<<",\"ops\":[";
        bool comma=false;Board end=b;
        for(auto op:plan.freeOps){bool found=false;
            for(auto move:freeMoves(end))if(move.second.kind==op.kind&&move.second.l==op.l&&move.second.r==op.r){end=move.first;found=true;break;}
            if(!found)throw runtime_error("free action recovery mismatch");
            if(comma)cout<<',';comma=true;
            cout<<"{\"kind\":"<<quote(op.kind==0?"group":"edge")<<",\"l\":"<<op.l
                <<",\"r\":"<<op.r<<",\"board\":"<<boardJSON(end)<<'}';}
        if(plan.mode>=0){end=game::doDraw(end,DrawMode(plan.mode),q1).board;
            if(comma)cout<<',';
            cout<<"{\"kind\":"<<quote(plan.mode==0?"drop":plan.mode==1?"down":"up")
                <<",\"board\":"<<boardJSON(end)<<'}';}
        cout<<"],\"board\":"<<boardJSON(end)<<"}"<<endl;
    }
};

int main(int argc,char** argv){
    try{
        if(argc==5&&string(argv[1])=="build"){
            PendingValues p;p.build(argv[2],argv[3]);p.save(argv[4]);
            cout<<"{\"fullStates\":"<<p.fullStates<<",\"pendingStates\":"<<p.entries.size()<<"}\n";
        }else if(argc==5&&string(argv[1])=="policy"){
            PendingValues p;p.load(argv[3]);p.exportPolicy(argv[2],argv[4]);
            cout<<"{\"states\":"<<p.fullStates<<"}\n";
        }else if(argc==3&&string(argv[1])=="query"){
            PendingValues p;p.load(argv[2]);cout<<"{\"status\":\"ready\"}"<<endl;
            string line;while(getline(cin,line))try{p.query(line);}
                catch(const exception& e){cout<<"{\"status\":\"error\",\"error\":"<<quote(e.what())<<"}"<<endl;}
        }else throw runtime_error("usage: pending_value build TABLE VALUES OUTPUT | query PENDING_FILE | policy TABLE PENDING_FILE OUTPUT");
    }catch(const exception& e){cerr<<e.what()<<endl;return 1;}
}
