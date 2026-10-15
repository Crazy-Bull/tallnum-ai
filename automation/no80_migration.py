"""Reconcile a candidate with the measured route's model and connection rules."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from .common import atomic_json
from .library import table_header
from .no80_route import OUT, EVIDENCE, audit


def migrate(route, catalog, replacements):
    route,catalog=deepcopy(route),deepcopy(catalog)
    route['minimumTemplateTarget']=24
    policies={p['id']:p for p in catalog['policies']}
    changes=[]
    for step in route['steps']:
        if step['kind']!='leaf':continue
        item=policies[step['policy']]
        header=table_header(item['table'])
        if not header['successNoExtraCombos']:
            choices=[p for p in replacements if p.get('cells',5)==step['policyCells']
                     and p['target']==step['target'] and p['exit']==step['exit']
                     and p.get('successNoExtraCombos') is True and p.get('maxValue',0)>=48
                     and p.get('bases')==item.get('bases')]
            if not choices:raise ValueError('Missing clean replacement: '+item['id'])
            replacement=min(choices,key=lambda p:(not bool(p.get('petsc',{}).get('verified')),p['id']))
            changes.append({'old':item['id'],'new':replacement['id'],'target':step['target']})
            policies[replacement['id']]=replacement
            step['policy']=replacement['id']
    used={s['policy'] for s in route['steps'] if s['kind']=='leaf'}
    used.update(i for ids in route.get('bufferRescuePolicies',{}).values() for i in ids)
    catalog['policies']=[policies[i] for i in sorted(used)]
    report=audit(route,catalog)
    original=json.loads((EVIDENCE/'route.json').read_text())
    boundary=next(i for i,s in enumerate(original['steps']) if s['after']==[[5120,1,False]])+1
    if route['steps'][:boundary]!=original['steps'][:boundary]:
        raise ValueError('Measured opening/prefix changed')
    report.update(preservedPrefixSteps=boundary,cleanReplacements=changes,
                  below24LeafCounts=dict(Counter(s['template'] for s in route['steps']
                                                if s['kind']=='leaf' and s['target']<24)),
                  nonDynamicPolicies=[p['id'] for p in catalog['policies'] if not p.get('pendingValue')],
                  wholeGameSuccessRate=None)
    for item in catalog['policies']:
        if not table_header(item['table'])['successNoExtraCombos']:
            raise ValueError('Dirty route/rescue model: '+item['id'])
    return route,catalog,report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route',type=Path,default=OUT/'route-high-ordinary.json')
    parser.add_argument('--catalog',type=Path,default=OUT/'catalog-dynamic.json')
    parser.add_argument('--replacements',type=Path,default=OUT/'clean-migration/catalog.json')
    args=parser.parse_args()
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    r,c,a=migrate(read(args.route),read(args.catalog),read(args.replacements)['policies'])
    for name,value in [('route-migrated',r),('catalog-migrated',c),('migration-audit',a)]:
        atomic_json(OUT/(name+'.json'),value)
    print(json.dumps(a,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
