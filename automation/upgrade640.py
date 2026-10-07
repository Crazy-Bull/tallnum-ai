"""Use measured six-cell ordinary exits to upgrade seven-cell 640 contracts.

Standalone template statistics approximate route ranking only. Actual full
board entry/residual and random-pool behavior need separate simulation.
"""
import argparse
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path

from .common import atomic_json, fingerprint
from .binary_routes import BinaryPlanner,verify_tree
from .library import current_rule


ROOT=Path(__file__).resolve().parent.parent
WORK=ROOT/'automation/runs/seven640/six-cell-upgrade'


def prepare():
    WORK.mkdir(parents=True,exist_ok=True)
    source=ROOT/'automation/runs/binary10240/zero-risk-search/binary-plan.json'
    baseline={'entries':json.loads(source.read_text())['config']['weights']}
    snapshot=deepcopy(baseline);policies={}
    for key,entry in baseline['entries'].items():
        path=Path(entry['policy']).parent/(entry['policyId']+'.json')
        item=json.loads(path.read_text(encoding='utf-8'))
        if item['policySha256']!=entry['policySha256']:raise ValueError('Five-cell policy changed')
        policies[item['id']]=item
    for target in (32,40,48):
        work=ROOT/f'automation/runs/six{target}-alpha001'
        manifest=json.loads((work/'result.json').read_text())
        identity=json.loads((work/'export-identity.json').read_text())
        if manifest['aggressiveness']!=.01 or not manifest['valueIterationConverged']:
            raise ValueError('Six-cell variant is not complete')
        if fingerprint(manifest['policy'])!=manifest['policySha256']:raise ValueError('Six-cell policy changed')
        table=Path(manifest['table'])
        if fingerprint(table)!=identity['table']:raise ValueError('Six-cell table changed')
        atomic_json(Path(str(table)+'.rules.json'),{'tableSha256':identity['table'],
            'modelSha256':fingerprint(Path(str(table)+'.model.json')),'ruleSha256':current_rule()})
        stats=manifest['statistics'];cost=(Fraction(str(stats['u']))+Fraction(str(stats['v'])))/Fraction(str(stats['p']))
        for kind in ('single','match'):
            key=f'6:{target}:{kind}';identifier=f'six{target}-{kind}-a001'
            item={'id':identifier,'target':target,'cells':6,'exit':kind,'maxGoalCells':1,
                  'maxValue':48,'bases':[1,3,5,15],'policy':manifest['policy'],
                  'policySha256':manifest['policySha256'],'table':str(table),
                  'source':str(table.parent/'vi.values.bin'),'states':manifest['header']['states'],
                  'hashes':{'table':identity['table']},'ruleSha256':current_rule(),
                  'nativeBridge':manifest['nativeBridge'],'statistics':stats,
                  'variantAggressiveness':.01,'exitSemantics':'ordinary-single-via-virtual-boundary',
                  'sourceExit':'single','adapter':('ordinary-goal-then-equal-anchor-merge' if kind=='match' else 'ordinary-single'),
                  'workerKey':f'six{target}-single-a001','nativeExitOverride':'single','exclusiveCacheBuild':True,
                  'statisticsScope':'empty virtual-boundary iid entry; route entry and residuals unmeasured'}
            policies[identifier]=item
            snapshot['entries'][key]={'target':target,'exit':kind,'cells':6,
                'policyId':identifier,'policy':item['policy'],'policySha256':item['policySha256'],
                'alpha':.01,'maxValue':48,'statistics':stats,'p':stats['p'],'c':stats['u']+stats['v'],
                'weight':float(cost),'weightExact':str(cost),'adapter':item['adapter']}
    atomic_json(WORK/'baseline-weights.json',baseline)
    atomic_json(WORK/'weights.json',snapshot)
    atomic_json(WORK/'catalog.json',{'policies':list(policies.values())})
    return baseline,snapshot


def upgrade_tree(tree,snapshot):
    node=deepcopy(tree);changes=[]
    def visit(n):
        if n.get('template'):
            kind,space,target,*_=n['task'];key=f'6:{target}:{kind}'
            if space>=6 and key in snapshot['entries']:
                entry=snapshot['entries'][key]
                changes.append({'task':n['task'],'oldTemplate':n['template'],'newTemplate':key,
                                'oldCost':n['cost'],'newCost':entry['weightExact']})
                n.update(template=key,rule='six-cell-policy',policy=entry['policyId'],cost=entry['weightExact'])
        else:
            for c in n.get('children',[]):visit(c)
            if n.get('children'):n['cost']=str(sum((Fraction(c['cost']) for c in n['children']),Fraction(0)))
    visit(node)
    return node,changes


