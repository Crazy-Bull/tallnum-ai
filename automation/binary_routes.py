"""Binary, space-aware single/match/extend/buffer contract search.

Only measured STANDARD five/six-cell policies are leaves. Buffer is a Group
construction with existing ordinary members, never a nested Group. Reverse
ordinary splits are forbidden; buffer is exempt. Costs approximate independent
local retries, not whole-game stochastic execution. EDGE nesting and numeric
domains are explicitly bounded; missing leaf statistics remain unknown.
"""
from collections import Counter
from fractions import Fraction
import argparse
import json
from pathlib import Path
import sqlite3

from .common import atomic_json, fingerprint
from .expected_routes import standard
from .peak_bounds import arithmetic_peak_bounds
from .route_search import identity, normalize, edge_board, Block, template_key

VERSION = 'binary-space-buffer-1'


def verify_tree(tree, cells, entrance=()):
    """Replay every connection on the full ordered protected board.

    Leaves remain stochastic contracts, not invented deterministic policies.
    This checks their ideal success exits only. Residuals/RNG need simulation.
    """
    board=tuple(entrance)
    steps=[]
    def record(kind, before, **extra):
        steps.append({'kind':kind,'before':[b.json() for b in before],
                      'after':[b.json() for b in board],**extra})
    def group(count):
        nonlocal board
        before=board
        members=board[-count:]
        if not 2<=count<=5 or len(members)!=count or any(b.group for b in members) or any(b.span!=1 for b in members):
            raise ValueError('Illegal Group members')
        if any(b.group for b in board[:-count]):
            raise ValueError('Only one Group is allowed')
        board=normalize((*board[:-count],Block(sum(b.value for b in members),count,True)))
        record('group',before,indices=list(range(len(before)-count,len(before))))
    def visit(node):
        nonlocal board
        kind,n,target,*rest=node['task']
        before=board
        occupied=sum(b.span for b in board)
        if occupied+n>cells:
            raise ValueError(f'Workspace exceeds board: {node["task"]}, {before}')
        if kind=='match' and (not board or board[-1].value!=target):
            raise ValueError('Match entrance mismatch')
        if kind=='extend' and (len(board)<2 or [b.value for b in board[-2:]]!=list(rest[1:3])):
            raise ValueError('Extend entrance mismatch')
        if node['rule'] in ('five-cell-policy','six-cell-policy'):
            capacity=int(node['template'].split(':')[0])
            if capacity not in (5,6) or not standard(target) or n<capacity:
                raise ValueError('Invalid measured leaf workspace')
            if kind=='single' or kind=='match': board=normalize((*board,Block(target)))
            elif kind=='extend':
                a,b=rest[1:3]
                if board[-1].group or board[-1].span!=1:
                    raise ValueError('Extend requires ordinary boundary')
                board=normalize((*board[:-1],Block(a,2,True)))
            record('leaf',before,target=target,exit=kind,template=node['template'],policyCells=capacity,availableCells=n)
        else:
            for child in node['children']:visit(child)
            rule=node['rule']
            if rule=='edge':
                previous=board
                board=edge_board(board)
                record('edge',previous)
            elif rule=='finish-group':group(len(node['anchors'])+1)
            elif rule=='ordinary-extension':group(2)
        if kind in ('single','match'):
            expected=normalize((*before,Block(target)))
            if board!=expected:
                raise ValueError(f'{kind} exit mismatch at {target}: {board}, expected {expected}')
        elif kind=='extend':
            expected=normalize((*before[:-2],Block(2*rest[1])))
            if board!=expected:raise ValueError('Extend exit mismatch')
        elif kind in ('group','group-match'):
            anchors=tuple(rest[1])
            if kind=='group-match':
                prefix=before[:-len(anchors)] if anchors else before
                if board!=normalize((*prefix,Block(target,2,True))):
                    raise ValueError('Group match exit mismatch')
                return
            if anchors and board[:-1]!=before[:-len(anchors)]:
                raise ValueError(f'Group prefix mismatch at {node["task"]}: {before} -> {board}')
            if not board or not board[-1].group or board[-1].value!=target:
                raise ValueError(f'Group result mismatch at {node["task"]}: {before} -> {board}')
        elif kind=='buffer':
            if not board or not board[-1].group or board[-1].value//10!=target:
                raise ValueError('Buffer exit mismatch')
        if sum(b.span for b in board)>=cells:
            raise ValueError('Physical board is full')
    visit(tree)
    return {'idealExitVerified':True,'finalBoard':[b.json() for b in board],
            'steps':steps,'maximumProtectedCells':max((sum(b[1] for b in s['after']) for s in steps),default=0),
            'stochasticExecutionVerified':False}


