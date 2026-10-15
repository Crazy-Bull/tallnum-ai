// Build the old query format from certified fixed choices without loading the MDP.
#define TALLNUM_FIXED_CACHE_LIBRARY
#include "native_policy.cpp"

int main(int argc,char** argv){try{
    if(argc!=6 || string(argv[4])!="cache")throw runtime_error("expected table policy exit cache output");
    ifstream in(argv[1],ios::binary);auto h=solver::readHeader(in);
    if(h.capacity<5 || h.capacity>6 || !h.aboveOnly || !PolicyService::validBases(h.bases))
        throw runtime_error("unsupported fixed cache model");
    string kind=argv[3];
    if(kind!="single"&&kind!="match"&&kind!="extend")throw runtime_error("bad exit");
    if((kind=="single"&&h.maxGoalCells!=1)||(kind=="extend"&&h.maxGoalCells>4))throw runtime_error("bad goal span");
    ifstream model(string(argv[1])+".model.json");string data((istreambuf_iterator<char>(model)),{});
    auto flag=[&](const string& name){smatch m;if(!regex_search(data,m,regex("\\\""+name+"\\\"\\s*:\\s*(true|false)")))return false;return m[1]=="true";};
    smatch bound;if(!regex_search(data,bound,regex(R"("maxValue"\s*:\s*([0-9]+))")))throw runtime_error("missing model bound");
    uint32_t maximum=stoi(bound[1]);if(maximum<h.target||maximum>65535)throw runtime_error("bad model bound");
    bool clean=flag("successNoExtraCombos"),guard=flag("matchEdgeGuard"),edge=flag("singleEdgeGuard"),tidy=flag("singleTidyExit"),strict=edge||tidy;
    if(guard&&kind!="match")throw runtime_error("guard exit mismatch");
    ifstream policyFile(argv[2],ios::binary);array<char,8> magic{};policyFile.read(magic.data(),8);string tag(magic.data(),8);
    if(tag!="TALLPOL4"&&tag!="TALLAPO1")throw runtime_error("requires fixed choices");
    if(tag=="TALLAPO1"){double alpha=solver::readPod<double>(policyFile);if(!isfinite(alpha)||alpha<0||alpha>h.target/7.5)throw runtime_error("bad aggression");}
    for(auto expected:{h.version,h.capacity,h.target})if(solver::readPod<uint32_t>(policyFile)!=expected)throw runtime_error("policy header mismatch");
    if(solver::readPod<uint64_t>(policyFile)!=h.states)throw runtime_error("state count mismatch");
    for(auto expected:{h.maxGoalCells,h.aboveOnly,uint32_t(h.bases.size())})if(solver::readPod<uint32_t>(policyFile)!=expected)throw runtime_error("policy rule mismatch");
    for(auto b:h.bases)if(solver::readPod<uint32_t>(policyFile)!=b)throw runtime_error("policy bases mismatch");
    uint64_t expectedSignature=solver::readPod<uint64_t>(policyFile),signature=14695981039346656037ULL;
    auto mix=[&](uint64_t x){for(int k=0;k<8;++k){signature^=x&255;signature*=1099511628211ULL;x>>=8;}};
    struct Row{uint64_t code,post;uint32_t choice;};vector<Row> rows;rows.reserve(h.states);
    for(uint32_t i=0;i<h.states;++i){
        uint64_t code=solver::readPod<uint64_t>(in);uint8_t flags=solver::readPod<uint8_t>(in);uint32_t count=solver::readPod<uint32_t>(in),choice=solver::readPod<uint32_t>(policyFile);
        mix(code);mix(flags);mix(count);uint64_t selected=0;
        for(uint32_t j=0;j<count;++j){auto post=solver::readPod<uint64_t>(in);mix(post);if(j==choice)selected=post;}
        if(choice==0xFFFFFFFFu){if(!(flags&1))throw runtime_error("bad success choice");}
        else if(choice==0xFFFFFFFEu){if(!(flags&2)&&count)throw runtime_error("bad dead choice");}
        else if(choice>=count)throw runtime_error("choice outside row");
        rows.push_back({code,selected,choice});
    }
    if(signature!=expectedSignature||!policyFile||policyFile.peek()!=ifstream::traits_type::eof())throw runtime_error("fixed policy identity mismatch");
    sort(rows.begin(),rows.end(),[](const Row&a,const Row&b){return a.code<b.code;});
    ofstream out(argv[5],ios::binary);auto put=[&](auto value){out.write(reinterpret_cast<char*>(&value),sizeof(value));};
    out.write(strict?"TNQUERY5":(guard?"TNQUERY4":(clean?"TNQUERY3":"TNQUERY2")),8);
    put(h.capacity);put(h.target);put(maximum);if(clean||guard)put(uint32_t(clean));if(guard||strict)put(uint32_t(guard));if(strict){put(uint32_t(edge));put(uint32_t(tidy));}
    put(h.maxGoalCells);put(h.aboveOnly);put(uint32_t(h.bases.size()));for(auto b:h.bases)put(b);put(h.states);put(signature);
    for(auto r:rows)put(r.code);for(auto r:rows)put(r.post);for(auto r:rows)put(r.choice);
    auto boards=solver::readPod<uint64_t>(in);put(boards);
    for(uint64_t i=0;i<boards;++i){auto n=solver::readPod<uint32_t>(in);put(n);put(solver::readPod<uint8_t>(in));
        for(uint32_t j=0;j<n;++j){put(solver::readPod<uint16_t>(in));put(solver::readPod<uint8_t>(in));put(solver::readPod<uint8_t>(in));}}
    if(!in||in.peek()!=ifstream::traits_type::eof())throw runtime_error("bad transition length");out.close();if(!out)throw runtime_error(string("cache write failed: ")+strerror(errno)+"; available="+to_string(filesystem::space(filesystem::path(argv[5]).parent_path()).available));
    cout<<"{\"status\":\"cached\",\"states\":"<<h.states<<"}"<<endl;return 0;
}catch(const exception& e){cerr<<e.what()<<endl;return 1;}}