def compile_route(tree,catalog):
    steps=verify_tree(tree,7)['steps']
    for s in steps:
        if s['kind']=='leaf':s['policy']=catalog[s['template']]['policyId']
    return {'id':'seven640-six-cell-upgrade','version':2,'kind':'stages','cells':7,'target':640,'initialPrefix':[],'steps':steps}


def original_tree(weights):
    """Expand the saved 12-stage 640 witness into measured primitive exits."""
    saved=json.loads((ROOT/'automation/runs/seven640/minimum_peak/route.json').read_text())
    children=[]
    for stage in saved['stages']:
        target=stage['fiveCellTarget'];kind=stage['interface']
        before=stage['before'];space=7-sum(b[1] for b in before)
        # The opening tower is active input, not a protected prefix.
        if stage['stage']==1:space=7
        rest=[0]
        if kind=='extend':rest+=[before[-2][0],before[-1][0]]
        task=[kind,space,target,*rest]
        key=f'5:{target}:{kind}'
        if key in weights['entries']:
            e=weights['entries'][key]
            child={'task':task,'rule':'five-cell-policy','template':key,'policy':e['policyId'],
                   'cost':e['weightExact'],'children':[]}
        elif kind=='single' and target==64:
            leaves=[]
            for exit,n in [('single',space),('match',space-1)]:
                e=weights['entries'][f'5:32:{exit}']
                leaves.append({'task':[exit,n,32,0],'rule':'five-cell-policy',
                    'template':f'5:32:{exit}','policy':e['policyId'],'cost':e['weightExact'],'children':[]})
            child={'task':task,'rule':'double','children':leaves,'cost':str(sum((Fraction(l['cost']) for l in leaves),Fraction(0)))}
        else:raise ValueError('Unmeasured original interface: '+key)
        children.append(child)
    return {'task':['single',7,640,0],'rule':'original-stage-sequence','children':children,
            'cost':str(sum((Fraction(c['cost']) for c in children),Fraction(0)))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node-limit',type=int,default=50000)
    args=parser.parse_args()
    baseline,snapshot=prepare()
    plans=[]
    for name,weights in [('baseline',baseline),('optimized',snapshot)]:
        planner=BinaryPlanner(WORK/name,weights,maximum=1280,edge_depth=1,node_limit=args.node_limit)
        try:plan=planner.plan(640,7)
        finally:planner.close()
        print(json.dumps({'name':name,'status':plan['status'],'cost':plan['totalWeight'],'calls':plan['leafCalls']}),flush=True)
        if not plan['tree']['cost']:raise RuntimeError('No baseline/optimized structural route')
        plans.append(plan)
    tree,changes=upgrade_tree(plans[0]['tree'],snapshot)
    original=original_tree(baseline)
    direct,original_changes=upgrade_tree(original,snapshot)
    candidates={'original':original,'original-upgraded':direct,
                'baseline':plans[0]['tree'],'replaced':tree,'optimized':plans[1]['tree']}
    summary={'version':1,'cells':7,'target':640,'replacements':changes,'candidates':{},
             'originalReplacements':original_changes,
             'wholeGameStatistics':None,'globallyOptimal':False}
    for name,tree in candidates.items():
        trace=verify_tree(tree,7)
        route=compile_route(tree,snapshot['entries'])
        route['id']=f'seven640-{name}'
        atomic_json(WORK/(name+'-route.json'),route)
        atomic_json(WORK/(name+'-tree.json'),tree)
        summary['candidates'][name]={'additiveIndependentRetryEstimate':float(Fraction(tree['cost'])),
            'calls':sum(s['kind']=='leaf' for s in trace['steps']),
            'sixCellCalls':sum(s.get('policyCells')==6 for s in trace['steps']),
            'idealExitVerified':True,'wholeGameVerified':False}
    atomic_json(WORK/'comparison.json',summary)
    print(json.dumps(summary),flush=True)


if __name__=='__main__':main()
