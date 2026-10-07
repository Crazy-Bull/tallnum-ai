"""Export and evaluate a configured six-cell single policy variant."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import numpy as np
from .common import atomic_json,fingerprint
from .library import table_header


def validate_configuration(config,header):
    if config['cells']!=6 or config['exit']!='single' or config['maxGoalCells']!=1:
        raise ValueError('Requires a six-cell ordinary single policy')
    for field in ('cells','target','maxGoalCells','maxValue','bases'):
        if header[field]!=config[field]:raise ValueError('Table/configuration mismatch: '+field)
    if header['above']!=1 or config['successSide']!='above':
        raise ValueError('Requires above-boundary success')
    if header.get('successNoExtraCombos',False)!=config.get('successNoExtraCombos',False):
        raise ValueError('Table/configuration mismatch: successNoExtraCombos')
    for field in ('singleEdgeGuard','singleTidyExit'):
        if header.get(field,False)!=config.get(field,False):
            raise ValueError('Table/configuration mismatch: '+field)


def simulate_graph(path,attempts=100,seed=648001,limit=100000):
    with open(path,'rb') as f:
        if f.read(8)!=b'TNGRAPH1':raise ValueError('Unknown graph format')
        n=struct.unpack('<Q',f.read(8))[0]
    if n<36 or Path(path).stat().st_size!=16+26*n:
        raise ValueError('Invalid graph size or entry states')
    if attempts<=0 or limit<=0:raise ValueError('Attempts and limit must be positive')
    kind=np.memmap(path,mode='r',dtype='u1',offset=16,shape=(n,))
    cost=np.memmap(path,mode='r',dtype='u1',offset=16+n,shape=(n,))
    nxt=np.memmap(path,mode='r',dtype='<u4',offset=16+2*n,shape=(n,6))
    rng=np.random.default_rng(seed);records=[]
    for i in range(attempts):
        state=int(rng.integers(36));drops=0;outcome='limit'
        for _ in range(limit):
            if state<0 or state>=n:raise ValueError('Invalid graph successor')
            drops+=int(cost[state])
            if kind[state]>2:raise ValueError('Invalid terminal kind')
            if kind[state]:outcome='success' if kind[state]==1 else 'failure';break
            state=int(nxt[state,int(rng.integers(6))])
        records.append({'outcome':outcome,'drops':drops})
    success=sum(r['outcome']=='success' for r in records)
    failures=sum(r['outcome']=='failure' for r in records)
    u=sum(r['drops'] for r in records if r['outcome']=='success')/attempts
    v=sum(r['drops'] for r in records if r['outcome']=='failure')/attempts
    return {'kind':'Monte-Carlo fixed-policy graph estimate','seed':seed,'attempts':attempts,
            'successes':success,'failures':failures,'limits':attempts-success-failures,
            'p':success/attempts,'u':u,'v':v,'c':u+v if success+failures==attempts else None,
            'meanObservedDrops':sum(r['drops'] for r in records)/attempts,
            'expectedTotalDrops':(u+v)*attempts/success if success and success+failures==attempts else None,
            'states':n,'exact':False,'actualGamePoolUnlocksModeled':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,default=Path('automation/runs/six48'))
    parser.add_argument('--exact',action='store_true')
    args=parser.parse_args();work=args.workspace.resolve()
    config=json.loads((work/'configuration.json').read_text())
    storage=Path(config['dataDirectory']);table=storage/'table.bin';values=storage/'vi.values.bin'
    header=table_header(table)
    validate_configuration(config,header)
    vi=json.loads(Path(str(table)+'.result.json').read_text())
    if vi['aggressiveness']!=config['aggressiveness']:
        raise ValueError('Value-file construction aggressiveness differs from configuration')
    prefix=storage/f"six{config['target']}-single";graph=Path(str(prefix)+'.graph.bin')
    bridge=Path(config.get('nativeBridge',str(work/'tallnum_automation_six.exe')))
    export_identity={'table':fingerprint(table),'values':fingerprint(values),'native':fingerprint(bridge),'exit':'single'}
    identity_path=work/'export-identity.json'
    cached=json.loads(identity_path.read_text()) if identity_path.exists() else None
    if not graph.exists() or not Path(str(prefix)+'.policy.bin').exists() or cached!=export_identity:
        with (work/'export.log').open('w') as log:
            result=subprocess.run([str(bridge),str(table),str(values),'single','export',str(prefix)],stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError('Policy export failed: '+(work/'export.log').read_text(errors='replace')[-2000:])
        atomic_json(identity_path,export_identity)
    stats=simulate_graph(graph,seed=config.get('simulationSeed',648001))
    atomic_json(work/'simulation.json',stats)
    print(json.dumps(stats),flush=True)
    if args.exact or config.get('successNoExtraCombos',False):
        from .statistics import evaluate_file
        stats=evaluate_file(graph)
        stats['exact']=True
        stats['evaluation']='fixed-policy linear equations, floating-point residual checked'
        stats['c']=stats['u']+stats['v'] if stats['usable'] else None
        atomic_json(work/'statistics.json',stats)
    certification={}
    if config.get('successNoExtraCombos',False):
        from .aggressive import execute, PETSC_BIN
        from .library import NATIVE_DIR
        evaluations=[]
        for step,rtol in ((1,'1e-11'),(2,'1e-12')):
            stage=f'exit_probability_{step:02d}'
            result=work/f'{stage}.result.json'
            execute(stage,[NATIVE_DIR/'petsc_graph_eval.exe',graph,result,
                    '-ksp_type','dgmres','-ksp_gmres_restart','50','-ksp_rtol',rtol,
                    '-ksp_atol','1e-13','-ksp_max_it','20000','-pc_type','jacobi'],
                    work,PETSC_BIN,table_path=table)
            actual=json.loads(result.read_text(encoding='utf-8'))
            if not actual.get('converged') or abs(actual['successProbability']-stats['p'])>1e-5:
                raise RuntimeError('Clean-exit PETSc fixed-policy verification failed')
            evaluations.append(str(result))
        stats['momentSolverSuccessProbability']=stats['p']
        stats['p']=actual['successProbability']
        stats['failureProbability']=max(0,1-stats['p']-stats['nonterminationProbability'])
        stats['successDrops']=stats['u']/stats['p'] if stats['p'] else None
        stats['failureDrops']=stats['v']/stats['failureProbability'] if stats['failureProbability'] else None
        stats['expectedTotalDrops']=(stats['u']+stats['v'])/stats['p'] if stats['usable'] and stats['p'] else None
        stats['probabilitySolver']='PETSc-fixed-exit-graph'
        atomic_json(work/'statistics.json',stats)
        certification={'verified':True,'rounds':2,'exitEvaluationRounds':2,
                       'exitEvaluationResults':evaluations,'successNoExtraCombos':True}
    manifest={**config,'header':header,'valueIteration':vi,'policy':str(prefix)+'.policy.bin',
              'policySha256':fingerprint(str(prefix)+'.policy.bin'),'graph':str(graph),
              'statistics':stats,'petsc':certification,'valueIterationConverged':vi['max_delta']<=vi['tolerance'],
              'globalOptimalityCertified':False,'fiveCellCatalogRegistered':False,
              'objective':'maximize survival-discounted success probability',
              'evaluationArtificialSuddenDeath':False,
              'expectedDropsOptimalityCertified':False,
              'modelNotes':{'activePhysicalSlotsExcludeVirtualF':True,'previewCount':2,
                            'drawPool':[2,4,6,8,10,15],'drawProbabilities':[1/6]*6,
                            'groupMaxMembers':5,'actualGamePoolUnlocksModeled':False,
                            'successNoExtraCombos':config.get('successNoExtraCombos',False)}}
    atomic_json(work/'result.json',manifest)
    print(json.dumps({'completed':True,'valueIterationConverged':manifest['valueIterationConverged']}),flush=True)


if __name__=='__main__':main()
