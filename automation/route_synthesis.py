"""Explicit nonstandard construction from standard single and buffer contracts.

Scalar exploration is only a structural seed. Every emitted stage is a real
RouteSearch successor; five-cell preparation/PETSc and full-board simulation
remain responsible for proving stochastic executability.
"""
from fractions import Fraction
import heapq
from .planner import ordinary
from .route_search import Block,normalize


def synthesize(search,prefix,target,node_limit=2000):
    expected=normalize((*prefix,Block(target)))
    if any(b.group for b in prefix):return [],0,False
    serial=0;heap=[];best={};nodes=0
    def offer(board,cost,steps):
        nonlocal serial
        if board in best and best[board]<=cost:return
        best[board]=cost;serial+=1;heapq.heappush(heap,(cost,serial,board,steps))
    def step(op,before,after):return {**op,'before':[b.json() for b in before],'after':[b.json() for b in after]}
    for op,after,cost in search.successors(prefix):
        if op['kind']=='leaf' and ((op['exit'] in ('single','match') and ordinary(op['target']))
                                   or (op['exit']=='buffer' and op.get('purpose')=='equal-buffer' and op['target']==target)):
            if after==expected or after[:-1]==prefix:
                offer(after,cost,[step(op,prefix,after)])
    while heap:
        cost,_,board,steps=heapq.heappop(heap)
        if cost!=best[board]:continue
        if board==expected:return [{'steps':steps,'units':str(cost),'explicitNonstandard':target}],nodes,False
        if nodes>=node_limit:return [],nodes,True
        nodes+=1
        if board[:-1]!=prefix:continue
        anchor=board[-1].value
        for op,after,extra in search.successors(board):
            if op['kind']!='leaf':continue
            first=[*steps,step(op,board,after)]
            if op['exit'] in ('match','buffer') and op['target']==anchor:
                if after==expected or after[:-1]==prefix:offer(after,cost+extra,first)
            elif op['exit']=='buffer' and op.get('purpose')=='edge-buffer':
                for edge,end,free in search.successors(after):
                    if edge['kind']=='edge' and (end==expected or end[:-1]==prefix):
                        offer(end,cost+extra+free,[*first,step(edge,after,end)])
    return [],nodes,False
