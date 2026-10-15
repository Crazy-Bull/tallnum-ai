"""Binary, space-aware single/match/extend/buffer contract search.

Leaves are declared standard contracts or supplied measured policies. Buffer is a Group
construction with existing ordinary members, never a nested Group. Both ordered
ordinary splits and repeated boundary reuse are allowed. Costs approximate independent
local retries, not whole-game stochastic execution. EDGE nesting and numeric
domains are explicitly bounded; missing leaf statistics remain unknown.
"""
from collections import Counter
from fractions import Fraction
import argparse
import json
import zlib
from pathlib import Path
import sqlite3

from .common import atomic_json, fingerprint
from .expected_routes import standard
from .peak_bounds import arithmetic_peak_bounds
from .route_search import identity, normalize, edge_board, Block, template_key

VERSION = 'binary-five-peak-dp-4'


def encode_memo(answer):
    return sqlite3.Binary(b'BPD3'+zlib.compress(json.dumps(answer).encode('utf-8'),1))


def decode_memo(payload):
    if isinstance(payload,bytes) and payload.startswith(b'BPD3'):
        payload=zlib.decompress(payload[4:])
    return json.loads(payload)


def structural_snapshot(maximum=128):
    """Declared standard contracts for planning; not certified policies.

    Keep missing policy measurements separate from structural reachability.
    Unit costs only break equal-profile ties and are never expected drops.
    """
    return {'metric':'structural leaf calls', 'structuralOnly':True,
            'entries':{f'5:{target}:{kind}':{'target':target,'exit':kind,
                         'weightExact':'1','policyId':None,'structuralOnly':True}
                       for target in range(2,maximum+1) if standard(target)
                       for kind in ('single','match','extend')}}


def verify_tree(tree, cells, entrance=(), *, node_callback=None):
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
        if node['rule'] in ('five-cell-policy','six-cell-policy','template-policy'):
            boundaries=node.get('allowedBoundaries')
            minimum=node.get('equivalentBoundaryMinimum')
            if minimum is not None and (not before or before[-1].value<minimum):
                raise ValueError('Template equivalent boundary mismatch')
            if boundaries is not None and (not before or before[-1].value not in boundaries):
                raise ValueError('Template protected boundary mismatch')
            capacity=int(node['template'].split(':')[0])
            if capacity<5 or (not standard(target) and not node.get('declaredNonstandard')) or n<capacity:
                raise ValueError('Invalid measured leaf workspace')
            if kind=='single' or kind=='match': board=normalize((*board,Block(target)))
            elif kind=='extend':
                a,b=rest[1:3]
                if board[-1].group or board[-1].span!=1:
                    raise ValueError('Extend requires ordinary boundary')
                board=normalize((*board[:-1],Block(a,2,True)))
            connection=({'singleConnectionAfter':[b.json() for b in board]}
                        if kind=='single' and before and before[-1].value==target else {})
            record('leaf',before,target=target,exit=kind,template=node['template'],
                   policyCells=capacity,availableCells=n,
                   **({'warmStartOrdinary':node['warmStartOrdinary']} if node.get('warmStartOrdinary') else {}),**connection)
        elif node['rule']=='warm-single':
            if kind!='single' or len(node['children'])!=2:
                raise ValueError('Warm construction requires a precursor and target single')
            visit(node['children'][0])
            warm=node['warmStartOrdinary']
            if board!=(*before,Block(warm)):
                raise ValueError('Warm entrance was not actually constructed')
            previous=board
            board=before
            record('release',previous,releaseIndices=[len(previous)-1],warmStartOrdinary=warm)
            finish=node['children'][1]
            if finish['task'][0]!='single' or finish['task'][2]!=target:
                raise ValueError('Warm policy has the wrong final target')
            if finish.get('warmStartOrdinary')!=warm:
                raise ValueError('Warm policy has inconsistent entrance metadata')
            visit(finish)
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
                if not any(board==normalize((*prefix,Block(target,span,True)))
                           for span in range(max(2,len(anchors)+1),6)):
                    raise ValueError(f'Group match exit mismatch at {node["task"]}: {before} -> {board}')
                if node_callback:node_callback(node,before,board)
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
        if node_callback:node_callback(node,before,board)
    visit(tree)
    return {'idealExitVerified':True,'finalBoard':[b.json() for b in board],
            'steps':steps,'maximumProtectedCells':max((sum(b[1] for b in s['after']) for s in steps),default=0),
            'stochasticExecutionVerified':False}


