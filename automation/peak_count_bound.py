"""Optimistic integer DP lower bound for peak leaf calls in the binary grammar.

Drops protected-prefix collision checks. Thus its minimum is a lower bound,
not an executable route. A matching verified route closes the proof gap.
All leaves still have five-cell capacity. No four-cell primitives are used.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
from .expected_routes import standard
from .binary_routes import verify_tree
from .common import atomic_json

INF=10**6

class RelaxedPeakBound:
    def __init__(self, plan, *, maximum=None, edge_depth=None, ceiling=None):
        if any(not key.startswith('5:') for key in plan['leafCounts']):
            raise ValueError('This bound requires a pure five-cell library')
        verify_tree(plan['tree'],plan['cells'])
        self.ceiling=ceiling if ceiling is not None else max(int(k.split(':')[1]) for k in plan['leafCounts'])
        self.minimum_leaf_target=plan['config'].get('minimumLeafTarget',2)
        self.declared_targets={int(k.split(':')[1]) for k,e in plan['config'].get('weights',{}).items()
                               if e.get('declaredNonstandard')}
        self.maximum=maximum or plan['config']['maximum']
        self.depth=plan['config']['edgeDepth'] if edge_depth is None else edge_depth
        if self.maximum<plan['config']['maximum'] or self.depth<plan['config']['edgeDepth'] or self.depth>8:
            raise ValueError('Proof overrides may only expand the source scope, up to EDGE depth eight')
        self.incumbents={};self.nodes=0
        def walk(t):
            leaf_target=int(t['template'].split(':')[1]) if t.get('template') else 0
            if t.get('template') and leaf_target < self.minimum_leaf_target:
                raise ValueError('Incumbent uses a template below the configured minimum')
            count=INF if leaf_target>self.ceiling else int(leaf_target==self.ceiling)+sum(walk(c) for c in t['children'])
            kind,n,v,*r=t['task']
            if kind=='extend':key=('e',n,r[1],r[2],r[0])
            elif kind in ('single','match'):key=(kind[0],n,v,r[0])
            else:return count
            if count>=INF:return INF
            for depth in range(key[-1],self.depth+1):
                expanded=(*key[:-1],depth)
                self.incumbents[expanded]=min(count,self.incumbents.get(expanded,INF))
            return count
        walk(plan['tree'])
        self.choices={}

    def bound(self,n,kind='m'):
        return 0 if n<5 else self.ceiling*(3**(n-5) if kind=='m' else (1 if n==5 else 2*3**(n-6)))

    def leaf(self,t):
        return int(t==self.ceiling) if (standard(t) or t in self.declared_targets) and self.minimum_leaf_target<=t<=self.ceiling else INF

    def values(self,maximum):
        return [x for x in range(2,min(maximum,self.maximum)+1) if x%2==0 or x==15]

    @lru_cache(None)
    def solve(self,key):
        self.nodes+=1
        if self.nodes%50000==0:print(json.dumps({'relaxedStates':self.nodes,'task':key}),flush=True)
        kind,n,t,*r=key
        if n<5:return INF
        if kind in ('s','m'):
            d=r[0]
            if t>self.bound(n,kind) or t>self.maximum or t<2 or (t%2 and t!=15):return INF
            if kind=='s' and n<=6 and not standard(t):return INF
            best=min(self.leaf(t),self.incumbents.get(key,INF))
        elif kind=='e':
            b,d=r;diff=t-b
            if diff<2 or b<2 or t>self.maximum or t>max(b,2*self.bound(n))+self.bound(n):return INF
            best=min(self.leaf(diff),self.incumbents.get(key,INF))
        else:
            last,count,d=r
            if t<2 or count>=5 or t>self.bound(n):return INF
            best=INF
        if best==0:return 0
        def offer(*children):
            nonlocal best
            cost=0
            for child in children:
                cost+=self.solve(child)
                if cost>=best:return
            if cost<best:
                best=cost;self.choices[key]=children
        if kind=='s':
            if n>5 and t%2==0:
                offer(('s',n,t//2,d),('m',n-1,t//2,d))
                if d:
                    for precursor in self.values(min(5*t+9,self.bound(n,'s'))):
                        if precursor<5*t:continue
                        for total in range(5*t,min(5*t+9,self.maximum)+1):
                            if total!=precursor:offer(('s',n,precursor,d-1),('g',n-1,total,0,0,d-1))
        elif kind=='m':
            if n>5:
                xs=self.values(min(t-2,self.bound(n,'s')))
                xs.sort(key=lambda x:(abs(3*x-t),x))
                for x in xs:offer(('s',n,x,d),('e',n-1,t,x,d))
                offer(('s',n,t,d))
        elif kind=='e':
            if diff==b:offer(('m',n,b,d))
            if b<diff:offer(('m',n,b,d),('e',n,t,2*b,d))
            offer(('s',n,diff,d))
            offer(('g',n,diff,b,1,d))
        else:
            if count and t!=last:offer(('s',n,t,d))
            if n>5 and count<4:
                for x in self.values(min(t-2,self.bound(n,'s'))):
                    if count and x==last:continue
                    offer(('s',n,x,d),('g',n-1,t-x,x,count+1,d))
        return best


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--maximum',type=int);parser.add_argument('--edge-depth',type=int)
    args=parser.parse_args();plan=json.loads(args.plan.read_text());dp=RelaxedPeakBound(plan,maximum=args.maximum,edge_depth=args.edge_depth)
    root=('s',plan['cells'],plan['target'],dp.depth)
    lower=dp.solve(root);upper=dp.incumbents[root]
    result={'target':plan['target'],'cells':plan['cells'],'ceiling':dp.ceiling,
            'lowerBound':None if lower==INF else lower,'verifiedCandidateCount':upper,
            'gapClosed':lower==upper,'states':dp.nodes,'maximum':dp.maximum,
            'edgeDepth':root[-1],'scope':'optimistic relaxation of finite ordered binary/Group/EDGE grammar; protected-prefix collisions ignored; all leaves five cells',
            'gameWideOptimalityProven':False,'sourcePlan':str(args.plan),
            'stageBounds':{'first5120':dp.solve(('s',10,5120,dp.depth)),
                'match5120':dp.solve(('m',9,5120,dp.depth)),
                'match1728':dp.solve(('m',8,1728,dp.depth)),
                'extend1664':dp.solve(('e',8,5120,3456,dp.depth))} if plan['target']==10240 else {}}
    atomic_json(args.output,result);print(json.dumps(result),flush=True)


if __name__=='__main__':main()
