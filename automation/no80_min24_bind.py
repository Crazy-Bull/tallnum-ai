"""Bind the explicit min24 tree only when all physical policies exist."""
from collections import Counter
from copy import deepcopy
import json
from .common import atomic_json
from .no80_route import OUT,EVIDENCE,audit


def bind():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    baseline=read(EVIDENCE/'route.json')
    policies={p['id']:p for p in read(EVIDENCE/'catalog.json')['policies']}
    for name in ('catalog-low17.json','catalog-dynamic.json','catalog-real-models.json'):
        for p in read(OUT/name)['policies']:policies[p['id']]=p
    for directory in ('real-models','tidy-match-models','physical-extend-models','min24-models'):
        for file in (OUT/directory).glob('*/policy.json'):
            p=read(file);policies[p['id']]=p
    prefix=next(i for i,s in enumerate(baseline['steps']) if s['after']==[[5120,1,False]])+1
    suffix=read(OUT/'min24-declared-steps.json')['steps']
    missing=[]
    for index,s in enumerate(suffix,prefix+1):
        if s['kind']!='leaf':continue
        if s['policyCells']==6 and s['exit']=='match':
            s.update(exit='single',singleConnectionAfter=deepcopy(s['after']))
        cells,target,kind=s['policyCells'],s['target'],s['exit']
        if s.get('warmStartOrdinary'):
            cells=s['policyCells']=6
        anchor=s['before'][-1][0]
        candidates=[]
        for p in policies.values():
            if (p.get('cells',5),p['target'],p['exit'])!=(cells,target,kind):continue
            if p.get('warmStartOrdinary')!=s.get('warmStartOrdinary'):continue
            if not p.get('pendingValue') or not p.get('successNoExtraCombos'):continue
            value=p.get('singleProtectedValue')
            equivalent=p.get('equivalentProtectedMinimum')
            if value is not None and value!=anchor and not (equivalent and anchor>=equivalent):continue
            candidates.append(p)
        if not candidates:
            missing.append([cells,target,kind,anchor]);continue
        p=max(candidates,key=lambda p:(p.get('singleProtectedValue')==anchor,
                                      bool(p.get('normalBoundaryPriority')),
                                      bool(p.get('singleTidyExit')),p['id']))
        s.update(policy=p['id'],template=f'{cells}:{target}:{kind}')
    if missing:
        atomic_json(OUT/'min24-missing-contracts.json',sorted(map(list,set(map(tuple,missing)))))
        print(json.dumps({'missingContracts':sorted(set(map(tuple,missing)))},ensure_ascii=False),flush=True)
        return False
    route={**baseline,'id':'no80-min24-declared-v1','minimumTemplateTarget':24,
           'steps':deepcopy(baseline['steps'][:prefix])+suffix,
           'singleBoundaryBufferRescue':True,'extendedBoundaryBufferRescue':True,
           'realBoundaryRewind':True,'entryRecovery':True}
    route['bufferRescuePolicies']={k:[i for i in ids if 24<=policies[i]['target']<=64]
                                  for k,ids in baseline.get('bufferRescuePolicies',{}).items() if int(k)<80}
    used={s['policy'] for s in route['steps'] if s['kind']=='leaf'}
    used.update(i for ids in route['bufferRescuePolicies'].values() for i in ids)
    catalog={'policies':[policies[i] for i in sorted(used)]}
    report={**audit(route,catalog),'preservedPrefixSteps':prefix,'wholeGameSuccessRate':None,
            'plannedFive64Calls':sum(s['kind']=='leaf' and s['policyCells']==5 and s['target']==64 for s in route['steps'])}
    for name,value in [('route-min24',route),('catalog-min24',catalog),('min24-bound-audit',report)]:
        atomic_json(OUT/(name+'.json'),value)
    print(json.dumps(report,ensure_ascii=False),flush=True)
    return True


if __name__=='__main__':bind()
