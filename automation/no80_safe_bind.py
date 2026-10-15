"""Bind a structurally safe suffix to compatible measured real-board policies."""
from copy import deepcopy
import argparse
import json
from pathlib import Path
from .common import atomic_json
from .no80_route import OUT, EVIDENCE, audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route',type=Path,default=OUT/'route-high-ordinary.json')
    parser.add_argument('--output-prefix',default='safe-real')
    parser.add_argument('--check-next-entry',action='store_true')
    args=parser.parse_args()
    if Path(args.output_prefix).name!=args.output_prefix:raise ValueError('Output prefix must be a filename')
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    route=read(args.route)
    if any(s['kind']=='leaf' and s['target']<24 for s in route['steps']):
        raise ValueError('Template targets below 24 are forbidden')
    route['minimumTemplateTarget']=24
    baseline=read(EVIDENCE/'route.json')
    prefix=next(i for i,s in enumerate(baseline['steps']) if s['after']==[[5120,1,False]])+1
    catalogs=[read(OUT/name) for name in ('catalog-dynamic.json','catalog-v14.json','catalog-real-models.json')]
    policies={p['id']:p for c in catalogs for p in c['policies']}
    for directory in ('real-models','tidy-match-models','physical-extend-models','physical-single-models'):
        for file in (OUT/directory).glob('*/policy.json'):
            item=read(file);policies[item['id']]=item
    old=read(OUT/'route-v14.json')
    route.update(singleBoundaryBufferRescue=True,extendedBoundaryBufferRescue=True,realBoundaryRewind=True,
                 bufferRescuePolicies=deepcopy(old['bufferRescuePolicies']))
    if args.check_next_entry:route['checkNextLeafEntry']=True
    changes=[]
    for stage,s in enumerate(route['steps'][prefix:],prefix):
        # An EDGE anywhere also visits every pair inside the protected region.
        if s['kind']=='leaf' and any(a[0]//10>0 and a[0]//10==b[0]//10 for a,b in zip(s['before'],s['before'][1:])):
            raise ValueError(f'Unsafe protected EDGE pair at stage {stage}')
        if s['kind']!='leaf':continue
        if s['exit']=='extend' and s['before'][-1][0]==s['target']:
            # Equal matching performs the same checked normal-merge cascade.
            s['exit']='match'
        candidates=[p for p in policies.values() if p.get('cells',5)==s['policyCells']
                    and p['target']==s['target'] and p['exit']==s['exit']
                    and p.get('pendingValue') and p.get('successNoExtraCombos')
                    and p.get('singleProtectedHead') is None and not p.get('disableEdge')]
        if s['exit'] in ('single','match','extend'):
            exact=[p for p in policies.values() if p.get('cells',5)==5 and p['target']==s['target']
                   and p['exit']==s['exit'] and p.get('singleProtectedValue')==s['before'][-1][0]]
            if exact:candidates=exact
        if not candidates:raise ValueError(f'No compatible policy at stage {stage}: {s["template"]}')
        p=max(candidates,key=lambda p:(p.get('singleProtectedValue') is not None,
                                      bool(p.get('normalBoundaryPriority')),
                                      bool(p.get('singleTidyExit')),p['id']))
        if p['id']!=s['policy']:changes.append([stage,s['policy'],p['id']])
        s.update(policy=p['id'],policyCells=p.get('cells',5),template=f'{p.get("cells",5)}:{s["target"]}:{s["exit"]}')
    if route['steps'][:prefix]!=baseline['steps'][:prefix]:raise ValueError('Opening changed')
    used={s['policy'] for s in route['steps'] if s['kind']=='leaf'}
    used.update(i for ids in route['bufferRescuePolicies'].values() for i in ids)
    catalog={'policies':[policies[i] for i in sorted(used)]}
    report={**audit(route,catalog),'changedStages':changes,'preservedPrefixSteps':prefix,'wholeGameSuccessRate':None}
    for name,value in [('route-'+args.output_prefix,route),('catalog-'+args.output_prefix,catalog),(args.output_prefix+'-audit',report)]:
        atomic_json(OUT/(name+'.json'),value)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
