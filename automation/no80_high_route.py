"""A shorter final match, keeping small anchors out of tight continuations."""
from fractions import Fraction
import argparse
import json
from .no80_route import ROOT, OUT
from .binary_routes import BinaryPlanner, verify_tree
from .route_search import Block
from .common import atomic_json


def build(spare_cell64=False):
    weights=json.loads((ROOT/'automation/runs/binary10240/minimum64/random-test-weights.json').read_text())
    weights['entries'].update(json.loads((ROOT/'automation/runs/binary10240/min24/weights.json').read_text())['entries'])
    p=BinaryPlanner(OUT/'high-components',weights,maximum=20480,minimum_leaf_target=24,maximum_leaf_target=64,objective='weight')
    def node(task,rule,children,**extra):
        return {'task':list(task),'rule':rule,'children':children,
                'cost':str(sum((Fraction(c['cost']) for c in children),Fraction(0))),**extra}
    def task(kind,n,v,*args):return (kind,n,v,5,*args)
    def single(n,v):
        t=task('single',n,v)
        if v in (4,6,10,12,16,24,30,32,40,48,60) or (v==64 and n==5):
            leaf=p.leaf(t)
            if leaf is None:raise ValueError(('Missing leaf',t))
            return leaf
        if v in (14,18,22,34,54):
            a={14:72,18:96,22:112,34:176,54:272}[v]
            parts={14:(40,30),18:(60,30),22:(80,30),34:(160,10),54:(240,30)}[v]
            buffer=node(task('buffer',n-1,v//2,(),a),'buffer-choice',
                        [group(n-1,5*v,(),a,parts)],groupTarget=5*v)
            return node(t,'edge',[single(n,a),buffer])
        return node(t,'double',[single(n,v//2),match(n-1,v//2)])
    def group(n,a,anchors,blocker,parts):
        kind='group-match' if anchors else 'group'
        t=task(kind,n,a,anchors,blocker)
        x,*tail=parts
        child=single(n,x)
        if tail:
            return node(t,'buffer-add' if anchors else 'buffer-start',
                        [child,group(n-1,a,anchors+(x,),blocker,tuple(tail))])
        return node(t,'finish-group',[child],anchors=list(anchors),groupTarget=a)
    def ordinary_extension(n,a,b):
        return node(task('extend',n,a-b,a,b),'ordinary-extension',[single(n,a-b)],a=a,b=b)
    def extend(n,a,b):
        v=a-b;t=task('extend',n,v,a,b)
        if v==b:return node(t,'matching-extension',[match(n,b)])
        if (a,b)==(96,32):
            # Matching consumes the anchor in place, so both tasks retain n
            # cells. 32 -> 64 -> Group(64+32)=96 avoids a 64 template.
            return node(t,'reuse-boundary',[match(n,32),extend(n,96,64)])
        if spare_cell64 and v==64 and n>=6:
            return ordinary_extension(n,a,b)
        direct=p.leaf(t)
        if direct:return direct
        if (a,b)==(192,64):
            return node(t,'reuse-boundary',[match(n,b),extend(n,a,2*b)])
        if (a,b)==(576,384):
            return node(t,'group-extension',[group(n,a,(b,),a,(128,64))])
        if (a,b)==(1728,1152):
            return node(t,'group-extension',[group(n,a,(b,),a,(384,128,64))])
        if (a,b)==(5120,3456):
            return node(t,'group-extension',[group(n,a,(b,),a,(1152,384,128))])
        if (a,b) in ((54,18),(144,48),(288,96),(384,128),(576,192),(864,384),(1728,576),(5120,1728)):
            return node(t,'reuse-boundary',[match(n,b),extend(n,a,2*b)])
        return ordinary_extension(n,a,b)
    def match(n,v):
        t=task('match',n,v)
        if spare_cell64 and v==64 and n>=6:
            return node(t,'ordinary-match',[single(n,64)])
        if v==136:
            # 40 + (48 + 48) would protect adjacent 40/48 during the
            # last producer, making every EDGE unsafe. 48 + 64 + 24
            # preserves distinct decimal heads throughout that workspace.
            return node(t,'match-sum',[single(n,48),
                node(task('extend',n-1,88,136,48),'group-extension',
                     [group(n-1,136,(48,),136,(64,24))])])
        if v in (16,24,30,32,40,48,60,64):
            leaf=p.leaf(t)
            if leaf:return leaf
        if v==18:return node(t,'match-sum',[single(n,6),extend(n-1,18,6)])
        if v==36:return node(t,'ordinary-match',[single(n,36)])
        split={14:6,22:10,28:12,34:10,44:12,56:24,68:28,88:40,136:40,
               54:18,72:24,80:40,96:32,108:48,120:60,128:64,144:48,160:80,
               240:120,256:128,320:160,512:256,
               192:64,216:96,288:96,384:128,432:192,576:192,864:384,1728:576,5120:1728}[v]
        return node(t,'match-sum',[single(n,split),extend(n-1,v,split)])
    try:
        tree=match(9,5120)
        checked=verify_tree(tree,10,(Block(5120),))
        atomic_json(OUT/'high-final5120-tree.json',tree)
        atomic_json(OUT/'high-final5120-steps.json',checked)
        print(json.dumps({'steps':len(checked['steps']),'leaves':sum(s['kind']=='leaf' for s in checked['steps'])}))
    finally:p.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spare-cell64',action='store_true',help='Use two 32 producers whenever six cells are available')
    build(parser.parse_args().spare_cell64)