class BinaryPlanner:
    def __init__(self, directory, snapshot, *, maximum=13824, edge_depth=5,
                 node_limit=150000, split_mode='guided', progress=None, minimum_leaf_target=2):
        if not 2 <= maximum <= 65535 or not 0 <= edge_depth <= 8:
            raise ValueError('Invalid numerical/EDGE bound')
        if split_mode not in ('guided','all') or node_limit < 0:
            raise ValueError('Invalid search mode/budget')
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.snapshot=snapshot
        if minimum_leaf_target<2:raise ValueError('Invalid minimum leaf target')
        self.minimum_leaf_target=minimum_leaf_target
        self.maximum,self.depth,self.limit=maximum,edge_depth,node_limit
        self.mode,self.progress=split_mode,progress
        self.nodes=0
        self.paused=False
        self.memory={}
        self.seeds={}
        self.seed_mode=False
        self.cells=10
        self.config={'version':VERSION,'source':fingerprint(__file__),'weights':snapshot['entries'],
                     'rules':{name:fingerprint(Path(__file__).parent/name) for name in ('game.py','route_search.py')},
                     'maximum':maximum,'edgeDepth':edge_depth,'splitMode':split_mode,
                     'minimumLeafTarget':minimum_leaf_target,
                     'ordinaryOrder':'left-target>=right-target','bufferOrder':'exempt',
                     'smallSpace':'measured-policies-with-explicit-capacity'}
        self.run=identity(self.config)
        self.db=sqlite3.connect(self.directory/'binary-search.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS binary_memo (run TEXT,key TEXT,answer TEXT,PRIMARY KEY(run,key))')
        self.bounds=arithmetic_peak_bounds((2,4,8,6,10,15),(),maximum)['costs']
        self.standard_values=[v for v in range(2,maximum+1) if standard(v)]
        self.unit_cost=min(Fraction(e['weightExact'])/int(k.split(':')[1])
                           for k,e in snapshot['entries'].items())

    def lower_bound(self, task):
        kind,n,target,*rest=task
        mass=target
        if kind=='single' and not standard(target) and target%2==0:
            base=target
            while base%2==0:base//=2
            # A new ordinary nonstandard odd base first enters through EDGE.
            # Its smallest possible output is 2*base, losing at least 18*base
            # of input mass. Normal doubling conserves the remainder.
            mass+=18*base
        if kind=='buffer': mass=max(0,10*target-sum(rest[1]))
        elif kind in ('group','group-match'): mass=max(0,target-sum(rest[1]))
        return self.unit_cost*mass

    def close(self):
        self.db.commit()
        self.db.close()

    def candidates(self, low, high):
        if self.mode=='all':
            return [v for v in range(max(2,low),min(high,self.maximum)+1)
                    if v==15 or v%2==0]
        values={v for v in self.standard_values if low<=v<=high}
        middle=(low+high)//2
        for v in (low,low+1,low+2,high,high-1,high-2,middle,middle-1,middle+1):
            if low<=v<=high and (v==15 or v>=2 and v%2==0):
                values.add(v)
        return sorted(values)

    def seed_candidates(self, values):
        families={}
        for v in values:
            if not standard(v):continue
            base=v
            while base%2==0:base//=2
            families[base]=max(v,families.get(base,0))
        return [families[b] for b in sorted(families)]

    def leaf(self, task):
        kind,n,target,*rest=task
        if n<5 or target<self.minimum_leaf_target or kind not in ('single','match','extend') or not standard(target):
            return None
        options=[(key,entry) for capacity in (5,6) if n>=capacity
                 for key in (f'{capacity}:{target}:{kind}',)
                 if (entry:=self.snapshot['entries'].get(key)) is not None]
        if not options:
            return None
        key,entry=min(options,key=lambda pair:Fraction(pair[1]['weightExact']))
        return {'task':task,'cost':entry['weightExact'],'rule':('six-cell-policy' if key.startswith('6:') else 'five-cell-policy'),
                'children':[],'template':key,'policy':entry['policyId'],'complete':True}

    def solve(self, task, entrance=()):
        task=tuple(task)
        entrance=tuple(entrance)
        key=json.dumps([task,[b.json() for b in entrance]],separators=(',',':'))
        if key in self.memory:
            return self.memory[key]
        row=self.db.execute('SELECT answer FROM binary_memo WHERE run=? AND key=?',(self.run,key)).fetchone()
        if row:
            answer=json.loads(row[0])
            if answer['complete']:
                self.memory[key]=answer
                return answer
        kind,n,target,*rest=task
        if kind in ('single','match','extend') and target<self.minimum_leaf_target:
            return {'task':task,'cost':None,'complete':True}
        if n<5 or target<(1 if kind=='buffer' else 2) or target>self.maximum or (kind in ('single','match','extend') and target%2 and target!=15):
            return {'task':task,'cost':None,'complete':True}
        # Within this grammar an empty buffer needs at least six cells.
        # A new ordinary nonstandard base must use EDGE, which reserves one
        # cell for its precursor. Doubling cannot introduce a new odd base.
        # This is a scope-specific impossibility, not a game-wide assertion.
        if kind=='single' and n<=6 and not standard(target):
            return {'task':task,'cost':None,'complete':True}
        if sum(b.span for b in entrance)+n>self.cells:
            return {'task':task,'cost':None,'complete':True}
        if kind=='match' and (not entrance or entrance[-1].value!=target):
            return {'task':task,'cost':None,'complete':True}
        if kind=='extend' and (len(entrance)<2 or [b.value for b in entrance[-2:]]!=list(rest[1:3]) or entrance[-1].group):
            return {'task':task,'cost':None,'complete':True}
        if kind in ('group','group-match','buffer') and rest[1]:
            anchors=tuple(rest[1])
            if tuple(b.value for b in entrance[-len(anchors):])!=anchors or any(b.group for b in entrance[-len(anchors):]):
                return {'task':task,'cost':None,'complete':True}
        if self.limit and self.nodes>=self.limit:
            self.paused=True
            return {'task':task,'cost':None,'complete':False}
        self.nodes+=1
        if self.progress and self.nodes%10000==0:
            self.progress({'nodes':self.nodes,'memo':len(self.memory)})
        best=self.leaf(task) or self.seeds.get(key)
        if best and best['rule'] in ('five-cell-policy','six-cell-policy'):
            if kind=='extend':
                end=normalize((*entrance[:-1],Block(rest[1],2,True)))
            else:end=normalize((*entrance,Block(target)))
            best={**best,'entrance':[b.json() for b in entrance],'exitBoard':[b.json() for b in end]}
        complete=True

        def offer(rule, child_tasks, **extra):
            nonlocal best,complete
            if self.seed_mode and best is not None and best['rule'] not in ('five-cell-policy','six-cell-policy') and kind=='single':
                return
            if best is not None and sum((self.lower_bound(t) for t in child_tasks),Fraction(0))>=Fraction(best['cost']):
                return
            children=[]
            cost=Fraction(0)
            board=entrance
            for child_task in child_tasks:
                child=self.solve(child_task,board)
                complete=complete and child['complete']
                if child['cost'] is None:
                    return
                children.append(json.dumps([tuple(child_task),[b.json() for b in board]],separators=(',',':')))
                board=tuple(Block(*b) for b in child['exitBoard'])
                cost+=Fraction(child['cost'])
                if best is not None and cost+sum((self.lower_bound(t) for t in child_tasks[len(children):]),Fraction(0))>=Fraction(best['cost']):
                    return
            if rule=='edge':board=edge_board(board)
            elif rule in ('finish-group','ordinary-extension'):
                count=len(extra['anchors'])+1 if rule=='finish-group' else 2
                members=board[-count:]
                if len(members)!=count or not 2<=count<=5 or any(b.group or b.span!=1 for b in members) or any(b.group for b in board[:-count]):return
                board=normalize((*board[:-count],Block(sum(b.value for b in members),count,True)))
            if kind in ('single','match'):
                if board!=normalize((*entrance,Block(target))):return
            elif kind=='extend':
                if board!=normalize((*entrance[:-2],Block(2*rest[1]))):return
            elif kind in ('group','group-match'):
                anchors=tuple(rest[1])
                prefix=entrance[:-len(anchors)] if anchors else entrance
                if kind=='group-match':
                    if board!=normalize((*prefix,Block(target,2,True))):return
                elif not board or not board[-1].group or board[-1].value!=target or board[:-1]!=prefix:return
            elif kind=='buffer':
                anchors=tuple(rest[1])
                prefix=entrance[:-len(anchors)] if anchors else entrance
                if not board or not board[-1].group or board[-1].value//10!=target or board[:-1]!=prefix:return
            if sum(b.span for b in board)>=self.cells:return
            if best is None or cost<Fraction(best['cost']):
                best={'task':task,'cost':str(cost),'rule':rule,'children':children,
                      'complete':True,'entrance':[b.json() for b in entrance],
                      'exitBoard':[b.json() for b in board],**extra}

        if kind=='single':
            depth=rest[0]
            if n>5:
                half=target//2
                if target%2==0 and (half==15 or half%2==0):
                    offer('double',[('single',n,half,depth),('match',n-1,half,depth)])
                if depth and target%2==0 and (not self.seed_mode or not standard(target)):
                    precursors=[v for v in range(5*target,min(5*target+9,self.maximum)+1) if v%2==0]
                    precursors.sort(key=lambda v:(self.bounds.get(v,10**9),v))
                    for value in precursors:
                        offer('edge',[('single',n,value,depth-1),
                                      ('buffer',n-1,target//2,depth-1,(),value)],
                              bufferRange=[5*target,min(5*target+9,self.maximum)])
        elif kind=='match':
            depth=rest[0]
            if n>5:
                # The right extend's target is target-x, hence x>=target-x.
                xs=self.candidates((target+1)//2,target-2)
                if self.seed_mode:xs=[x for x in xs if standard(x)]
                def priority(x):
                    left=self.snapshot['entries'].get(template_key(x,'single'))
                    right=self.snapshot['entries'].get(template_key(target-x,'extend'))
                    return (not (left and right),
                            Fraction(left['weightExact'])+Fraction(right['weightExact']) if left and right else Fraction(0),
                            x!=target//2,not standard(x),x)
                xs.sort(key=priority)
                if self.seed_mode:
                    xs=self.seed_candidates(xs)
                for x in xs:
                    offer('match-sum',[('single',n,x,depth),('extend',n-1,target-x,depth,target,x)])
                # This is a unary interface adaptation, not a decomposition:
                # a full ordinary construction can finish against its anchor.
                if not self.seed_mode or best is None and standard(target):
                    offer('ordinary-match',[('single',n,target,depth)])
        elif kind=='extend':
            depth,a,b=rest
            if a-b!=target or b<2:
                raise ValueError('Invalid extension entry')
            if target==b:
                offer('matching-extension',[('match',n,b,depth)])
            # Complete B with ordinary members before making the Group. A
            # pre-built Group(target) cannot be nested inside Group(B,...).
            offer('group-extension',[('group-match',n,a,depth,(b,),a)])
            if target!=b and (not self.seed_mode or standard(target)):
                offer('ordinary-extension',[('single',n,target,depth)],a=a,b=b)
            if n>5:
                # Reusing B doubles the boundary without consuming another
                # cell. Crucially, the second child still has n cells.
                if b<target and target-b<=b:
                    offer('reuse-boundary',[('match',n,b,depth),
                                            ('extend',n,target-b,depth,a,2*b)])
        elif kind=='buffer':
            depth,anchors,blocker=rest
            anchors=tuple(anchors)
            # target is the DECIMAL PREFIX, not an ordinary tile target.
            for total in range(10*target,min(10*target+9,self.maximum)+1):
                if total==blocker:
                    continue
                offer('buffer-choice',[('group',n,total,depth,anchors,blocker)],groupTarget=total)
        elif kind in ('group','group-match'):
            depth,anchors,blocker=rest
            anchors=tuple(anchors)
            remaining=target-sum(anchors)
            if 1<=len(anchors)<=4 and remaining>=2:
                # Group requires ordinary members; never combine an existing
                # Group. If a new component equals the last anchor, its match
                # merges them and gives the updated member list.
                if anchors[-1]!=remaining and (not self.seed_mode or standard(remaining)):
                    offer('finish-group',[('single',n,remaining,depth)],anchors=list(anchors),groupTarget=target)
                if n>5 and len(anchors)<4:
                    xs=self.candidates(2,remaining-2)
                    if self.seed_mode:xs=self.seed_candidates(x for x in xs if x<=anchors[-1] and x!=anchors[-1])
                    xs.sort(key=lambda x:(not standard(remaining-x),not standard(x),-x))
                    for x in xs:
                        if x>anchors[-1]:
                            continue  # Canonical large-first ordinary members.
                        if x==anchors[-1]:
                            continue  # Explicit normal-merge alternatives are not assumed Group leaves.
                        offer('buffer-add',[('single',n,x,depth),
                                            (kind,n-1,target,depth,anchors+(x,),blocker)])
            elif not anchors and n>5:
                xs=self.candidates(2,target-2)
                if self.seed_mode:xs=self.seed_candidates(xs)
                xs.sort(key=lambda x:(not standard(target-x),not standard(x),-x))
                for x in xs:
                    # No right-target<=left-target test here: Group total may
                    # exceed its adjacent ordinary blocker (e.g. 274 vs 272).
                    offer('buffer-start',[('single',n,x,depth),
                                          (kind,n-1,target,depth,(x,),blocker)])
        else:
            raise ValueError('Unknown interface')
        answer=best or {'task':task,'cost':None}
        answer['complete']=complete and not self.seed_mode
        self.memory[key]=answer
        self.db.execute('INSERT OR REPLACE INTO binary_memo VALUES (?,?,?)',(self.run,key,json.dumps(answer)))
        if len(self.memory)%200==0:
            self.db.commit()
        return answer

    def export(self, answer):
        if answer['cost'] is None:
            return answer
        node={k:v for k,v in answer.items() if k!='children'}
        node['children']=[]
        for key in answer.get('children',[]):
            child=self.memory.get(key)
            if child is None:
                child=json.loads(self.db.execute('SELECT answer FROM binary_memo WHERE run=? AND key=?',(self.run,key)).fetchone()[0])
            node['children'].append(self.export(child))
        if node['children']:
            # Shared memo children may improve after a parent incumbent was
            # found. Price the actual exported tree, not its older upper bound.
            node['cost']=str(sum((Fraction(c['cost']) for c in node['children']),Fraction(0)))
        return node

    def plan(self,target,cells=10):
        if cells not in (7,10) or not 2<=target<=self.maximum:
            raise ValueError('Invalid goal/cells')
        self.cells=cells
        self.config['cells']=cells
        self.run=identity(self.config)
        self.seed_mode=True
        seed=self.solve(('single',cells,target,self.depth))
        atomic_json(self.directory/'binary-seed.json',self.export(seed))
        self.seeds={k:v for k,v in self.memory.items() if v['cost'] is not None}
        self.memory={}
        self.seed_mode=False
        self.nodes=0
        self.paused=False
        root=self.solve(('single',cells,target,self.depth))
        tree=self.export(root)
        verification=None
        if root['cost'] is not None:
            verification=verify_tree(tree,cells)
            atomic_json(self.directory/'ideal-connection-trace.json',verification)
        counts=Counter()
        def count(node):
            if node.get('template'):
                counts[node['template']]+=1
            for child in node.get('children',[]):count(child)
        count(tree)
        result={'version':VERSION,'target':target,'cells':cells,'tree':tree,
                'totalWeight':float(Fraction(tree['cost'])) if tree['cost'] else None,
                'leafCounts':dict(sorted(counts.items())),'leafCalls':sum(counts.values()),
                'nodesThisRun':self.nodes,'status':'paused' if self.paused else 'candidate' if root['cost'] else 'no-route-in-scope',
                'config':self.config,'globallyOptimal':False,'executionVerified':False,
                'idealConnectionsVerified':verification is not None,
                'minimumAdditiveWeightProvenInScope':bool(root['cost'] is not None and root['complete'] and root['cost']==tree['cost']),
                'metric':'sum of measured (u+v)/p for individual leaf invocations',
                'scope':'binary rules with stated domains and finite EDGE depth; measured leaf policies with explicit capacity; unresolved primitive buffer policies not assumed',
                'wholeGameExpectedDrops':None}
        atomic_json(self.directory/'binary-plan.json',result)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',type=int)
    parser.add_argument('--cells',type=int,choices=(7,10),default=10)
    parser.add_argument('--weights',type=Path,required=True)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--maximum',type=int)
    parser.add_argument('--edge-depth',type=int,default=5)
    parser.add_argument('--node-limit',type=int,default=150000)
    parser.add_argument('--split-mode',choices=('guided','all'),default='guided')
    parser.add_argument('--minimum-leaf-target',type=int,default=2)
    args=parser.parse_args()
    planner=BinaryPlanner(args.directory,json.loads(args.weights.read_text()),
                          maximum=args.maximum or min(65535,max(48,2*args.target)),edge_depth=args.edge_depth,
                          node_limit=args.node_limit,split_mode=args.split_mode,
                          minimum_leaf_target=args.minimum_leaf_target,
                          progress=lambda d:print(json.dumps(d),flush=True))
    try:
        result=planner.plan(args.target,args.cells)
        print(json.dumps({k:v for k,v in result.items() if k not in ('tree','config')},indent=2))
    finally:planner.close()


if __name__=='__main__':main()
