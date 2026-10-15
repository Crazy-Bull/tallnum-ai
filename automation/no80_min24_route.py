"""Explicit min24 candidate. Nonstandard leaves require generated policies.

This file verifies ideal connections only; it makes no probability claim.
"""
from collections import Counter
from fractions import Fraction
import json
from .no80_route import ROOT,OUT
from .binary_routes import BinaryPlanner,verify_tree
from .route_search import Block
from .common import atomic_json
from .expected_routes import standard


def build():
    weights=json.loads((ROOT/'automation/runs/binary10240/minimum64/random-test-weights.json').read_text())
    weights['entries'].update(json.loads((ROOT/'automation/runs/binary10240/min24/weights.json').read_text())['entries'])
    planner=BinaryPlanner(OUT/'min24-declared-components',weights,maximum=20480,
                          minimum_leaf_target=24,maximum_leaf_target=64,objective='weight')
    def task(kind,n,v,*args):return (kind,n,v,5,*args)
    def node(t,rule,children,**extra):
        return {'task':list(t),'rule':rule,'children':children,
                'cost':str(sum((Fraction(c['cost']) for c in children),Fraction(0))),**extra}
    def leaf(t):
        kind,n,v,*_=t
        if v<24 or v>64 or n<5:raise ValueError(('Forbidden leaf',t))
        direct=planner.leaf(t)
        if direct:return direct
        if not standard(v) and (kind,v) not in {('single',28),('single',36),('single',44),
                                              ('match',28),('match',34),('match',36),
                                              ('match',44),('match',54),('match',56),('extend',36)}:
            raise ValueError(('Undeclared nonstandard contract',t))
        return {'task':list(t),'rule':'five-cell-policy','children':[],
                'cost':'1','template':f'5:{v}:{kind}','declaredNonstandard':True,
                'requiresGeneratedPolicy':True}
    def single(n,v):
        t=task('single',n,v)
        if v in (24,30,32,40,48,60) or (v==64 and n==5):return leaf(t)
        if v in (28,36,44):
            return node(t,'warm-single',[single(n,v//2),leaf(t)],warmStartOrdinary=v//2)
        if v in (14,18,22,34,54):
            precursor={14:72,18:96,22:112,34:176,54:272}[v]
            parts={14:(40,30),18:(60,30),22:(80,30),34:(80,60,30),54:(240,30)}[v]
            buffer=node(task('buffer',n-1,v//2,(),precursor),'buffer-choice',
                        [group(n-1,5*v,(),precursor,parts)],groupTarget=5*v)
            return node(t,'edge',[single(n,precursor),buffer])
        return node(t,'double',[single(n,v//2),match(n-1,v//2)])
    def group(n,total,anchors,blocker,parts):
        kind='group-match' if anchors else 'group'
        t=task(kind,n,total,anchors,blocker)
        x,*tail=parts
        if tail:
            return node(t,'buffer-add' if anchors else 'buffer-start',
                        [single(n,x),group(n-1,total,anchors+(x,),blocker,tuple(tail))])
        return node(t,'finish-group',[single(n,x)],anchors=list(anchors),groupTarget=total)
    def extend(n,a,b):
        v=a-b;t=task('extend',n,v,a,b)
        if v==b:return node(t,'matching-extension',[match(n,b)])
        if (a,b)==(96,32):return node(t,'reuse-boundary',[match(n,32),extend(n,96,64)])
        if v==64 and n>=6:
            return node(t,'ordinary-extension',[single(n,v)],a=a,b=b)
        if 24<=v<=64:return leaf(t)
        parts={(576,384):(128,64),(1728,1152):(384,128,64),
               (5120,3456):(1152,384,128)}.get((a,b))
        if parts:return node(t,'group-extension',[group(n,a,(b,),a,parts)])
        if b<v:return node(t,'reuse-boundary',[match(n,b),extend(n,a,2*b)])
        return node(t,'ordinary-extension',[single(n,v)],a=a,b=b)
    def match(n,v):
        t=task('match',n,v)
        if v==64 and n>=6:return node(t,'ordinary-match',[single(n,v)])
        if v in (24,28,30,32,34,36,40,44,48,54,56,60,64):return leaf(t)
        if v==136:
            return node(t,'match-sum',[single(n,48),
                        node(task('extend',n-1,88,v,48),'group-extension',
                             [group(n-1,v,(48,),v,(64,24))])])
        split={68:32,72:24,80:40,88:40,96:32,108:48,120:60,128:64,
               144:48,160:80,192:64,216:96,240:120,256:128,288:96,
               320:160,384:128,432:192,512:256,576:192,864:384,
               1728:576,5120:1728}[v]
        return node(t,'match-sum',[single(n,split),extend(n-1,v,split)])
    try:
        tree=match(9,5120)
        checked=verify_tree(tree,10,(Block(5120),))
        counts=Counter(s['template'] for s in checked['steps'] if s['kind']=='leaf')
        required=sorted({(s['target'],s['exit'],s['before'][-1][0])
                         for s in checked['steps'] if s['kind']=='leaf'})
        result={'minimumTemplateTarget':24,'maximumFiveCellTarget':64,
                'counts':dict(counts),'requiredContracts':required,
                'warmStarts':[{'target':s['target'],'ordinary':s['warmStartOrdinary'],'before':s['before']}
                              for s in checked['steps'] if s['kind']=='leaf' and s.get('warmStartOrdinary')],
                'requiresGeneratedPolicies':True,'wholeGameSuccessRate':None}
        atomic_json(OUT/'min24-declared-tree.json',tree)
        atomic_json(OUT/'min24-declared-steps.json',checked)
        atomic_json(OUT/'min24-declared-audit.json',result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    finally:planner.close()


if __name__=='__main__':build()
