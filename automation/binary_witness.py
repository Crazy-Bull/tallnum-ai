"""Controlled-draw witness for binary routes; never a stochastic policy test."""
import argparse
from collections import deque
import json
from pathlib import Path

from . import game
from .binary_routes import verify_tree
from .common import atomic_json
from .route_search import Block, normalize


def recipe(target):
    g=lambda n:('group-last',n)
    r24=[6,6,4,2,g(2),6]
    r32=[4,4,8,8,8]
    r40=[6,4,g(2),10,10,10]
    recipes={2:[2],4:[4],6:[6],8:[8],10:[10],12:[6,6],15:[15],
             16:[8,8],20:[10,10],24:r24,30:[15,15],32:r32,
             40:r40,48:r24*2,60:[15,15,10,10,10,g(2)],64:r32*2}
    recipes.update({80:recipes[40]*2,96:recipes[48]*2,
                    120:recipes[60]*2,128:recipes[64]*2})
    return recipes[target]


def apply_blocks(board, op):
    if isinstance(op,int):return normalize((*board,Block(op)))
    kind,arg=op
    indices=list(range(len(board)-arg,len(board))) if kind=='group-last' else arg
    members=board[indices[0]:indices[-1]+1]
    if not 2<=len(members)<=5 or any(b.group for b in board) or any(b.span!=1 for b in members):
        raise ValueError('Illegal Group')
    return normalize((*board[:indices[0]],Block(sum(b.value for b in members),len(members),True),*board[indices[-1]+1:]))


def leaf_ops(step,last,repeat,limit=250000):
    """Find a legal ordinary-member witness while preserving its entry prefix."""
    start=tuple(Block(*b) for b in step['before'])
    goal=tuple(Block(*b) for b in step['after'])
    prefix=len(start)
    def allowed(board):
        return board==goal or (board[:prefix]==start and sum(b.span for b in board[prefix:])<5
                               and sum(b.span for b in board)<10
                               and all(b.value<=step['target'] for b in board[prefix:]))
    def attempt(ops):
        board=start
        previous,streak=last,repeat
        accepted=[]
        for op in ops:
            if board==goal:return accepted
            if isinstance(op,int):
                streak=streak+1 if op==previous else 1
                previous=op
                if streak>4:return None
            try:board=apply_blocks(board,op)
            except ValueError:return None
            if not allowed(board):return None
            accepted.append(op)
        return accepted if board==goal else None
    ops=recipe(step['target'])
    if step['exit']=='extend':ops=[*ops,('group-last',2)]
    found=attempt(ops)
    if found is not None:return found
    if step['exit']=='extend':
        # Keep ordinary members separate until Group includes the boundary.
        # E.g. against B=64, building ordinary 128 would consume B at its
        # halfway 64; members 96+32 instead provide a legal 128 complement.
        values=(2,4,6,8,10,12,15,16,20,24,30,32,40,48,60,64,80,96,120,128)
        for x in reversed(values):
            y=step['target']-x
            if y not in values or x<y:continue
            found=attempt([*recipe(x),*recipe(y),('group-last',3)])
            if found is not None:return found
    root=(start,last,repeat)
    queue=deque([root])
    parents={root:None}
    final=None
    while queue and len(parents)<limit:
        state=queue.popleft()
        board,previous,streak=state
        options=[v for v in game.POOL if v<=step['target'] and not (v==previous and streak>=4)]
        if not any(b.group for b in board):
            for i in range(prefix-1 if step['exit']=='extend' else prefix,len(board)-1):
                for j in range(i+2,min(i+5,len(board))+1):options.append(('group',list(range(i,j))))
        for op in options:
            try:end=apply_blocks(board,op)
            except ValueError:continue
            if not allowed(end):continue
            key=(end,op,streak+1 if op==previous else 1) if isinstance(op,int) else (end,previous,streak)
            if key in parents:continue
            parents[key]=(state,op)
            if end==goal:
                final=key;queue.clear();break
            queue.append(key)
        if final:break
    if final is None:raise ValueError(f'No controlled witness for {step}, searched {len(parents)} states')
    ops=[]
    while parents[final] is not None:
        previous,op=parents[final];ops.append(op);final=previous
    return list(reversed(ops))


