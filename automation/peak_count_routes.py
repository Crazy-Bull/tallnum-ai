"""Focus bounded optimization on subtrees containing the highest allowed leaf.

Every imported subtree is rebound and verified against its full ordered entrance.
This pass supplies incumbents; it never claims whole-route optimality by itself.
"""
import argparse
from collections import Counter
from fractions import Fraction
import json
from pathlib import Path
from .binary_routes import BinaryPlanner, structural_snapshot, verify_tree
from .common import atomic_json
from .route_search import Block


def reprice(tree, planner):
    children=[reprice(c,planner) for c in tree.get('children',[])]
    profile=list(planner.zero)
    if tree.get('template'):
        key=tree['template'];capacity,target,_=key.split(':')
        if int(target)<planner.minimum_leaf_target:
            raise ValueError('Imported tree uses a template below the configured minimum')
        profile[planner.rank_index[(int(capacity),int(target))]]=1
        cost=planner.snapshot['entries'][key]['weightExact']
    else:
        profile=[sum(c['profile'][i] for c in children) for i in range(len(profile))]
        cost=str(sum((Fraction(c['cost']) for c in children),Fraction(0)))
    return {**tree,'children':children,'profile':profile,'cost':cost,'complete':False}


def focus(plan, directory, *, node_limit=10000, maximum_task=1728, split_mode='all', objective='peak-count'):
    ceiling=max(int(k.split(':')[1]) for k in plan['leafCounts'])
    p=BinaryPlanner(directory,{'entries':plan['config']['weights']},maximum=plan['config']['maximum'],
                    minimum_leaf_target=plan['config'].get('minimumLeafTarget',2),
                    maximum_leaf_target=ceiling,edge_depth=plan['config']['edgeDepth'],
                    node_limit=node_limit,split_mode=split_mode,objective=objective)
    peak_index=p.five_peak_index if objective=='five-peak-count' else p.peak_index
    p.cells=plan['cells']
    zero_planner=None
    if objective=='five-peak-count' and peak_index is not None:
        peak=p.ranks[peak_index][1]
        entries={key:entry for key,entry in p.snapshot['entries'].items()
                 if not key.startswith(f'5:{peak}:')}
        if entries:
            zero_planner=BinaryPlanner(Path(directory)/'zero-peak-dp',{'entries':entries},maximum=p.maximum,
                                      minimum_leaf_target=p.minimum_leaf_target,
                                      maximum_leaf_target=max(int(k.split(':')[1]) for k in entries),
                                      edge_depth=p.depth,node_limit=node_limit,split_mode=split_mode,
                                      objective='five-peak-count')
            zero_planner.cells=p.cells;zero_planner.seed_mode=True
    p.cells=plan['cells'];audit=[]
    def improve(tree,entrance):
        # A finished subtree releases its scratch space. Use the actual free
        # cells, rather than a conservative budget inherited from its parent.
        available=p.cells-sum(b.span for b in entrance)
        tree={**tree,'task':(tree['task'][0],available,*tree['task'][2:])}
        if tree.get('rule')=='warm-single':
            return reprice({**tree,'children':[improve(tree['children'][0],entrance),tree['children'][1]]},p)
        board=entrance;children=[]
        for child in tree['children']:
            child=improve(child,board);children.append(child)
            board=tuple(Block(*b) for b in verify_tree(child,p.cells,board)['finalBoard'])
        tree=reprice({**tree,'children':children},p)
        key=json.dumps(tree['task'])
        cached=p.templates.get(key)
        if cached is None or p.score(tree)<p.score(cached):p.templates[key]=tree
        p.reuse_seed(tree['task'],entrance)
        if peak_index is None or not tree['profile'][peak_index] or tree['task'][1]<6 or tree['task'][2]>maximum_task:return tree
        if zero_planner is not None and zero_planner.capacity_possible(tree['task']):
            zero_planner.nodes=0;zero_planner.paused=False
            answer=zero_planner.solve(tree['task'],entrance)
            if answer['cost'] is not None:
                alternative=reprice(zero_planner.export(answer),p)
                verify_tree(alternative,p.cells,entrance)
                if p.score(alternative)<p.score(tree):tree=alternative
            if not tree['profile'][peak_index]:return tree
        p.templates[json.dumps(tree['task'])]=tree
        p.reuse_seed(tree['task'],entrance)
        p.seeds.update({k:v for k,v in p.memory.items() if v.get('cost') is not None});p.memory={};p.nodes=0;p.paused=False
        answer=p.solve(tree['task'],entrance)
        candidate=p.export(answer) if answer['cost'] is not None else tree
        verify_tree(candidate,p.cells,entrance)
        old=tree['profile'][peak_index];new=candidate['profile'][peak_index]
        audit.append({'task':tree['task'],'entrance':[b.json() for b in entrance],
                      'before':old,'after':new,'nodes':p.nodes,'complete':answer['complete']})
        print(json.dumps(audit[-1]),flush=True)
        if p.score(candidate)<p.score(tree):tree=candidate
        return tree
    try:
        tree=improve(reprice(plan['tree'],p),())
        trace=verify_tree(tree,p.cells)
        counts=Counter(s['template'] for s in trace['steps'] if s['kind']=='leaf')
        result={**plan,'tree':tree,'leafCounts':dict(sorted(counts.items())),
                'leafCalls':sum(counts.values()),'totalWeight':float(Fraction(tree['cost'])),
                'config':{**p.config,'cells':p.cells},'objective':p.objective,'status':'candidate',
                'difficultyProfile':[{'cells':c,'target':t,'count':tree['profile'][i]}
                     for i,(c,t) in enumerate(p.ranks) if tree['profile'][i]],
                'minimumPeakCountProvenInScope':False,'minimumDifficultyProvenInScope':False,
                'minimumFivePeakCountProvenInScope':False,
                'globallyOptimal':False,'idealConnectionsVerified':True,'executionVerified':False,
                'missingPolicies':[key for key in sorted(counts) if p.snapshot['entries'][key].get('structuralOnly')],
                'focusedOptimization':audit}
        result.pop('minimumPeakProvenInScope',None);result.pop('capSearch',None)
        atomic_json(Path(directory)/'binary-plan.json',result)
        atomic_json(Path(directory)/'ideal-connection-trace.json',trace)
        return result
    finally:
        p.close()
        if zero_planner is not None:zero_planner.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--node-limit',type=int,default=10000)
    parser.add_argument('--maximum-task',type=int,default=1728)
    parser.add_argument('--split-mode',choices=('guided','all'),default='all')
    args=parser.parse_args()
    result=focus(json.loads(args.plan.read_text()),args.directory,node_limit=args.node_limit,
                 maximum_task=args.maximum_task,split_mode=args.split_mode)
    print(json.dumps({'leafCalls':result['leafCalls'],'difficultyProfile':result['difficultyProfile']}))


if __name__=='__main__':main()
