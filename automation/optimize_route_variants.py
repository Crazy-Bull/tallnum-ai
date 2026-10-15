"""Choose per-stage aggressiveness by whole-route restart cost.

Exact Pareto search over supplied, certified variants of fixed stage routes.
Statistics assume independent template entries; this is not a game-level
optimality proof. No truncation is used in the variant search.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from .common import atomic_json, fingerprint
from .expected_routes import variant_alpha, weight, RULES
from .planner import Metrics
from .upgrade640 import WORK, ROOT


def frontier(points):
    result=[];best=float('inf')
    for point in sorted(points,key=lambda x:(-x['metrics'].p,x['metrics'].cost,tuple(x['policies']))):
        if point['metrics'].cost < best:
            result.append(point);best=point['metrics'].cost
    return result


def select_sequence(choices):
    """Keep every nondominated suffix; domination is safe for any prefix.

    A fixed prefix followed by suffix S has restart cost
    (cPrefix/pPrefix + cS)/pS. Higher pS and lower cS cannot worsen it.
    """
    points=[{'metrics':Metrics(1,0,0),'policies':[]}];sizes=[]
    for variants in reversed(choices):
        if not variants:raise ValueError('A stage has no usable variants')
        points=frontier([{'metrics':m.then(s['metrics']),
                          'policies':[identifier]+s['policies']}
                         for identifier,m in variants for s in points])
        sizes.append(len(points))
    return min(points,key=lambda x:(x['metrics'].expected,tuple(x['policies']))),sizes


def optimize(route,catalog):
    if route.get('version')!=2 or route.get('kind')!='stages':
        raise ValueError('Require an executable version-2 stage route')
    by_id={p['id']:p for p in catalog['policies']};choices=[];leaves=[]
    for step in route['steps']:
        if step['kind']!='leaf':continue
        if step['policy'] not in by_id:
            raise ValueError('Source stage policy is missing or uncertified: '+step['policy'])
        source=by_id[step['policy']];cells=step.get('policyCells',5)
        variants=[p for p in by_id.values() if p.get('cells',5)==cells
                  and p['target']==step['target'] and p['exit']==step['exit']
                  and p.get('maxGoalCells')==source.get('maxGoalCells')
                  and p.get('bases',[1,3,5,15])==source.get('bases',[1,3,5,15])
                  and p.get('maxValue',p['target'])>=max(48,step['target'])
                  and p.get('maxValue',p['target'])<=max(48,2*step['target'])]
        choices.append([(p['id'],Metrics(*(p['statistics'][k] for k in ('p','u','v')))) for p in variants])
        leaves.append(step)
    selected,sizes=select_sequence(choices)
    output=deepcopy(route);output['id']=route['id']+'-variants'
    decisions=[]
    for step,identifier,old,options in zip((s for s in output['steps'] if s['kind']=='leaf'),selected['policies'],leaves,choices):
        step['policy']=identifier;p=by_id[identifier]
        decisions.append({'target':step['target'],'exit':step['exit'],
            'cells':step.get('policyCells',5),'alpha':p['variantAggressiveness'],
            'maxValue':p.get('maxValue',p['target']),'policy':identifier,
            'previousPolicy':old['policy'],'availableVariants':len(options),
            'availableVariantIds':[identifier for identifier,_ in options]})
    return output,{'metrics':selected['metrics'].json(),'decisions':decisions,'suffixFrontierSizes':sizes,
        'optimalAmongSuppliedVariantsForFixedStructure':True,
        'approximation':'independent template-entry statistics; actual residuals and entry distributions unmeasured',
        'globallyOptimal':False}


def load_catalog(paths):
    policies={};excluded=[]
    for path in paths:
        for original in json.loads(Path(path).read_text())['policies']:
            p=deepcopy(original)
            try:
                weight(p['statistics']);alpha=variant_alpha(p)
                if p.get('cells',5)==5 and (p.get('ruleSha256') not in RULES or
                    not p.get('petsc',{}).get('verified') or p.get('petsc',{}).get('exitEvaluationRounds',0)<2
                    or p.get('exitSemantics') not in ('success-board-v2','success-board-clean-v3')):
                    raise ValueError('Uncertified five-cell exit')
                if p['id'] in policies and policies[p['id']]['policySha256']==p['policySha256']:continue
                if fingerprint(p['policy'])!=p['policySha256']:raise ValueError('Policy hash changed')
                p['variantAggressiveness']=alpha;policies[p['id']]=p
            except (ValueError,KeyError,OSError) as error:
                excluded.append({'id':p.get('id'),'reason':str(error)})
    return {'policies':list(policies.values())},excluded


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--names',nargs='+',default=['original','original-upgraded','optimized'])
    parser.add_argument('--route',type=Path,help='Optional executable stage route, instead of the default 640 candidates')
    parser.add_argument('--catalog',type=Path,action='append',help='Supply one or more policy catalogs')
    parser.add_argument('--output-dir',type=Path,default=WORK)
    args=parser.parse_args()
    paths=args.catalog or [WORK/'catalog.json',
                           ROOT/'automation/runs/binary10240/additional-templates/catalog.json',
           ROOT/'automation/runs/binary10240/additional-templates/bounds48/catalog.json']
    sources=[{'path':str(path.resolve()),'sha256':fingerprint(path)} for path in paths]
    catalog,excluded=load_catalog(paths)
    atomic_json(args.output_dir/'catalog.json',catalog)
    reports={}
    inputs=[(args.route.stem,args.route)] if args.route else [(name,WORK/(name+'-route.json')) for name in args.names]
    for name,path in inputs:
        route=json.loads(path.read_text())
        upgraded,report=optimize(route,catalog)
        atomic_json(args.output_dir/(name+'-variants-route.json'),upgraded)
        reports[name]=report
        print(json.dumps({'route':name,'metrics':report['metrics'],
                          'stageCount':len(report['decisions'])}),flush=True)
    atomic_json(args.output_dir/'variant-comparison.json',{'routes':reports,'excluded':excluded,
        'sources':sources,
        'recommended':min(reports,key=lambda n:reports[n]['metrics']['expectedTotalDrops'])})


if __name__=='__main__':main()
