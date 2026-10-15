"""Recalculate single probabilities for the actual protected decimal head."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

from .common import atomic_json, fingerprint
from .library import current_rule, MODEL, table_header
from .no80_route import ROOT, OUT, EVIDENCE, audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pairs',default='6:1,12:4,12:1,12:2,16:1,10:2,10:3,30:4,30:6,60:4,24:1')
    parser.add_argument('--demote-six',action='store_true')
    args=parser.parse_args()
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    route=read(OUT/('route-boundary-models.json' if (OUT/'route-boundary-models.json').exists() else 'route-v14.json'))
    catalog=read(OUT/('catalog-boundary-models.json' if (OUT/'catalog-boundary-models.json').exists() else 'catalog-v14.json'))
    original=read(EVIDENCE/'route.json')
    prefix=next(i for i,s in enumerate(original['steps']) if s['after']==[[5120,1,False]])+1
    directory=OUT/'boundary-models';directory.mkdir(exist_ok=True)
    native=OUT/'boundary-pending.exe'
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ['PATH']
    for target,head in (map(int,pair.split(':')) for pair in args.pairs.split(',')):
        candidates=[p for p in catalog['policies'] if p.get('cells',5)==5 and p['exit']=='single'
                    and p['target']==target and p.get('singleProtectedHead') is None]
        if not candidates:
            candidates=[p for p in read(OUT/'catalog-dynamic.json')['policies'] if p.get('cells',5)==5
                        and p['exit']=='single' and p['target']==target]
        if not candidates:
            candidates=[p for p in read(Path('F:/TallnumData/tallnumai-cleanexit/catalog.json'))['policies']
                        if p.get('cells',5)==5 and p['exit']=='single' and p['target']==target
                        and p.get('successNoExtraCombos')]
        base=candidates[0]
        work=directory/f'{target}-head{head}';work.mkdir(exist_ok=True)
        table,values,pending,policy=(work/name for name in ('table.bin','values.bin','pending.bin','policy.bin'))
        with (work/'compute.log').open('a') as log:
            if not table.exists():
                subprocess.run([str(OUT/'boundary-generator.exe'),'--cells','5','--target',str(target),
                    '--max-value',str(base['maxValue']),'--max-goal-cells','1','--bases',','.join(map(str,base['bases'])),
                    '--success-side','above','--success-no-extra-combos','1','--single-tidy-exit','1',
                    '--single-protected-head',str(head),'--output',str(table)],stdout=log,stderr=log,check=True)
                atomic_json(Path(str(table)+'.rules.json'),{'ruleSha256':current_rule(),
                    'sourceSha256':fingerprint(MODEL),'modelSha256':fingerprint(str(table)+'.model.json'),
                    'tableSha256':fingerprint(table)})
            if not values.exists():subprocess.run([str(ROOT/'tallnum_vi.exe'),str(table),'5000','1e-10',str(values)],stdout=log,stderr=log,check=True)
            if not pending.exists():subprocess.run([str(native),'build',str(table),str(values),str(pending)],stdout=log,stderr=log,check=True)
            if not policy.exists():subprocess.run([str(native),'policy',str(table),str(pending),str(policy)],stdout=log,stderr=log,check=True)
        item=deepcopy(base)
        identifier=f'boundary-single-{target}-head{head}-'+fingerprint(table)[:12]
        item.update(id=identifier,table=str(table),source=str(values),policy=str(policy),
                    cells=5,maxGoalCells=1,successNoExtraCombos=True,matchEdgeGuard=False,
                    policySha256=fingerprint(policy),singleEdgeGuard=True,singleTidyExit=True,
                    singleProtectedHead=head,disableStaticFallback=True,pendingNative=str(native),
                    pendingValue=str(pending),pendingValueMeta=str(work/'pending.json'),
                    pendingValueSha256=fingerprint(pending),realBoardAlternatives=True)
        item['hashes']={'table':fingerprint(table),'source':fingerprint(values),'native':fingerprint(native)}
        # The source policy's statistics/certificate do not describe these new
        # transitions. Preserve provenance without copying its probability.
        for key in ('statistics','petsc','reachableStates'):item.pop(key,None)
        item['boundaryValueResult']=read(Path(str(table)+'.result.json'))
        metadata={'format':'TNPEND04','pendingSha256':item['pendingValueSha256'],
                  'tableSha256':item['hashes']['table'],'policySha256':item['policySha256'],
                  'target':target,'exit':'single','cells':5,'successNoExtraCombos':True,
                  'matchEdgeGuard':False,'singleEdgeGuard':True,'singleTidyExit':True,
                  'singleProtectedHead':head,'maxValue':base['maxValue'],'maxGoalCells':1}
        atomic_json(work/'pending.json',metadata);atomic_json(work/'policy.json',item)
        catalog['policies']=[p for p in catalog['policies'] if p['id']!=identifier]+[item]
        count=0
        for step in route['steps'][prefix:]:
            if (step.get('kind')=='leaf' and step.get('exit')=='single'
                    and (step.get('policyCells')==5 or args.demote_six)
                    and step['target']==target and step['before'][-1][0]//10==head):
                step.update(policy=identifier,policyCells=5,template=f'5:{target}:single');count+=1
        if route['steps'][:prefix]!=original['steps'][:prefix]:raise ValueError('Measured opening changed')
        audit(route,catalog)
        atomic_json(OUT/'route-boundary-models.json',route);atomic_json(OUT/'catalog-boundary-models.json',catalog)
        print(json.dumps({'target':target,'head':head,'stages':count,'values':item['boundaryValueResult']}),flush=True)


if __name__=='__main__':main()
