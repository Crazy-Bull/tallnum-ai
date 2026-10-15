"""Preserve the measured opening/controller and rebuild the final 5120 match."""
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import argparse
import json
from pathlib import Path

from .binary_routes import BinaryPlanner, verify_tree
from .common import atomic_json
from .route_search import Block

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'automation/runs/six-strict-single-002/validation-100-entry-gate-fix'
OUT = ROOT / 'automation/runs/no80-dynamic'


def audit(route, catalog):
    policies = {p['id']: p for p in catalog['policies']}
    used = {s['policy'] for s in route['steps'] if s['kind'] == 'leaf'}
    used.update(i for ids in route.get('bufferRescuePolicies', {}).values() for i in ids)
    for ident in used:
        p = policies[ident]
        if p.get('cells',5) < 5 or p['target'] < 24 or (p.get('cells',5) == 5 and p['target'] >= 80):
            raise ValueError('Forbidden route/rescue policy: ' + ident)
    for index,step in enumerate(route['steps']):
        if step['kind'] != 'leaf': continue
        p = policies[step['policy']]
        if step['target'] != p['target'] or int(step['template'].split(':')[1]) != p['target']:
            raise ValueError('Route target differs from policy: ' + p['id'])
        if p.get('warmStartOrdinary')!=step.get('warmStartOrdinary'):
            raise ValueError('Warm policy/entry contract differs: '+p['id'])
        if step.get('warmStartOrdinary'):
            previous=route['steps'][index-1] if index else {}
            warm=step['warmStartOrdinary']
            if (previous.get('kind')!='release' or previous.get('warmStartOrdinary')!=warm
                    or previous.get('after')!=step['before']
                    or previous.get('before')!=step['before']+[[warm,1,False]]):
                raise ValueError(f'Warm block must be explicitly constructed and released at stage {index}: {p["id"]}')
    return {'usedPolicyCount': len(used), 'forbiddenPolicies': [],
            'minimumTemplateTarget': 24,
            'leafCounts': dict(Counter(s['template'] for s in route['steps'] if s['kind']=='leaf'))}


def prepare(tree_file=None,ordinary_extensions=False):
    read = lambda p: json.loads(Path(p).read_text(encoding='utf-8'))
    original, catalog = read(EVIDENCE/'route.json'), read(EVIDENCE/'catalog.json')
    weights = read(ROOT/'automation/runs/binary10240/minimum64/random-test-weights.json')
    weights['entries'].update(read(ROOT/'automation/runs/binary10240/min24/weights.json')['entries'])
    model = read(ROOT/'automation/runs/binary10240/minimum64/binary-plan.json')
    tree = read(tree_file) if tree_file else deepcopy(model['tree']['children'][-1])
    planner = BinaryPlanner(OUT/'local-polish', weights, maximum=20480,
                            minimum_leaf_target=24, maximum_leaf_target=64, objective='weight')
    def polish(node):
        children = [polish(c) for c in node.get('children', [])]
        updated = {**node, 'children': children}
        if children:
            updated['cost'] = str(sum((Fraction(c['cost']) for c in children), Fraction(0)))
        direct = planner.leaf(tuple(node['task']))
        def peak(tree):
            return (int(tree['template'].split(':')[1]) if tree.get('template')
                    else max((peak(c) for c in tree.get('children',[])),default=0))
        if direct and peak(direct)<=peak(updated) and Fraction(direct['cost']) <= Fraction(updated['cost']):
            return direct
        return updated
    try:
        tree = polish(tree)
        suffix = verify_tree(tree, 10, (Block(5120),))['steps']
    finally:
        planner.close()
    if ordinary_extensions:
        converted=[]
        for s in suffix:
            if (s['kind']=='leaf' and s['exit']=='extend' and s['target']<64
                    and 10-sum(b[1] for b in s['before'])>=6
                    and f"5:{s['target']}:single" in weights['entries']):
                before=deepcopy(s['before']);after=deepcopy(s['after'])
                ordinary=before+[[s['target'],1,False]]
                single={**s,'exit':'single','template':f"5:{s['target']}:single",'after':ordinary}
                if before[-1][0]==s['target']:
                    single.update(after=after,singleConnectionAfter=after)
                    converted.append(single)
                else:
                    converted.extend([single,{'kind':'group','before':ordinary,'after':after,
                                               'indices':[len(before)-1,len(before)]}])
            else:converted.append(s)
        suffix=converted
    boundary = next(i for i,s in enumerate(original['steps']) if s['after']==[[5120,1,False]])
    route = {**original, 'id':'no80-dynamic-final5120-v1',
             'minimumTemplateTarget':24,
             'steps':deepcopy(original['steps'][:boundary+1])+suffix}
    # Retain the measured strict six-cell producers and live probability search.
    by_template = {(p.get('cells',5),p['target'],p['exit']):p for p in catalog['policies']}
    added = {}
    for s in suffix:
        if s['kind']!='leaf': continue
        cells,target,exit_kind = s['policyCells'],s['target'],s['exit']
        if (target in (32,40,48) and exit_kind in ('single','match')
                and s.get('availableCells',cells)>=6
                and 10-sum(b[1] for b in s['before'])>=6):
            cells = s['policyCells'] = 6
            s['template'] = f'6:{target}:{exit_kind}'
        item = by_template.get((cells,target, 'single' if cells==6 else exit_kind))
        if item is None:
            e = weights['entries'][s['template']]
            manifest = e.get('manifest',str(Path(e['policy']).parent/(e['policyId']+'.json')))
            item = read(ROOT/manifest if not Path(manifest).is_absolute() else manifest)
            added[item['id']] = item
        s['policy'] = item['id']
        if cells==6 and exit_kind=='match':
            s.update(exit='single',template=f'6:{target}:single',
                     singleConnectionAfter=deepcopy(s['after']),
                     connection='ordinary-single-then-real-automatic-equal-merge')
    catalog['policies'] += list(added.values())
    route['bufferRescuePolicies'] = {k:[i for i in ids if next(p for p in catalog['policies'] if p['id']==i)['target']<80]
                                    for k,ids in original.get('bufferRescuePolicies',{}).items() if int(k)<80}
    required = {s['policy'] for s in route['steps'] if s['kind']=='leaf'}
    required.update(i for ids in route['bufferRescuePolicies'].values() for i in ids)
    catalog['policies'] = [p for p in catalog['policies'] if p['id'] in required]
    report = audit(route,catalog)
    report.update(preservedPrefixSteps=boundary+1, replacementSteps=len(suffix),
                  newStaticPolicies=[p['id'] for p in added.values() if not p.get('pendingValue')],
                  final5120Split=[1728,1728,1664], wholeGameSuccessRate=None)
    suffix_name=('-high' if tree_file else '')+('-ordinary' if ordinary_extensions else '')
    for name,value in [('route',route),('catalog',catalog),('audit',report),('final5120-tree',tree)]:
        atomic_json(OUT/(name+suffix_name+'.json'),value)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--tree',type=Path)
    parser.add_argument('--ordinary-extensions',action='store_true')
    args=parser.parse_args();prepare(args.tree,args.ordinary_extensions)
