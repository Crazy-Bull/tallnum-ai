"""Search executable probability-table splices for a <=13-call 10240 route.

The measured route supplies the stable opening/bridges. An independent
minimum-count structural plan supplies only arithmetic waypoints. Dijkstra
searches legal leaf/Group/EDGE exits on the physical ten-cell board; no
handwritten replacement sequence is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import heapq
import json
from pathlib import Path

from .common import atomic_json
from .no80_route import OUT, audit
from .route_search import Block, edge_board, normalize


def blocks(raw):
    return tuple(Block(*row[:3]) for row in raw)


def raw(board):
    return [part.json() for part in board]


def physical(board):
    return sum(part.span for part in board)


def candidate_policies(catalog):
    """Use only measured pending tables whose exit contract is general here."""
    wanted={(6,32,'single'),(6,48,'single'),(5,32,'single'),
            (5,40,'single'),(5,48,'single'),(5,60,'single'),
            (5,64,'single'),(5,32,'match'),(5,48,'match'),
            (5,60,'match'),(5,64,'match'),(5,32,'extend'),
            (5,48,'extend'),(5,64,'extend')}
    choices={}
    for item in catalog['policies']:
        key=(item.get('cells',5),item['target'],item['exit'])
        if key not in wanted or not item.get('pendingValue') or not item.get('disableStaticFallback'):
            continue
        if item.get('warmStartOrdinary'):
            continue
        protected=item.get('singleProtectedValue')
        if protected is not None and (item['exit']!='match' or protected!=item['target']):
            continue
        old=choices.get(key)
        if old is None or item.get('statistics',{}).get('p',0.99)>old.get('statistics',{}).get('p',0.99):
            choices[key]=item
    return choices


def successors(board, prefix, goal, policies, peak_budget, used_peak):
    goal_total=sum(b.value for b in goal)
    for (cells,target,exit_kind),item in policies.items():
        if physical(board)+cells>10 or target<24 or (cells==5 and target>64):
            continue
        extra=int(cells==5 and target==64)
        if used_peak+extra>peak_budget:
            continue
        if exit_kind=='match' and (not board or board[-1].value!=target):
            continue
        if exit_kind=='extend':
            if len(board)<2 or board[-1].group or board[-1].span!=1:
                continue
            if board[-2].value-board[-1].value!=target:
                continue
            after=normalize((*board[:-1],Block(board[-2].value,2,True)))
        else:
            after=normalize((*board,Block(target)))
        if after[:len(prefix)]!=prefix or sum(b.value for b in after)>goal_total or physical(after)>10:
            continue
        step={'kind':'leaf','before':raw(board),'after':raw(after),'target':target,
              'exit':exit_kind,'template':f'{cells}:{target}:{exit_kind}',
              'policyCells':cells,'availableCells':10-physical(board),
              'policy':item['id']}
        if exit_kind=='single' and board and board[-1].value==target:
            step['singleConnectionAfter']=raw(after)
            step['connection']='ordinary-single-then-real-automatic-equal-merge'
        yield after,step,extra
    if not any(b.group for b in board):
        for count in range(2,min(5,len(board)-len(prefix))+1):
            members=board[-count:]
            if any(b.span!=1 for b in members):
                continue
            after=normalize((*board[:-count],Block(sum(b.value for b in members),count,True)))
            if after[:len(prefix)]!=prefix or sum(b.value for b in after)>goal_total or physical(after)>=10:
                continue
            first=len(board)-count
            step={'kind':'group','before':raw(board),'after':raw(after),
                  'indices':list(range(first,len(board)))}
            yield after,step,0
    if any(board[i].value//10>0 and board[i].value//10==board[i+1].value//10
           for i in range(len(board)-1)):
        after=edge_board(board)
        if after!=board and after[:len(prefix)]==prefix and physical(after)<10:
            yield after,{'kind':'edge','before':raw(board),'after':raw(after)},0


def search(start,goal,locked,policies,peak_budget,required_peak=None,max_steps=24,max_states=300000):
    start,goal=blocks(start),blocks(goal)
    prefix=start[:locked]
    if goal[:locked]!=prefix:raise ValueError('Search changes its protected prefix')
    heap=[(0,0,0,start,())]
    best={(start,0):(0,0)}
    expanded=0
    serial=0
    while heap:
        steps,risk,_,board,path=heapq.heappop(heap)
        used=sum(s.get('kind')=='leaf' and s.get('policyCells')==5 and s.get('target')==64
                 for s in path)
        if best.get((board,used))!=(steps,risk):continue
        if board==goal and (required_peak is None or used==required_peak):
            return list(path),{'expanded':expanded,'steps':steps,'five64Calls':used}
        if steps>=max_steps:continue
        expanded+=1
        if expanded>max_states:raise RuntimeError('Search state limit reached')
        for after,action,extra in successors(board,prefix,goal,policies,peak_budget,used):
            newer=used+extra
            # A secondary reliability/risk tie breaker keeps measured exits.
            penalty=0
            if action['kind']=='leaf':
                p=next(p for p in policies.values() if p['id']==action['policy'])
                penalty=round((1-p.get('statistics',{}).get('p',0.99))*100000)
            cost=(steps+1,risk+penalty)
            key=(after,newer)
            if key in best and best[key]<=cost:continue
            best[key]=cost
            serial+=1
            heapq.heappush(heap,(*cost,serial,after,path+(action,)))
    raise RuntimeError(f'No legal splice: {raw(start)} -> {raw(goal)}, 64 budget {peak_budget}')


def transport_macro(source,base,policies):
    """Rebase a previously measured construction on a longer protected prefix."""
    shift=len(base)-1
    moved=[]
    for original in source:
        step=deepcopy(original)
        for field in ('before','after','singleConnectionAfter'):
            if field in step:
                if not step[field] or step[field][0]!=[5120,1,False]:
                    raise ValueError('Donor macro lost its 5120 anchor')
                step[field]=deepcopy(base)+step[field][1:]
        for field in ('indices','releaseIndices'):
            if field in step:step[field]=[i+shift for i in step[field]]
        if step['kind']=='leaf':
            available=10-sum(part[1] for part in step['before'])
            step['availableCells']=available
            if available<step['policyCells']:
                key=(5,step['target'],step['exit'])
                replacement=policies.get(key)
                if step['exit']!='single' or replacement is None or available<5:
                    raise ValueError('Donor macro has no probability-table capacity replacement')
                step.update(policyCells=5,template=f'5:{step["target"]}:single',
                            policy=replacement['id'])
            if step['policyCells']==5 and step['target']==64:
                raise ValueError('Donor macro uses a five-cell 64 template')
        moved.append(step)
    for a,b in zip(moved,moved[1:]):
        if a['after']!=b['before']:raise ValueError('Transported macro has a broken contract')
    return moved


def measured_macro(steps,base,target,policies):
    donor_start=[[5120,1,False]]
    donor_finish=donor_start+[[target,1,False]]
    candidates=[]
    for i,step in enumerate(steps):
        if step['before']!=donor_start:continue
        for j in range(i,min(i+60,len(steps))):
            if steps[j]['after']!=donor_finish:continue
            try:moved=transport_macro(steps[i:j+1],base,policies)
            except ValueError:continue
            if any(s.get('warmStartOrdinary') and s['kind']=='leaf' and
                   (k==0 or moved[k-1].get('kind')!='release' or
                    moved[k-1].get('warmStartOrdinary')!=s['warmStartOrdinary'])
                   for k,s in enumerate(moved)):
                continue
            candidates.append(moved)
            break
    if not candidates:raise RuntimeError(f'No reusable measured macro for ordinary {target}')
    return min(candidates,key=len)


def plan(route,catalog,structural,maximum_64=13):
    route=deepcopy(route)
    policies=candidate_policies(catalog)
    steps=route['steps']
    def locate(board,start=0):
        return next(i for i in range(start,len(steps)) if steps[i]['after']==board)
    first_864=[[5120,1,False],[864,1,False]]
    first_1728=[[5120,1,False],[1728,1,False]]
    late_start=[[5120,1,False],[3456,1,False],[1152,1,False]]
    begin=locate(first_864)+1
    end=locate(first_1728,begin)+1
    tail=locate(late_start,end)+1
    if steps[begin]['before']!=first_864 or steps[tail]['before']!=late_start:
        raise ValueError('Measured route splice contracts changed')
    final=structural['steps'][-1]
    if final['kind']!='group' or final['after']!=[[10240,1,False]]:
        raise ValueError('Structural waypoint source is not a completed 10240 plan')
    destination=final['before']
    if destination[:3]!=late_start:
        raise ValueError('Structural candidate changed its final protected prefix')
    early,early_stats=search(first_864,first_1728,1,policies,0,max_steps=32)
    new_tail=[];reports=[];current=late_start
    first_goal=destination[3][0]
    if first_goal%2:raise ValueError('Final ordinary component has no equal-pair macro')
    donor=measured_macro(steps,late_start,first_goal//2,policies)
    new_tail.extend(donor)
    current=donor[-1]['after']
    first,stats=search(current,destination[:4],len(late_start),policies,1,
                       required_peak=1,max_steps=30)
    new_tail.extend(first);reports.append({'measuredDonorSteps':len(donor),**stats})
    current=destination[:4]
    for length in range(5,len(destination)+1):
        waypoint=destination[:length]
        found,stats=search(current,waypoint,len(current),policies,0,required_peak=0,
                           max_steps=30)
        new_tail.extend(found);reports.append(stats);current=waypoint
    # The final Group is an exact arithmetic connection, not a template.
    new_tail.append({'kind':'group','before':destination,'after':[[10240,1,False]],
                     'indices':list(range(1,len(destination)))})
    route['steps']=steps[:begin]+early+steps[end:tail]+new_tail
    route['id']=route['id']+'-peak13-search'
    # The 13-call constraint applies to planned leaves. Runtime buffer
    # rescues remain available, even when a rescue uses five-cell 64.
    counts=Counter(s['template'] for s in route['steps'] if s['kind']=='leaf')
    five64=counts.get('5:64:single',0)+counts.get('5:64:match',0)+counts.get('5:64:extend',0)
    if five64>maximum_64:raise ValueError(f'Planner exceeded 64 limit: {five64}>{maximum_64}')
    report={'five64Calls':five64,'maximumFiveCellTarget':64,
            'rescueFive64Policies':[ident for ids in route.get('bufferRescuePolicies',{}).values()
                                    for ident in ids if next((p for p in catalog['policies']
                                    if p['id']==ident and p.get('cells',5)==5 and p['target']==64),None)],
            'splices':{'first1728':early_stats,
            'final':reports},'leafCounts':dict(counts),'structure':'measured bridges plus searched arithmetic splices'}
    audit(route,catalog)
    return route,report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route',type=Path,default=OUT/'route-min24.json')
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--structural',type=Path,default=Path(__file__).resolve().parent/'runs/binary10240/minimum64/ideal-connection-trace.json')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    read=lambda p:json.loads(Path(p).read_text(encoding='utf-8'))
    route,report=plan(read(args.route),read(args.catalog),read(args.structural))
    args.out.mkdir(parents=True,exist_ok=True)
    atomic_json(args.out/'route.json',route)
    atomic_json(args.out/'planning-report.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