class BinaryPlanner:
    def __init__(self, directory, snapshot, *, maximum=13824, edge_depth=5,
                 node_limit=150000, split_mode='guided', progress=None, minimum_leaf_target=2, maximum_leaf_target=None,
                 objective='difficulty', opening_targets=None, minimum_total_for_template=None,
                 allowed_templates_at_single_anchor=None):
        if not 2 <= maximum <= 65535 or not 0 <= edge_depth <= 8:
            raise ValueError('Invalid numerical/EDGE bound')
        if split_mode not in ('guided','all') or node_limit < 0:
            raise ValueError('Invalid search mode/budget')
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)
        self.snapshot=snapshot
        if minimum_leaf_target<2:raise ValueError('Invalid minimum leaf target')
        self.minimum_leaf_target=minimum_leaf_target
        if objective not in ('difficulty','peak-count','weight','five-peak-count'):
            raise ValueError('Unknown route objective')
        self.objective=objective
        self.opening_targets=None if opening_targets is None else frozenset(opening_targets)
        if self.opening_targets is not None and not self.opening_targets:
            raise ValueError('Opening target set cannot be empty')
        self.minimum_total_for_template=dict(minimum_total_for_template or {})
        self.allowed_templates_at_single_anchor={int(k):frozenset(v) for k,v in
                                                 (allowed_templates_at_single_anchor or {}).items()}
        self.automatic_leaf_cap=maximum_leaf_target is None
        self.maximum_leaf_target=maximum if maximum_leaf_target is None else maximum_leaf_target
        if not minimum_leaf_target <= self.maximum_leaf_target <= maximum:
            raise ValueError('Invalid maximum leaf target')
        # An additive histogram has the optimal-substructure property. A bare
        # (maximum, count) score does not: a sibling can mask that maximum.
        self.ranks=sorted({(int(k.split(':')[0]),int(k.split(':')[1]))
                           for k in snapshot['entries']},reverse=True)
        if any(c<5 or c>255 for c,t in self.ranks):
            raise ValueError('All template leaves must use 5–255 cells')
        self.minimum_capacity=min(c for c,t in self.ranks)
        self.rank_index={rank:i for i,rank in enumerate(self.ranks)}
        self.peak_index=next(i for i,(c,t) in enumerate(self.ranks) if minimum_leaf_target<=t<=self.maximum_leaf_target)
        self.five_peak_index=next((i for i,(c,t) in enumerate(self.ranks)
                                  if c==5 and minimum_leaf_target<=t<=self.maximum_leaf_target),None)
        self.zero=(0,)*len(self.ranks)
        self.leaf_ceiling=max((t for c,t in self.ranks if minimum_leaf_target<=t<=self.maximum_leaf_target),default=0)
        self.maximum,self.depth,self.limit=maximum,edge_depth,node_limit
        self.mode,self.progress=split_mode,progress
        self.nodes=0
        self.paused=False
        self.memory={}
        self.seeds={}
        self.templates={}
        self.seed_mode=False
        self.cells=10
        self.config={'version':VERSION,'source':fingerprint(__file__),'weights':snapshot['entries'],
                     'rules':{name:fingerprint(Path(__file__).parent/name) for name in ('game.py','route_search.py')},
                     'maximum':maximum,'edgeDepth':edge_depth,'splitMode':split_mode,
                     'minimumLeafTarget':minimum_leaf_target,
                     'maximumLeafTarget':self.maximum_leaf_target,'objective':objective,
                     'openingTargets':sorted(self.opening_targets) if self.opening_targets is not None else None,
                     'minimumTotalForTemplate':self.minimum_total_for_template,
                     'allowedTemplatesAtSingleAnchor':{str(k):sorted(v) for k,v in self.allowed_templates_at_single_anchor.items()},
                     'ordinaryOrder':'all-ordered-splits','bufferOrder':'exempt',
                     'smallSpace':'measured-policies-with-explicit-capacity'}
        self.run=identity(self.config)
        self.db=sqlite3.connect(self.directory/'binary-search.sqlite3')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=NORMAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS binary_memo (run TEXT,key TEXT,answer TEXT,PRIMARY KEY(run,key))')
        self.bounds=arithmetic_peak_bounds((2,4,8,6,10,15),(),maximum)['costs']
        self.standard_values=[v for v in range(2,maximum+1) if standard(v)]
        # Tripling through Group is as important as doubling. Include these
        # nonstandard intermediates even for standard final goals (1728, etc.).
        self.guided_values=set(self.standard_values)
        self.guided_values.update(int(k.split(':')[1]) for k,e in snapshot['entries'].items()
                                  if e.get('declaredNonstandard'))
        # Declared nonstandard bases (28, 36, 44, etc.) are just as reusable
        # under doubling as the standard bases. Omitting their multiples
        # removes valid Group decompositions such as 1408 + 480 + 160.
        for base in list(self.guided_values):
            value=2*base
            while value<=maximum:
                self.guided_values.add(value);value*=2
        for v in self.standard_values:
            while v<=maximum:
                self.guided_values.add(v)
                v*=3
        self.unit_cost=min(Fraction(e['weightExact'])/int(k.split(':')[1])
                           for k,e in snapshot['entries'].items())

    def capacity_possible(self, task):
        """Optimistic bounds for this right-growing contract grammar.

        With b the smallest declared leaf capacity: M(b)=S(b)=L,
        M(n)=3*M(n-1), S(n)=2*M(n-1).
        Appended ordinary Group members sum to at most M(n). Reusing a
        boundary doubles at most M(n), then adds at most M(n), establishing
        the next match bound. EDGE only loses mass; induction on EDGE depth
        preserves these upper bounds. They are not bounds for arbitrary play.
        """
        kind,n,target,*rest=task
        base=self.minimum_capacity
        if n<base:return False
        match=self.leaf_ceiling*3**(n-base)
        if kind=='single':
            return target <= (self.leaf_ceiling if n==base else 2*self.leaf_ceiling*3**(n-base-1))
        if kind=='match':return target<=match
        if kind in ('group','group-match'):return target-sum(rest[1])<=match
        if kind=='buffer':return 10*target-sum(rest[1])<=match
        if kind=='extend':
            _,a,b=rest
            return a<=max(b,2*match)+match
        return True

    def profile_lower_bound(self, task):
        if self.objective=='five-peak-count':return list(self.zero)
        # Any successful subtree needs at least one leaf at a rank whose
        # cumulative capacity can satisfy the optimistic grammar bound.
        profile=list(self.zero)
        ceiling=self.leaf_ceiling
        try:
            self.leaf_ceiling=0
            for i in range(len(self.ranks)-1,-1,-1):
                _,value=self.ranks[i]
                if not self.minimum_leaf_target<=value<=self.maximum_leaf_target:continue
                self.leaf_ceiling=max(self.leaf_ceiling,value)
                if self.capacity_possible(task):
                    profile[i]=1
                    break
        finally:self.leaf_ceiling=ceiling
        return profile

    def score(self, answer):
        cost=Fraction(answer['cost'])
        if self.objective=='five-peak-count':
            return (answer['profile'][self.five_peak_index] if self.five_peak_index is not None else 0,cost)
        if self.objective=='peak-count':return (answer['profile'][self.peak_index],)
        return (tuple(answer['profile']),cost) if self.objective=='difficulty' else (cost,)

    def combined_score(self, profile, cost):
        if self.objective=='five-peak-count':
            return (profile[self.five_peak_index] if self.five_peak_index is not None else 0,cost)
        if self.objective=='peak-count':return (profile[self.peak_index],)
        return (tuple(profile),cost) if self.objective=='difficulty' else (cost,)

    def lower_bound(self, task):
        kind,n,target,*rest=task
        mass=target
        if kind=='single' and not standard(target) and target%2==0:
            if any(e.get('declaredNonstandard') and k.endswith(':single')
                   for k,e in self.snapshot['entries'].items()):
                # A provided nonstandard policy can introduce this odd base
                # internally. Its hidden EDGE mass cannot bound leaf calls.
                return Fraction(0)
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
        values={v for v in self.guided_values if low<=v<=high}
        middle=(low+high)//2
        for v in (low,low+1,low+2,high,high-1,high-2,middle,middle-1,middle+1):
            if low<=v<=high and (v==15 or v>=2 and v%2==0):
                values.add(v)
        return sorted(values)

    def seed_candidates(self, values):
        # Small anchors can be doubled repeatedly in the same workspace.
        # Keeping only the largest value in each base family loses those routes.
        return sorted(set(values),
                      key=lambda v:(v>self.maximum_leaf_target,-v))

    def leaf(self, task):
        kind,n,target,*rest=task
        if n<self.minimum_capacity or not self.minimum_leaf_target<=target<=self.maximum_leaf_target or kind not in ('single','match','extend'):
            return None
        options=[(key,entry) for capacity in sorted({c for c,t in self.ranks}) if n>=capacity
                 for key in (f'{capacity}:{target}:{kind}',)
                 if (entry:=self.snapshot['entries'].get(key)) is not None
                 and not entry.get('warmStartOrdinary')
                 and (entry.get('requiredBoundary') is None or kind!='extend' or rest[2] in entry.get('allowedBoundaries',[entry['requiredBoundary']]))
                 and (standard(target) or entry.get('declaredNonstandard'))]
        if not options:
            return None
        if self.objective=='five-peak-count':
            def leaf_score(pair):
                capacity,value,_=pair[0].split(':')
                peak=int(self.five_peak_index is not None and (int(capacity),int(value))==self.ranks[self.five_peak_index])
                return peak,Fraction(pair[1]['weightExact']),-int(capacity)
            key,entry=min(options,key=leaf_score)
        else:key,entry=min(options,key=lambda pair:
                      (tuple(map(int,pair[0].split(':')[:2])),Fraction(pair[1]['weightExact']))
                      if self.objective=='difficulty' else (Fraction(pair[1]['weightExact']),))
        profile=list(self.zero)
        profile[self.rank_index[tuple(map(int,key.split(':')[:2]))]]=1
        capacity=int(key.split(':')[0])
        return {'task':task,'cost':entry['weightExact'],'rule':{5:'five-cell-policy',6:'six-cell-policy'}.get(capacity,'template-policy'),
                'profile':profile,'children':[],'template':key,'policy':entry['policyId'],'complete':True,
                **({'allowedBoundaries':entry['allowedBoundaries']} if entry.get('allowedBoundaries') else {}),
                **({'equivalentBoundaryMinimum':entry['equivalentBoundaryMinimum']} if entry.get('equivalentBoundaryMinimum') else {}),
                **({'declaredNonstandard':True} if not standard(target) else {})}

    def polish_seed(self, tree, entrance=()):
        """Replace expensive leaves using spare cells before global search.

        The quick pass focuses on targets >=64; smaller contracts remain for
        the complete search instead of exploding the incumbent's leaf count.
        These are ordinary grammar productions, checked on the actual board.
        This ensures a finite search budget still improves the whole incumbent
        rather than spending all of it on the first small opening subtree.
        """
        if tree.get('cost') is None:return tree
        if tree.get('rule')=='warm-single':
            children=[self.polish_seed(tree['children'][0],entrance),tree['children'][1]]
            return {**tree,'children':children,'cost':str(sum((Fraction(c['cost']) for c in children),Fraction(0))),
                    'profile':[sum(c['profile'][i] for c in children) for i in range(len(self.ranks))]}
        task=tree['task']
        kind,n,target,*rest=task
        board=tuple(entrance)
        children=[]
        for child in tree.get('children',[]):
            child=self.polish_seed(child,board)
            children.append(child)
            board=tuple(Block(*b) for b in verify_tree(child,self.cells,board)['finalBoard'])
        if children:
            tree={**tree,'children':children,
                  'cost':str(sum((Fraction(c['cost']) for c in children),Fraction(0))),
                  'profile':[sum(c['profile'][i] for c in children) for i in range(len(self.ranks))]}
        if not tree.get('template'):return tree
        options=[]
        if kind in ('single','match') and n>self.minimum_capacity and target>=64 and target%2==0:
            half=target//2
            left=self.leaf(('single',n,half,rest[0]))
            right=self.leaf(('match',n-1,half,rest[0]))
            if left and right:
                # A match can use the same ordinary construction: its exit
                # naturally merges against the already protected equal anchor.
                options.append(('double' if kind=='single' else 'ordinary-match',left,right))
        if kind=='extend':
            depth,a,b=rest
            if n>self.minimum_capacity and target>=64 and target%2==0 and target!=b:
                left=self.leaf(('single',n,target//2,depth))
                right=self.leaf(('match',n-1,target//2,depth))
                if left and right:options.append(('ordinary-extension',left,right))
            if target>=64 and 32<=b<target and target-b>=32:
                left=self.leaf(('match',n,b,depth))
                right=self.leaf(('extend',n,target-b,depth,a,2*b))
                if left and right:options.append(('reuse-boundary',left,right))
        for rule,left,right in options:
            subtask=('single',n,target,rest[0]) if rule in ('ordinary-match','ordinary-extension') else task
            candidate={'task':subtask,'rule':'double' if rule in ('ordinary-match','ordinary-extension') else rule,
                       'children':[left,right],'cost':str(Fraction(left['cost'])+Fraction(right['cost'])),
                       'profile':[a+b for a,b in zip(left['profile'],right['profile'])],'complete':False}
            if rule in ('ordinary-match','ordinary-extension'):
                candidate={**candidate,'task':task,'rule':rule,'children':[candidate]}
            try:
                verify_tree(candidate,self.cells,entrance)
                candidate=self.polish_seed(candidate,entrance)
                verify_tree(candidate,self.cells,entrance)
            except ValueError:continue
            if self.score(candidate)<self.score(tree):tree=candidate
        return tree

    def reuse_seed(self, task, entrance):
        tree=self.templates.get(json.dumps(task))
        if tree is None and self.objective=='five-peak-count':
            candidates=[tree for tree in self.templates.values() if tree['task'][0]==task[0]
                        and tree['task'][2]==task[2] and tree['task'][1]<=task[1]
                        and tree['task'][3]<=task[3] and tuple(tree['task'][4:])==tuple(task[4:])]
            if candidates:
                tree={**min(candidates,key=self.score),'task':task}
        if tree is None:return None
        rebound={}
        def bind(node,before,after):
            template=node.get('template')
            if template:
                capacity,value,_=template.split(':')
                if not self.minimum_leaf_target<=int(value)<=self.maximum_leaf_target or int(capacity)<5:
                    raise ValueError('Seed template violates configured floor or capacity')
                gate=self.minimum_total_for_template.get(template,0)
                if sum(b.value for b in before)<gate:
                    raise ValueError('Seed template violates draw unlock gate')
                if len(before)==1 and before[0].span==1 and not before[0].group:
                    allowed=self.allowed_templates_at_single_anchor.get(before[0].value)
                    if allowed is not None and template not in allowed:
                        raise ValueError('Seed template violates single-anchor restriction')
                if not before and self.opening_targets is not None and node['task'][0]=='single' and node['task'][2] not in self.opening_targets:
                    raise ValueError('Seed template violates opening target restriction')
            key=json.dumps([node['task'],[b.json() for b in before]],separators=(',',':'))
            if node.get('template') and node.get('warmStartOrdinary'):
                key=json.dumps(['warm-leaf',node['task'],node['template'],[b.json() for b in before]])
            children=[rebound[id(c)][0] for c in node.get('children',[])]
            answer={**node,'children':children,'complete':False,
                    'entrance':[b.json() for b in before],'exitBoard':[b.json() for b in after]}
            rebound[id(node)]=(key,answer)
        try:verify_tree(tree,self.cells,entrance,node_callback=bind)
        except ValueError:return None
        self.memory.update(value for value in rebound.values())
        self.db.executemany('INSERT OR REPLACE INTO binary_memo VALUES (?,?,?)',
                            ((self.run,key,encode_memo(answer)) for key,answer in rebound.values()))
        return rebound[id(tree)][1]

    def solve(self, task, entrance=()):
        task=tuple(task)
        entrance=tuple(entrance)
        key=json.dumps([task,[b.json() for b in entrance]],separators=(',',':'))
        if key in self.memory:
            return self.memory[key]
        row=self.db.execute('SELECT answer FROM binary_memo WHERE run=? AND key=?',(self.run,key)).fetchone()
        if row:
            answer=decode_memo(row[0])
            if answer['complete']:
                self.memory[key]=answer
                return answer
        kind,n,target,*rest=task
        # The floor selects policy leaves, not arithmetic intermediates.
        # GROUP/EDGE may legitimately produce a smaller ordinary anchor.
        if not self.capacity_possible(task) or n<self.minimum_capacity or target<(1 if kind=='buffer' else 2) or target>self.maximum or (kind in ('single','match') and target%2 and target!=15):
            return {'task':task,'cost':None,'complete':True}
        # An empty buffer needs one more cell than the smallest leaf.
        # A new ordinary nonstandard base must use EDGE, which reserves one
        # cell for its precursor. Doubling cannot introduce a new odd base.
        # This is a scope-specific impossibility, not a game-wide assertion.
        if kind=='single' and n<=self.minimum_capacity+1 and not standard(target) and not self.leaf(task):
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
            self.progress({'nodes':self.nodes,'memo':len(self.memory),'task':task,'phase':'seed' if self.seed_mode else 'optimize'})
        incumbent=self.seeds.get(key)
        opening_restricted=(not entrance and kind=='single' and self.opening_targets is not None
                            and target not in self.opening_targets)
        candidate=None if opening_restricted else self.leaf(task)
        total_restricted=bool(candidate and sum(b.value for b in entrance)<
                              self.minimum_total_for_template.get(candidate['template'],0))
        anchor_allowed=(self.allowed_templates_at_single_anchor.get(entrance[0].value)
                        if len(entrance)==1 and entrance[0].span==1 and not entrance[0].group else None)
        anchor_restricted=bool(candidate and anchor_allowed is not None and candidate['template'] not in anchor_allowed)
        leaf_restricted=opening_restricted or total_restricted or anchor_restricted
        if candidate:
            boundary=self.snapshot['entries'][candidate['template']].get('requiredBoundary')
            leaf_restricted|=boundary is not None and (not entrance or entrance[-1].value not in self.snapshot['entries'][candidate['template']].get('allowedBoundaries',[boundary]))
            minimum=self.snapshot['entries'][candidate['template']].get('equivalentBoundaryMinimum')
            leaf_restricted|=minimum is not None and (not entrance or entrance[-1].value<minimum)
        best=(None if leaf_restricted else candidate) or (
            incumbent if incumbent and incumbent.get('cost') is not None and not leaf_restricted else None)
        if best is None and self.seed_mode:
            best=self.reuse_seed(task,entrance)
        if best and best['rule'] in ('five-cell-policy','six-cell-policy','template-policy'):
            if kind=='extend':
                end=normalize((*entrance[:-1],Block(rest[1],2,True)))
            else:end=normalize((*entrance,Block(target)))
            best={**best,'entrance':[b.json() for b in entrance],'exitBoard':[b.json() for b in end]}
        complete=True

        def offer(rule, child_tasks, **extra):
            nonlocal best,complete
            if self.seed_mode and best is not None and (self.objective in ('difficulty','peak-count','five-peak-count') or kind not in ('buffer','group','group-match')):
                return
            lower_profiles=[self.profile_lower_bound(t) for t in child_tasks]
            lower_profile=[sum(p[i] for p in lower_profiles) for i in range(len(self.ranks))]
            if best is not None and self.combined_score(lower_profile,sum((self.lower_bound(t) for t in child_tasks),Fraction(0)))>=self.score(best):
                return
            children=[]
            cost=Fraction(0)
            profile=list(self.zero)
            board=entrance
            for child_task in child_tasks:
                if self.objective=='five-peak-count':
                    child_task=(child_task[0],self.cells-sum(b.span for b in board),*child_task[2:])
                child=self.solve(child_task,board)
                complete=complete and child['complete']
                if child['cost'] is None:
                    return
                children.append(json.dumps([tuple(child_task),[b.json() for b in board]],separators=(',',':')))
                board=tuple(Block(*b) for b in child['exitBoard'])
                cost+=Fraction(child['cost'])
                profile=[a+b for a,b in zip(profile,child['profile'])]
                bound=cost+sum((self.lower_bound(t) for t in child_tasks[len(children):]),Fraction(0))
                remaining_profile=[profile[i]+sum(p[i] for p in lower_profiles[len(children):]) for i in range(len(self.ranks))]
                if best is not None and self.combined_score(remaining_profile,bound)>=self.score(best):
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
                    if not any(board==normalize((*prefix,Block(target,span,True)))
                               for span in range(max(2,len(anchors)+1),6)):return
                elif not board or not board[-1].group or board[-1].value!=target or board[:-1]!=prefix:return
            elif kind=='buffer':
                anchors=tuple(rest[1])
                prefix=entrance[:-len(anchors)] if anchors else entrance
                if not board or not board[-1].group or board[-1].value//10!=target or board[:-1]!=prefix:return
            if sum(b.span for b in board)>=self.cells:return
            if best is None or self.combined_score(profile,cost)<self.score(best):
                best={'task':task,'cost':str(cost),'profile':profile,'rule':rule,'children':children,
                      'complete':True,'entrance':[b.json() for b in entrance],
                      'exitBoard':[b.json() for b in board],**extra}

        if kind=='single':
            depth=rest[0]
            for encoded,entry in self.snapshot['entries'].items():
                capacity,value,exit_kind=encoded.split(':')
                warm=entry.get('warmStartOrdinary')
                if not warm or exit_kind!='single' or int(value)!=target or int(capacity)>n:continue
                boundary=entry.get('requiredBoundary')
                if boundary is not None and (not entrance or entrance[-1].value!=boundary):continue
                minimum=entry.get('equivalentBoundaryMinimum')
                if minimum is not None and (not entrance or entrance[-1].value<minimum):continue
                if entrance and entrance[-1].value==warm:continue
                precursor=self.solve(('single',n,warm,depth),entrance)
                if precursor['cost'] is None:continue
                precursor_key=json.dumps([precursor['task'],[b.json() for b in entrance]],separators=(',',':'))
                profile=list(self.zero);profile[self.rank_index[(int(capacity),target)]]=1
                finish={'task':task,'cost':entry['weightExact'],'profile':profile,'children':[],
                        'rule':'template-policy','template':encoded,'policy':entry['policyId'],
                        'warmStartOrdinary':warm,'declaredNonstandard':entry.get('declaredNonstandard',False),'complete':False}
                if minimum is not None:finish['equivalentBoundaryMinimum']=minimum
                finish_key=json.dumps(['warm-leaf',task,encoded,[b.json() for b in entrance]])
                self.memory[finish_key]=finish
                proposal={'task':task,'rule':'warm-single','warmStartOrdinary':warm,
                          'children':[precursor_key,finish_key],'cost':str(Fraction(precursor['cost'])+Fraction(finish['cost'])),
                          'profile':[a+b for a,b in zip(precursor['profile'],profile)],'complete':False}
                try:warm_trace=verify_tree(self.export(proposal),self.cells,entrance)
                except ValueError:continue
                proposal.update(entrance=[b.json() for b in entrance],exitBoard=warm_trace['finalBoard'])
                if best is None or self.score(proposal)<self.score(best):best=proposal
            if n>self.minimum_capacity:
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
            offer('ordinary-group-match',[('group-match',n,target,depth,(),target)])
            if n>self.minimum_capacity:
                # Both ordered splits matter: the existing boundary can be
                # reused repeatedly without consuming another working cell.
                xs=self.candidates(2,target-2)
                xs=[x for x in xs if self.capacity_possible(('single',n,x,depth))
                    and self.capacity_possible(('extend',n-1,target-x,depth,target,x))]
                if self.seed_mode and not depth:xs=[x for x in xs if standard(x)]
                def priority(x):
                    left=self.snapshot['entries'].get(template_key(x,'single'))
                    right=self.snapshot['entries'].get(template_key(target-x,'extend'))
                    return (not (left and right),
                            Fraction(left['weightExact'])+Fraction(right['weightExact']) if left and right else Fraction(0),
                            x!=target//2,not standard(x),x)
                xs.sort(key=priority)
                if self.seed_mode:
                    xs.sort(key=lambda x:(abs(3*x-target),x))
                for x in xs:
                    offer('match-sum',[('single',n,x,depth),('extend',n-1,target-x,depth,target,x)])
                # This is a unary interface adaptation, not a decomposition:
                # a full ordinary construction can finish against its anchor.
                if not self.seed_mode or best is None:
                    offer('ordinary-match',[('single',n,target,depth)])
        elif kind=='extend':
            depth,a,b=rest
            if a-b!=target or b<2:
                raise ValueError('Invalid extension entry')
            if target==b:
                offer('matching-extension',[('match',n,b,depth)])
            if n>=self.minimum_capacity:
                # Reusing B doubles the boundary without consuming another
                # cell. Crucially, the second child still has n cells.
                if b<target:
                    offer('reuse-boundary',[('match',n,b,depth),
                                            ('extend',n,target-b,depth,a,2*b)])
            # Complete B with ordinary members before making the Group. A
            # pre-built Group(target) cannot be nested inside Group(B,...).
            offer('group-extension',[('group-match',n,a,depth,(b,),a)])
            if target!=b:
                offer('ordinary-extension',[('single',n,target,depth)],a=a,b=b)
        elif kind=='buffer':
            depth,anchors,blocker=rest
            anchors=tuple(anchors)
            # target is the DECIMAL PREFIX, not an ordinary tile target.
            totals=list(range(10*target,min(10*target+9,self.maximum)+1))
            if self.seed_mode:
                leaf_values={int(k.split(':')[1]) for k in self.snapshot['entries']
                             if k.endswith(':single') and int(k.split(':')[1])<=self.maximum_leaf_target}
                totals.sort(key=lambda total:(not any(total-x in leaf_values and total-x!=x
                                                     for x in leaf_values),total))
            for total in totals:
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
                if anchors[-1]!=remaining:
                    offer('finish-group',[('single',n,remaining,depth)],anchors=list(anchors),groupTarget=target)
                if n>self.minimum_capacity and len(anchors)<4:
                    xs=self.candidates(2,remaining-2)
                    xs=[x for x in xs if self.capacity_possible(('single',n,x,depth))
                        and self.capacity_possible((kind,n-1,target,depth,anchors+(x,),blocker))]
                    if self.seed_mode:xs=self.seed_candidates(x for x in xs if x!=anchors[-1])
                    xs.sort(key=lambda x:(not (self.leaf(('single',n,x,depth)) and self.leaf(('single',n-1,remaining-x,depth))),not standard(remaining-x),not standard(x),-x))
                    for x in xs:
                        if x==anchors[-1]:
                            continue  # Explicit normal-merge alternatives are not assumed Group leaves.
                        offer('buffer-add',[('single',n,x,depth),
                                            (kind,n-1,target,depth,anchors+(x,),blocker)])
            elif not anchors and n>self.minimum_capacity:
                xs=self.candidates(2,target-2)
                xs=[x for x in xs if self.capacity_possible(('single',n,x,depth))
                    and self.capacity_possible((kind,n-1,target,depth,(x,),blocker))]
                if self.seed_mode:xs=self.seed_candidates(xs)
                xs.sort(key=lambda x:(not (self.leaf(('single',n,x,depth)) and self.leaf(('single',n-1,target-x,depth))),not standard(target-x),not standard(x),-x))
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
        if self.seed_mode and answer['cost'] is not None:
            self.templates[json.dumps(task)]=self.export(answer)
        if answer.get('cost') is not None or answer['complete']:
            self.db.execute('INSERT OR REPLACE INTO binary_memo VALUES (?,?,?)',(self.run,key,encode_memo(answer)))
        if len(self.memory)%200==0:
            self.db.commit()
        return answer

    def export(self, answer):
        if answer['cost'] is None:
            return answer
        node={k:v for k,v in answer.items() if k!='children'}
        node['children']=[]
        for key in answer.get('children',[]):
            child=self.memory.get(key) or self.seeds.get(key)
            if child is None:
                child=decode_memo(self.db.execute('SELECT answer FROM binary_memo WHERE run=? AND key=?',(self.run,key)).fetchone()[0])
            node['children'].append(self.export(child))
        if node['children']:
            # Shared memo children may improve after a parent incumbent was
            # found. Price the actual exported tree, not its older upper bound.
            node['cost']=str(sum((Fraction(c['cost']) for c in node['children']),Fraction(0)))
            node['profile']=[sum(c['profile'][i] for c in node['children']) for i in range(len(self.ranks))]
        return node

    def plan(self,target,cells=10):
        if type(target) is not int or type(cells) is not int:
            raise ValueError('Goal and cells must be integers')
        if not 5<=cells<=255 or not 2<=target<=self.maximum:
            raise ValueError('Invalid goal/cells')
        if self.automatic_leaf_cap and self.objective=='difficulty' and all(c==5 for c,t in self.ranks):
            attempts=[]
            for cap in sorted({t for c,t in self.ranks if self.minimum_leaf_target<=t<=self.maximum_leaf_target}):
                upper=cap if cells==5 else 2*cap*3**(cells-6)
                if target>upper:
                    attempts.append({'cap':cap,'status':'excluded-by-capacity-bound','upperBound':upper})
                    continue
                child=BinaryPlanner(self.directory/f'cap-{cap}',self.snapshot,
                                    maximum=self.maximum,edge_depth=self.depth,node_limit=self.limit,
                                    split_mode=self.mode,progress=self.progress,
                                    minimum_leaf_target=self.minimum_leaf_target,maximum_leaf_target=cap,
                                    objective=self.objective,opening_targets=self.opening_targets,
                                    minimum_total_for_template=self.minimum_total_for_template,
                                    allowed_templates_at_single_anchor=self.allowed_templates_at_single_anchor)
                try:result=child.plan(target,cells)
                finally:child.close()
                attempts.append({'cap':cap,'status':result['status']})
                if result['tree']['cost'] is not None or result['status']=='paused':
                    break
            else:
                # Run the widest scope to produce the usual no-route report.
                child=BinaryPlanner(self.directory/'cap-final',self.snapshot,maximum=self.maximum,
                                    edge_depth=self.depth,node_limit=self.limit,split_mode=self.mode,
                                    minimum_leaf_target=self.minimum_leaf_target,
                                    maximum_leaf_target=self.maximum_leaf_target,objective=self.objective,
                                    opening_targets=self.opening_targets,
                                    minimum_total_for_template=self.minimum_total_for_template,
                                    allowed_templates_at_single_anchor=self.allowed_templates_at_single_anchor)
                try:result=child.plan(target,cells)
                finally:child.close()
            result['capSearch']=attempts
            result['minimumPeakProvenInScope']=bool(result['tree']['cost'] is not None)
            atomic_json(self.directory/'binary-plan.json',result)
            return result
        self.memory={}
        self.seeds={}
        self.templates={}
        self.nodes=0
        self.paused=False
        self.cells=cells
        self.config['cells']=cells
        self.run=identity(self.config)
        self.seed_mode=True
        contextual=[(int(key.split(':')[1]),entry['warmStartOrdinary'])
                    for key,entry in self.snapshot['entries'].items() if entry.get('warmStartOrdinary')]
        if contextual and cells>self.minimum_capacity and target%2==0:
            # Build reusable warm entrances beside the future equal anchor.
            # Dependency order comes from ordinary doubling and EDGE ranges.
            prepared=set();pending=list(contextual)
            known={int(k.split(':')[1]) for k,e in self.snapshot['entries'].items()
                   if k.endswith(':single') and not e.get('warmStartOrdinary') and not e.get('requiredBoundary')}
            def family(value):
                return any(value>=base and value%base==0 and (value//base)&((value//base)-1)==0 for base in known)
            while pending:
                ready=next((pair for pair in pending if any(family(v) for v in range(5*pair[1],5*pair[1]+10) if v%2==0)),pending[0])
                pending.remove(ready)
                value,warm_value=ready
                for capacity in range(self.minimum_capacity,cells):
                    anchor=tuple(Block(target//2+100*i) for i in range(cells-capacity-1,0,-1))+(Block(target//2),)
                    for goal in (warm_value,value):
                        if self.limit and self.nodes>=self.limit//2:break
                        answer=self.solve(('single',capacity,goal,self.depth),anchor)
                        if answer['cost'] is not None:known.add(goal)
                prepared.add(value)
            tabulated=set(self.standard_values)
            for key in self.snapshot['entries']:
                value=int(key.split(':')[1])
                while value<=self.maximum:
                    tabulated.add(value);value*=2
            for capacity in range(self.minimum_capacity+2,cells):
                anchor=tuple(Block(target//2+100*i) for i in range(cells-capacity-1,0,-1))+(Block(target//2),)
                for value in sorted(tabulated):
                    if self.limit and self.nodes>=3*self.limit//4:break
                    task=('single',capacity,value,self.depth)
                    if value>target//2 or not self.capacity_possible(task):continue
                    self.solve(task,anchor)
        # Warm balanced third-components before the deep top-down query. This
        # makes nonstandard entry chains reusable across protected prefixes.
        warm=set()
        value=target//2
        while value>=2:
            choices=[v for v in self.guided_values if 2<=v<value]
            if choices:
                component=min(choices,key=lambda v:(abs(3*v-value),v))
                warm.add(component)
                base=component
                while base%2==0:base//=2
                if base!=15:warm.add(2*base)
            value//=2
        for value in ([] if contextual else sorted(warm)):
            if self.limit and self.nodes>=self.limit//4:break
            self.solve(('single',cells-1,value,self.depth))
        self.memory={k:v for k,v in self.memory.items() if v['cost'] is not None or v['complete']}
        seed=self.solve(('single',cells,target,self.depth))
        original_seed=self.export(seed)
        seed_tree=self.polish_seed(original_seed)
        if seed_tree.get('cost') is not None and self.score(seed_tree)<self.score(original_seed):
            self.templates[json.dumps(seed_tree['task'])]=seed_tree
            seed=self.reuse_seed(seed_tree['task'],())
        atomic_json(self.directory/'binary-seed.json',seed_tree)
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
                'minimumAdditiveWeightProvenInScope':bool(self.objective=='weight' and root['cost'] is not None and root['complete'] and root['cost']==tree['cost']),
                'minimumPeakCountProvenInScope':bool(self.objective=='peak-count' and root['cost'] is not None and root['complete'] and self.score(root)==self.score(tree)),
                'minimumFivePeakCountProvenInScope':bool(self.objective=='five-peak-count' and root['cost'] is not None and root['complete'] and self.score(root)==self.score(tree)),
                'minimumDifficultyProvenInScope':bool(self.objective=='difficulty' and root['cost'] is not None and root['complete'] and self.score(root)==self.score(tree)),
                'difficultyProfile':[{'cells':c,'target':t,'count':tree['profile'][i]}
                                     for i,(c,t) in enumerate(self.ranks) if tree.get('profile',self.zero)[i]],
                'objective':self.objective,
                'metric':self.snapshot.get('metric','sum of measured (u+v)/p for individual leaf invocations'),
                'missingPolicies':[key for key in sorted(counts) if self.snapshot['entries'][key].get('structuralOnly')],
                'scope':'ordered binary/Group/EDGE contract grammar with finite numerical and EDGE-depth bounds; leaf capacities explicit; structural declarations require policy certification',
                'wholeGameExpectedDrops':None}
        atomic_json(self.directory/'binary-plan.json',result)
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',type=int)
    parser.add_argument('--cells',type=int,choices=(7,10),default=10)
    parser.add_argument('--weights',type=Path,help='Optional template library; omit for structural planning')
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--maximum',type=int)
    parser.add_argument('--edge-depth',type=int,default=5)
    parser.add_argument('--node-limit',type=int,default=150000)
    parser.add_argument('--split-mode',choices=('guided','all'),default='guided')
    parser.add_argument('--minimum-leaf-target',type=int,default=2)
    parser.add_argument('--maximum-leaf-target',type=int)
    parser.add_argument('--objective',choices=('difficulty','peak-count','weight'),default='difficulty')
    parser.add_argument('--opening-targets',help='Comma-separated permitted first leaf targets')
    parser.add_argument('--minimum-total-template',action='append',default=[],metavar='TEMPLATE=TOTAL',
                        help='Require at least TOTAL fixed value before this five-cell template')
    args=parser.parse_args()
    try:
        gates={}
        for pair in args.minimum_total_template:
            key,raw=pair.split('=',1)
            if len(key.split(':'))!=3 or not raw.isdecimal():raise ValueError()
            gates[key]=int(raw)
        opening={int(x) for x in args.opening_targets.split(',')} if args.opening_targets else None
    except ValueError:parser.error('Invalid opening target or template total gate')
    snapshot=json.loads(args.weights.read_text()) if args.weights else structural_snapshot(args.maximum_leaf_target or (args.maximum or min(65535,max(48,2*args.target))))
    planner=BinaryPlanner(args.directory,snapshot,
                          maximum=args.maximum or min(65535,max(48,2*args.target)),edge_depth=args.edge_depth,
                          node_limit=args.node_limit,split_mode=args.split_mode,
                          minimum_leaf_target=args.minimum_leaf_target,
                          maximum_leaf_target=args.maximum_leaf_target,objective=args.objective,
                          opening_targets=opening,minimum_total_for_template=gates,
                          progress=lambda d:print(json.dumps(d),flush=True))
    try:
        result=planner.plan(args.target,args.cells)
        print(json.dumps({k:v for k,v in result.items() if k not in ('tree','config')},indent=2))
    finally:planner.close()


if __name__=='__main__':main()
