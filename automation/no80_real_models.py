"""Exact real-boundary single variants and a no-EDGE match connection."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

from .common import atomic_json, fingerprint
from .library import current_rule, MODEL
from .no80_route import ROOT, OUT, EVIDENCE, audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pairs',default='24:10,30:40,30:60,60:48,32:12,32:24,40:28,48:24,48:36')
    parser.add_argument('--no-edge-cells',type=int,choices=(5,6),default=5)
    parser.add_argument('--strict-match',action='store_true')
    parser.add_argument('--strict-extend',action='store_true')
    parser.add_argument('--physical-single',action='store_true',help='Use the generator that checks real normal-merge priority')
    args=parser.parse_args()
    if any(int(pair.split(':')[0])<24 for pair in args.pairs.split(',')):
        raise ValueError('Template targets below 24 are forbidden')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    route=read(OUT/('route-real-models.json' if (OUT/'route-real-models.json').exists() else 'route-v14.json'))
    catalog=read(OUT/('catalog-real-models.json' if (OUT/'catalog-real-models.json').exists() else 'catalog-v14.json'))
    original=read(EVIDENCE/'route.json')
    prefix=next(i for i,s in enumerate(original['steps']) if s['after']==[[5120,1,False]])+1
    available=read(OUT/'catalog-dynamic.json')['policies']
    shared=read(Path('F:/TallnumData/tallnumai-cleanexit/catalog.json'))['policies']
    physical=args.strict_extend or args.physical_single
    directory=OUT/('physical-extend-models' if args.strict_extend else 'physical-single-models' if args.physical_single else 'tidy-match-models' if args.strict_match else 'real-models');directory.mkdir(exist_ok=True)
    native=OUT/('physical-extend-pending.exe' if physical else 'tidy-match-pending.exe' if args.strict_match else 'real-boundary-pending.exe')
    generator=OUT/('physical-extend-generator.exe' if physical else 'tidy-match-generator.exe' if args.strict_match else 'real-boundary-generator.exe')
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ['PATH']

    def build(target,value=None,cells=5,kind='single'):
        pools=catalog['policies']+available+shared
        candidates=[p for p in pools if p['exit']==kind and p['target']==target
                    and p.get('singleProtectedValue') is None and p.get('singleProtectedHead') is None
                    and p.get('successNoExtraCombos')]
        if not candidates:raise ValueError(f'Missing clean model bounds: {kind} {target}')
        base=min(candidates,key=lambda p:p.get('cells',5))
        no_edge=value is None
        label=f'{cells}-{kind}-{target}-'+('no-edge' if no_edge else f'anchor{value}')
        work=directory/label;work.mkdir(exist_ok=True)
        table,values,pending,policy=(work/name for name in ('table.bin','values.bin','pending.bin','policy.bin'))
        span=1 if kind=='single' else base['maxGoalCells']
        command=[str(generator),'--cells',str(cells),'--target',str(target),
                 '--max-value',str(base['maxValue']),'--max-goal-cells',str(span),
                 '--bases',','.join(map(str,base['bases'])),'--success-side','above',
                 '--success-no-extra-combos','1','--output',str(table)]
        if no_edge:command+=['--disable-edge','1','--match-edge-guard','1']
        else:command+=['--single-tidy-exit','1',
                      '--match-protected-value' if kind!='single' else '--single-protected-value',str(value)]
        if kind=='extend':command+=['--extension-exit','1']
        with (work/'compute.log').open('a') as log:
            if not table.exists():
                subprocess.run(command,stdout=log,stderr=log,check=True)
                atomic_json(Path(str(table)+'.rules.json'),{'ruleSha256':current_rule(),
                    'sourceSha256':fingerprint(MODEL),'modelSha256':fingerprint(str(table)+'.model.json'),
                    'tableSha256':fingerprint(table)})
            if not values.exists():subprocess.run([str(ROOT/'tallnum_vi.exe'),str(table),'5000','1e-10',str(values)],stdout=log,stderr=log,check=True)
            if not pending.exists():subprocess.run([str(native),'build',str(table),str(values),str(pending)],stdout=log,stderr=log,check=True)
            if not policy.exists():subprocess.run([str(native),'policy',str(table),str(pending),str(policy)],stdout=log,stderr=log,check=True)
        item=deepcopy(base);identifier=label+'-'+fingerprint(table)[:12]
        item.update(id=identifier,table=str(table),source=str(values),policy=str(policy),cells=cells,
                    maxGoalCells=span,policySha256=fingerprint(policy),singleEdgeGuard=not no_edge and kind=='single',
                    singleTidyExit=not no_edge,disableEdge=no_edge,disableStaticFallback=True,
                    pendingNative=str(native),pendingValue=str(pending),pendingValueMeta=str(work/'pending.json'),
                    pendingValueSha256=fingerprint(pending),realBoardAlternatives=True)
        item['hashes']={'table':fingerprint(table),'source':fingerprint(values),'native':fingerprint(native)}
        item['matchEdgeGuard']=no_edge or kind!='single'
        if kind=='extend':item['extensionExit']=True
        if physical:item['normalBoundaryPriority']=True
        item.pop('singleProtectedHead',None);item.pop('singleProtectedValue',None)
        if value is not None:item.update(singleProtectedValue=value,singleProtectedHead=value//10)
        for field in ('statistics','petsc','reachableStates'):item.pop(field,None)
        item['realValueResult']=read(Path(str(table)+'.result.json'))
        metadata={'format':'TNPEND06' if kind=='extend' else 'TNPEND05','pendingSha256':item['pendingValueSha256'],
            'tableSha256':item['hashes']['table'],'policySha256':item['policySha256'],
            'target':target,'exit':kind,'cells':cells,'maxValue':base['maxValue'],'maxGoalCells':span,
            'successNoExtraCombos':True,'matchEdgeGuard':no_edge or kind!='single','singleEdgeGuard':not no_edge and kind=='single',
            'singleTidyExit':not no_edge,'singleProtectedHead':None if no_edge else value//10,
            'singleProtectedValue':value,'disableEdge':no_edge}
        if kind=='extend':metadata['extensionExit']=True
        atomic_json(work/'pending.json',metadata);atomic_json(work/'policy.json',item)
        catalog['policies']=[p for p in catalog['policies'] if p['id']!=identifier]+[item]
        count=0
        for step in route['steps'][prefix:]:
            if step.get('kind')!='leaf' or step.get('target')!=target:continue
            if no_edge:
                if (step.get('exit')=='single' and step['before'][-1][0]==target
                    and any(a[0]//10>0 and a[0]//10==b[0]//10 for a,b in zip(step['before'],step['before'][1:]))):
                    step.update(exit='match',policy=identifier,policyCells=cells,template=f'{cells}:{target}:match')
                    step.pop('singleConnectionAfter',None);step.pop('connection',None);count+=1
            elif step.get('exit')==kind and step['before'][-1][0]==value:
                step.update(policy=identifier,policyCells=5,template=f'5:{target}:{kind}');count+=1
        if route['steps'][:prefix]!=original['steps'][:prefix]:raise ValueError('Opening changed')
        audit(route,catalog)
        atomic_json(OUT/'route-real-models.json',route);atomic_json(OUT/'catalog-real-models.json',catalog)
        print(json.dumps({'variant':label,'stages':count,'values':item['realValueResult']}),flush=True)

    if not args.strict_match and not args.strict_extend and not args.physical_single:build(48,cells=args.no_edge_cells,kind='match')
    for target,value in (map(int,pair.split(':')) for pair in args.pairs.split(',')):
        build(target,value,kind='extend' if args.strict_extend else 'match' if args.strict_match else 'single')


if __name__=='__main__':main()
