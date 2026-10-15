"""Generate physical policies for explicitly requested min24 contracts."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
from .common import atomic_json,fingerprint
from .library import current_rule,MODEL
from .no80_route import ROOT,OUT,EVIDENCE


def build(target,kind,value,maximum,bases,initial=None,cells=5,keep=False):
    if not 24<=target<=64:raise ValueError('Five-cell targets must be in [24,64]')
    directory=OUT/'min24-models'/(f'{cells}-{kind}-{target}-anchor{value}'+(f'-warm{initial}' if initial else '')+('-keep' if keep else ''))
    directory.mkdir(parents=True,exist_ok=True)
    if (directory/'policy.json').exists() and (directory/'table.bin.gz').exists():
        return json.loads((directory/'policy.json').read_text())
    native=OUT/'min24-pending-stream.exe'
    generator=OUT/'min24-generator.exe'
    catalog=json.loads((EVIDENCE/'catalog.json').read_text())
    base=next(p for p in catalog['policies'] if p['exit']==('match' if kind=='extend' else kind) and p.get('cells',5)==5)
    table,values,pending,policy=(directory/name for name in ('table.bin','values.bin','pending.bin','policy.bin'))
    if not (directory/'policy.json').exists():
        # A cancelled native build may have left an unpublished partial file.
        for artifact in (pending,policy):
            if artifact.exists():artifact.unlink()
    span=1 if kind=='single' else 4 if kind=='extend' else 5
    command=[str(generator),'--cells',str(cells),'--target',str(target),'--max-value',str(maximum),
             '--max-goal-cells',str(span),'--bases',bases,'--success-side','above',
             '--success-no-extra-combos','1','--single-tidy-exit','1',
             '--single-protected-value' if kind=='single' else '--match-protected-value',str(value),
             '--output',str(table)]
    if kind=='extend':command+=['--extension-exit','1']
    if initial:command+=['--initial-ordinary',str(initial)]
    if keep:command+=['--keep-warm-base','1']
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ['PATH']
    with (directory/'compute.log').open('a',encoding='utf-8') as log:
        if not table.exists():
            subprocess.run(command,stdout=log,stderr=log,check=True)
            atomic_json(Path(str(table)+'.rules.json'),{'ruleSha256':current_rule(),
                         'sourceSha256':fingerprint(MODEL),'modelSha256':fingerprint(str(table)+'.model.json'),
                         'tableSha256':fingerprint(table)})
        if not values.exists():subprocess.run([str(OUT/'min24-vi.exe'),str(table),'5000','1e-10',str(values)],stdout=log,stderr=log,check=True)
        if not pending.exists():
            temporary=Path(str(pending)+'.building')
            subprocess.run([str(native),'build',str(table),str(values),str(temporary)],stdout=log,stderr=log,check=True)
            temporary.replace(pending)
        if not policy.exists():
            temporary=Path(str(policy)+'.building')
            subprocess.run([str(native),'policy',str(table),str(pending),str(temporary)],stdout=log,stderr=log,check=True)
            temporary.replace(policy)
    item=deepcopy(base);identifier=directory.name+'-'+fingerprint(table)[:12]
    for field in ('statistics','petsc','reachableStates','variantAggressiveness'):item.pop(field,None)
    item.update(id=identifier,target=target,exit=kind,cells=cells,maxValue=maximum,maxGoalCells=span,
                bases=list(map(int,bases.split(','))),table=str(table),source=str(values),policy=str(policy),
                policySha256=fingerprint(policy),ruleSha256=current_rule(),successNoExtraCombos=True,
                singleEdgeGuard=kind=='single',singleTidyExit=True,matchEdgeGuard=kind!='single',
                singleProtectedValue=value,singleProtectedHead=value//10,disableEdge=False,
                disableStaticFallback=True,pendingNative=str(native),pendingValue=str(pending),
                pendingValueMeta=str(directory/'pending.json'),pendingValueSha256=fingerprint(pending),
                realBoardAlternatives=True,normalBoundaryPriority=True)
    if kind=='extend':item['extensionExit']=True
    else:item.pop('extensionExit',None)
    if initial:item['warmStartOrdinary']=initial
    if keep:item['keepWarmBase']=True
    if initial:item['probabilityScope']='conditional on the explicitly constructed active warm block'
    item['hashes']={'table':fingerprint(table),'source':fingerprint(values),'native':fingerprint(native)}
    # Values above the largest modeled decimal head cannot collide normally
    # or under EDGE. F remains external and consumes no active template cell.
    if kind=='single' and value//10>maximum//10:
        item['equivalentProtectedMinimum']=10*(maximum//10+1)
    item['realValueResult']=json.loads(Path(str(table)+'.result.json').read_text())
    metadata={'format':'TNPEND06' if kind=='extend' else 'TNPEND05',
              'pendingSha256':item['pendingValueSha256'],'tableSha256':item['hashes']['table'],
              'policySha256':item['policySha256'],'target':target,'exit':kind,'cells':cells,
              'maxValue':maximum,'maxGoalCells':span,'successNoExtraCombos':True,
              'matchEdgeGuard':kind!='single','singleEdgeGuard':kind=='single','singleTidyExit':True,
              'singleProtectedHead':value//10,'singleProtectedValue':value,'disableEdge':False}
    if kind=='extend':metadata['extensionExit']=True
    atomic_json(directory/'pending.json',metadata);atomic_json(directory/'policy.json',item)
    print(json.dumps({'policy':identifier,'values':item['realValueResult']},ensure_ascii=False),flush=True)
    return item


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',type=int,required=True)
    parser.add_argument('--exit',choices=('single','match','extend'),required=True)
    parser.add_argument('--anchor',type=int,required=True)
    parser.add_argument('--maximum',type=int,default=64)
    parser.add_argument('--bases',default='1,3,5,15')
    parser.add_argument('--initial',type=int)
    parser.add_argument('--cells',type=int,choices=(5,6),default=5)
    parser.add_argument('--keep',action='store_true')
    args=parser.parse_args();build(args.target,args.exit,args.anchor,args.maximum,args.bases,args.initial,args.cells,args.keep)