def witness(plan):
    checked=verify_tree(plan['tree'],10)
    steps=checked['steps']
    # Unlock all sources legally and consume the actual opening [2,4].
    initial32=[2,('group-last',3),8,8,8]
    checkpoints={s['after'][0][0]:i for i,s in reversed(list(enumerate(steps)))
                 if len(s['after'])==1 and s['after'][0][1:]==[1,False]}
    if 48 in checkpoints:
        # 128 + Group(80,40) -> EDGE 24; matching 24 -> ordinary 48.
        boot=[*initial32,*recipe(32),*recipe(64),
              *recipe(40),*recipe(40),*recipe(40),('group-last',2),('edge',None),*recipe(24)]
        opening_target=48
    elif 10 in checkpoints:
        # 256 + Group(240,12,2) -> EDGE 50;
        # 50 + Group(40,12) -> EDGE 10. Unlocks are permanent.
        boot=[*initial32,*recipe(32),*recipe(64),*recipe(64),*recipe(64),
              *(recipe(60)*4),*recipe(12),2,('group-last',3),('edge',None),
              *recipe(40),*recipe(12),('group-last',2),('edge',None)]
        opening_target=10
    else:
        raise ValueError('No supported standalone ordinary opening checkpoint (10 or 48)')
    opening_end=checkpoints[opening_target]
    ops=list(boot)
    last,repeat=None,0
    for op in ops:
        if isinstance(op,int):repeat=repeat+1 if op==last else 1;last=op
    for s in steps[opening_end+1:]:
        part=(leaf_ops(s,last,repeat) if s['kind']=='leaf' else
              [(s['kind'],s.get('indices'))])
        for op in part:
            if isinstance(op,int):repeat=repeat+1 if op==last else 1;last=op
        ops.extend(part)
    draws=[op for op in ops if isinstance(op,int)]
    state=game.new_game(123,tower_limit=10)
    state['queue']=draws[:4]
    if any(v not in state['unlocked'] for v in state['queue']):raise ValueError('Opening queue is not unlocked')
    drawn=0
    trace=[]
    last,repeat=None,0
    for op in ops:
        before=game.signature(state)
        if isinstance(op,int):
            repeat=repeat+1 if op==last else 1;last=op
            if repeat>4:raise ValueError('Fifth identical random source')
            if state['queue'][0]!=op:raise ValueError('Queue mismatch')
            future=draws[drawn+4] if drawn+4<len(draws) else 2
            if future not in state['unlocked']:raise ValueError(f'Source {future} generated before unlock: {before}')
            action={'kind':'drop'}
            state=game.apply(state,action,sample=False)
            state['queue'][-1]=future
            drawn+=1
        else:
            kind,arg=op
            action={'kind':kind}
            if kind=='group-last':action={'kind':'group','indices':list(range(len(state['tower'])-arg,len(state['tower'])))}
            elif kind=='group':action['indices']=arg
            state=game.apply(state,action,sample=False)
        if state['gameOver']:raise ValueError('Full board in witness')
        trace.append({'action':action,'draw':op if isinstance(op,int) else None,
                      'before':before,'after':game.signature(state),'physicalCells':game.physical(state),
                      'unlocked':list(state['unlocked'])})
    if game.signature(state)!=[(plan['target'],1,'tile')]:raise ValueError('Final goal mismatch')
    return {'target':plan['target'],'cells':10,'conditionalDrawPathVerified':True,
            'realOpeningAndUnlocksVerified':True,'stochasticPolicyVerified':False,
            'drops':drawn,'actions':len(trace),'maximumPhysicalCells':max(s['physicalCells'] for s in trace),
            'bootstrapReplacesInitialStages':opening_end+1,'bootstrapDrops':sum(isinstance(op,int) for op in boot),
            'bootstrapTarget':opening_target,
            'localRetryWeightIncludesGenericOpening':True,'trace':trace}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=witness(json.loads(args.plan.read_text()))
    atomic_json(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='trace'},indent=2))


if __name__=='__main__':main()
