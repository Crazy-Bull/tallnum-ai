"""Resume guarded, tidy six-cell recomputation and a paired 100-game dynamic run."""
from pathlib import Path
import json
import msvcrt
import os
import subprocess
import sys
import time
from collections import Counter
from .common import atomic_json, fingerprint
from .library import ROOT, current_rule, table_header

OUT=ROOT/'automation/runs/six-strict-single-002'
BIN=OUT/'bin'
BASE=ROOT/'automation/runs/binary10240/min24/pending-search-all-policies-001/validation-100-retry1'
SOURCE=ROOT/'automation/runs/binary10240/min24/pending-search-all-policies-001'
DATA=Path('F:/TallnumData/tallnumai-six-strict-single-v2')

def run(name,argv):
    atomic_json(OUT/'progress.json',{'stage':name,'status':'running','pid':os.getpid(),
                                   'command':list(map(str,argv)),'updatedAt':time.time()})
    with (OUT/(name+'.log')).open('a',encoding='utf-8') as log:
        p=subprocess.run(list(map(str,argv)),cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
    if p.returncode:raise RuntimeError(f'{name} failed ({p.returncode}); see {OUT/name}.log')

def diagnostics(validation):
    route=json.loads((validation/'route.json').read_text())
    counts=Counter();errors=Counter();error_games=[];total_errors=0
    for file in sorted((validation/'games').glob('*.json')):
        data=json.loads(file.read_text());r=data['record'];events=r.get('liveSearch',[])
        current=[e for e in events if e.get('error')=='out-of-model-board']
        if current:error_games.append(r['seed'])
        total_errors+=len(current)
        for e in current:errors[e.get('policy','unknown')]+=1
        if r['outcome']!='success':
            stage=r['failureContext']['stage'];s=route['steps'][stage]
            counts[(s.get('policy',s['kind']),r['reason'])]+=1
    baseline_errors=0;baseline_error_games=0
    for file in sorted((BASE/'games').glob('*.json')):
        r=json.loads(file.read_text())['record']
        n=sum(e.get('status')=='error' for e in r.get('liveSearch',[]))
        baseline_errors+=n;baseline_error_games+=bool(n)
    report={'outOfModelBoardEvents':total_errors,'outOfModelBoardGames':error_games,
            'outOfModelBoardByPolicy':dict(errors),'baselineRawSearchErrors':baseline_errors,
            'baselineSearchErrorGames':baseline_error_games,
            'baselineErrorTypesNotRecorded':True,
            'failuresByPolicy':[{'policy':p,'reason':reason,'games':n} for (p,reason),n in counts.most_common()],
            'interpretation':'Dynamic search retains a finite pending-state dictionary. Count raw domain errors even when bridging/fallback recovers.'}
    atomic_json(OUT/'diagnostics.json',report)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ.get('PATH','')
    with (OUT/'run.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise SystemExit('Strict-single recomputation already running')
        atomic_json(OUT/'configuration.json',{'targets':[32,40,48],'cells':6,'maxValue':48,
                    'aggressiveness':.01,'singleEdgeGuard':True,'assumedProtectedValue':'TARGET',
                    'singleTidyExit':True,'residualMaxPhysicalCells':1,'residualMaxValue':8,
                    'fixedPolicyPETScRounds':2,'attempts':100,'baseline':str(BASE),
                    'dataRoot':str(DATA),'routeSource':str(SOURCE),
                    'binaries':{p.name:fingerprint(p) for p in BIN.glob('*.exe')}})
        try:
            run('recalculate',[sys.executable,'-m','automation.six_template_compute',
                '--targets',32,40,48,'--max-value',48,'--aggressiveness','.01','--strict-single',
                '--data-root',DATA,'--generator',BIN/'generator.exe','--bridge',BIN/'bridge.exe'])
            source=OUT/'source';source.mkdir(exist_ok=True)
            route=json.loads((SOURCE/'route.json').read_text())
            catalog=json.loads((SOURCE/'catalog.json').read_text())
            replacements={}
            for p in catalog['policies']:
                if p.get('cells')!=6 or p.get('exit')!='single':continue
                manifest=ROOT/f"automation/runs/six{p['target']}-alpha001-strict-single-v2/result.json"
                new=json.loads(manifest.read_text())
                if not new.get('singleEdgeGuard') or not new.get('singleTidyExit') or new.get('petsc',{}).get('exitEvaluationRounds',0)<2:
                    raise ValueError('Strict single lacks rules or two PETSc checks')
                table=Path(new['table']);h=table_header(table);table_hash=fingerprint(table)
                atomic_json(Path(str(table)+'.rules.json'),{'tableSha256':table_hash,
                    'modelSha256':fingerprint(str(table)+'.model.json'),'ruleSha256':current_rule(),
                    'generatorSha256':fingerprint(BIN/'generator.exe')})
                new.update(id=p['id'],states=h['states'],ruleSha256=current_rule(),
                    hashes={'table':table_hash,'source':fingerprint(Path(new['dataDirectory'])/'vi.values.bin'),
                            'native':fingerprint(BIN/'bridge.exe')},
                    exitSemantics='single-clean-residual-one-max8-v1')
                replacements[p['id']]=new
            if len(replacements)!=3:raise ValueError('Expected exactly three active six-cell single definitions')
            catalog['policies']=[replacements.get(p['id'],p) for p in catalog['policies']]
            atomic_json(source/'route.json',route);atomic_json(source/'catalog.json',catalog)
            pending=OUT/'pending-search'
            run('pending-build',[sys.executable,'-m','automation.prepare_pending_search',
                '--source-run',source,'--out',pending,'--all-five-cell-exits','--six-cell-singles',
                '--buffer-rescue-search','--native',BIN/'pending.exe'])
            validation=OUT/'validation-100'
            run('validate-100',[sys.executable,'-m','automation.validate_buffer_rescue',
                '--out',validation,'--policy-dir',pending,'--mapping',ROOT/'automation/runs/binary10240/min24/buffer-rescue-all-007/mapping.json',
                '--route-file',pending/'route.json','--catalog-file',pending/'catalog.json',
                '--baseline-run',BASE,'--seed-limit',100])
            diagnostics(validation)
            atomic_json(OUT/'progress.json',{'stage':'complete','status':'completed',
                    'summary':json.loads((validation/'summary.json').read_text()),'updatedAt':time.time()})
        except BaseException as error:
            previous=json.loads((OUT/'progress.json').read_text()) if (OUT/'progress.json').exists() else {}
            atomic_json(OUT/'progress.json',{**previous,'status':'failed','error':repr(error),'updatedAt':time.time()})
            raise

if __name__=='__main__':main()
