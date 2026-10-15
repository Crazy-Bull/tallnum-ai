"""Plan synthesis contracts independently, then bind pending-state tables.

The result is an ideal-exit route, not a whole-game success-rate claim. Every
leaf names a pending-state probability table with static fallback disabled.
Search exhaustion is reported separately from absence of a route in scope.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from .binary_routes import BinaryPlanner, verify_tree
from .common import atomic_json
from .expected_routes import standard
from .peak_count_routes import focus
from .probability_route_execution import configure_recovery, improve_execution


def equivalent_boundary_minimum(item):
    minimum=item.get('equivalentProtectedMinimum')
    maximum=item.get('maxValue')
    anchor=item.get('singleProtectedValue')
    return minimum if (item.get('exit')=='single' and type(minimum) is int
                       and type(maximum) is int and type(anchor) is int
                       and minimum>=10*(maximum//10+1) and anchor>=minimum) else None


def boundary_fits(item,before):
    if item.get('singleProtectedValue') is None:return True
    if not before:return False
    minimum=equivalent_boundary_minimum(item)
    return before[-1][0]>=minimum if minimum is not None else before[-1][0]==item['singleProtectedValue']


def usable_policies(catalog):
    choices={}
    for item in catalog['policies']:
        cells=item.get('cells',5)
        target=item['target']
        kind=item['exit']
        if (not 5<=cells<=255 or not 24<=target<=65535
                or kind not in ('single','match','extend')
                or not item.get('pendingValue') or not item.get('disableStaticFallback')
                ):
            continue
        protected=item.get('singleProtectedValue')
        key=(cells,target,kind)
        if key not in choices or (bool(protected),bool(item.get('warmStartOrdinary')),item['id']) < (bool(choices[key].get('singleProtectedValue')),bool(choices[key].get('warmStartOrdinary')),choices[key]['id']):
            choices[key]=item
    # A clean single target may be produced next to an equal protected block;
    # the game's automatic merge then supplies the match contract.
    for (cells,target,kind),item in list(choices.items()):
        variants=[p for p in catalog['policies'] if (p.get('cells',5),p['target'],p['exit'])==(cells,target,kind)
                  and p.get('pendingValue') and p.get('disableStaticFallback')
                  and p.get('warmStartOrdinary')==item.get('warmStartOrdinary')]
        if item.get('singleProtectedValue') is not None:
            choices[cells,target,kind]={**item,'allowedBoundaries':sorted({p['singleProtectedValue'] for p in variants if p.get('singleProtectedValue') is not None})}
        if kind=='single' and item.get('successNoExtraCombos') and (cells,target,'match') not in choices:
            choices[cells,target,'match']={**item,'aliasExit':'single'}
    return choices


def parse_allowed_templates(allowed_templates):
    choices=set()
    for key in allowed_templates:
        parts=key.split(':')
        if (len(parts)!=3 or not parts[0].isdigit() or not parts[1].isdigit()
                or not 5<=int(parts[0])<=255 or not 24<=int(parts[1])<=65535
                or parts[2] not in ('single','match','extend')):
            raise ValueError(f'无效的定式 {key!r}；须为 格数:目标:single|match|extend，格数至少 5，目标至少 24')
        choices.add((int(parts[0]),int(parts[1]),parts[2]))
    return choices


def structural_choices(selected):
    choices={key:None for key in selected}
    # A single exit may cause a real automatic equal merge against its anchor.
    # This search alias still binds to the selected single, never to an excluded match.
    for cells,target,kind in selected:
        if kind=='single' and (cells,target,'match') not in choices:
            choices[cells,target,'match']='single'
    return choices


def structural_snapshot(choices):
    if not choices:raise ValueError('请至少允许一种不小于五格的定式')
    return {'metric':'lexicographic template calls','structuralOnly':True,
            'entries':{f'{cells}:{target}:{kind}':{'target':target,'exit':kind,
                       'weightExact':'1','policyId':None,'structuralOnly':True,
                       'declaredNonstandard':not standard(target)}
                       for cells,target,kind in choices}}


def validate_bound_route(route, catalog, selected):
    """Validate catalog binding without imposing a goal-specific peak limit."""
    by_id={item['id']:item for item in catalog['policies']}
    for step in route['steps']:
        if step['kind']!='leaf':continue
        item=by_id[step['policy']]
        if sum(b[1] for b in step['before'])+step['policyCells']>route['cells']:
            raise ValueError(f'定式真实工作区不足: {item["id"]}')
        key=(item.get('cells',5),item['target'],item['exit'])
        if key not in selected or step['template']!=f'{key[0]}:{key[1]}:{key[2]}' or step['policyCells']!=key[0]:
            raise ValueError(f'路线定式与概率表契约不一致: {item["id"]}')
        if not item.get('pendingValue') or not item.get('disableStaticFallback'):
            raise ValueError(f'路线定式缺少待出数概率表: {item["id"]}')
        if not boundary_fits(item,step['before']):
            raise ValueError(f'定式边界不一致: {item["id"]}')
        if item.get('warmStartOrdinary')!=step.get('warmStartOrdinary'):
            raise ValueError(f'定式预热块不一致: {item["id"]}')


def plan_route(target,cells,catalog,directory,*,allowed_templates=None,maximum=None,edge_depth=5,node_limit=3000):
    if type(cells) is not int or not 1<=cells<=255:
        raise ValueError('塔容量须为 1–255 格整数')
    if type(target) is not int or not 2<=target<=65535:
        raise ValueError('目标须为 2–65535 的整数')
    if type(edge_depth) is not int or not 0<=edge_depth<=8 or type(node_limit) is not int or not 1<=node_limit<=1000000:
        raise ValueError('搜索预算或 EDGE 深度无效')
    policies=usable_policies(catalog) if catalog is not None else {}
    selected=set(policies) if allowed_templates is None else parse_allowed_templates(allowed_templates)
    ceiling=max((value for capacity,value,kind in selected),default=0)
    maximum=min(65535,max(64,2*target,ceiling)) if maximum is None else maximum
    if type(maximum) is not int or not target<=maximum<=65535:
        raise ValueError('中间数上限须在目标数至 65535 之间')
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'route.json').unlink(missing_ok=True)
    (directory/'structural-route.json').unlink(missing_ok=True)
    (directory/'planning-report.json').unlink(missing_ok=True)
    # Search reads contract declarations, never probability-table contents.
    choices=structural_choices(selected)
    if allowed_templates is None:
        for key,policy in policies.items():
            if policy.get('aliasExit')=='single':choices[key]='single'
    snapshot=structural_snapshot(choices)
    five_ceiling=max((value for capacity,value,kind in selected if capacity==5),default=0)
    scope={'maximum':maximum,'edgeDepth':edge_depth,'nodeLimit':node_limit,
           'minimumTemplateTarget':24,'maximumFiveCellTarget':five_ceiling,
           'allowedTemplates':sorted(f'{capacity}:{value}:{kind}' for capacity,value,kind in selected),
           'allowedFiveCellTemplates':sorted(f'5:{value}:{kind}' for capacity,value,kind in selected if capacity==5),
           'catalogPolicyCount':len(policies) if allowed_templates is None or catalog is None else None}
    if target in (2,4,6,8,10,15):
        result={'status':'direct-draw-target','target':target,'cells':cells,
                'reason':f'{target} 是原始发牌数字；可直接等待其出现，无须使用定式',
                'scope':scope,'randomExecutionVerified':False}
        atomic_json(directory/'planning-report.json',result)
        return result
    minimum_capacity=min(capacity for capacity,value,kind in selected)
    if cells<minimum_capacity:
        result={'status':'impossible-under-template-rules','target':target,'cells':cells,
                'reason':f'所选定式至少需要 {minimum_capacity} 格，当前塔容量不足以执行任何定式',
                'scope':scope,'randomExecutionVerified':False}
        atomic_json(directory/'planning-report.json',result)
        return result
    if target%2 and target!=15:
        result={'status':'impossible-ordinary-target','target':target,'cells':cells,
                'reason':'普通单块只能是偶数或 15；奇数组合块不是普通单块',
                'scope':scope,'randomExecutionVerified':False}
        atomic_json(directory/'planning-report.json',result)
        return result
    bound=max((value if cells==capacity else 2*value*3**(cells-capacity-1)
               for capacity,value,kind in selected if capacity<=cells),default=0)
    if target>bound:
        five_bound=(five_ceiling if cells==5 else 2*five_ceiling*3**(cells-6)) if five_ceiling and cells>=5 else 0
        only_five=bound==five_bound
        divisor=1 if cells==5 else 2*3**(cells-6)
        required=(target+divisor-1)//divisor if only_five else None
        result={'status':'requires-higher-template-ceiling' if only_five else 'outside-allowed-template-bound',
                'target':target,'cells':cells,
                'reason':(f'在允许的最高五格 {five_ceiling} 定式下，{cells} 格普通单块上界为 {bound}；目标至少需要五格定式上限 {required}'
                          if only_five else f'按所选定式的格数和目标，{cells} 格普通单块结构上界为 {bound}，低于目标 {target}'),
                'maximumOrdinaryTarget':bound,'minimumRequiredFiveCellTarget':required,
                'scope':scope,'randomExecutionVerified':False}
        atomic_json(directory/'planning-report.json',result)
        return result
    attempts=[]
    unresolved=False
    for cap in sorted({0}|{value for capacity,value,kind in selected if capacity==5}):
        scoped={key:alias for key,alias in choices.items() if key[0]!=5 or key[1]<=cap}
        upper=max((value if cells==capacity else 2*value*3**(cells-capacity-1)
                   for capacity,value,kind in scoped if capacity<=cells),default=0)
        if not scoped or target>upper:
            attempts.append({'fiveCellCeiling':cap,'status':'excluded-by-capacity-bound','upperBound':upper})
            continue
        scoped_snapshot=structural_snapshot(scoped)
        if catalog is not None:
            for key,item in policies.items():
                encoded=f'{key[0]}:{key[1]}:{key[2]}'
                if encoded in scoped_snapshot['entries']:
                    if item.get('singleProtectedValue') is not None:
                        scoped_snapshot['entries'][encoded]['requiredBoundary']=item['singleProtectedValue']
                        scoped_snapshot['entries'][encoded]['allowedBoundaries']=item.get('allowedBoundaries',[item['singleProtectedValue']])
                    minimum=equivalent_boundary_minimum(item)
                    if minimum is not None:
                        scoped_snapshot['entries'][encoded].pop('requiredBoundary',None)
                        scoped_snapshot['entries'][encoded].pop('allowedBoundaries',None)
                        scoped_snapshot['entries'][encoded]['equivalentBoundaryMinimum']=minimum
                    if item.get('warmStartOrdinary') is not None:
                        scoped_snapshot['entries'][encoded]['warmStartOrdinary']=item['warmStartOrdinary']
        planner=BinaryPlanner(directory/'search'/f'five-cap-{cap}',scoped_snapshot,
                              maximum=maximum,edge_depth=edge_depth,node_limit=node_limit,
                              minimum_leaf_target=24,maximum_leaf_target=max(k[1] for k in scoped),
                              objective='five-peak-count')
        try: candidate=planner.plan(target,cells)
        finally:planner.close()
        attempts.append({'fiveCellCeiling':cap,'status':candidate['status'],
                         'leafCalls':candidate['leafCalls']})
        if candidate['tree']['cost'] is not None:break
        unresolved|=candidate['status']=='paused'
    scope['objective']=['maximum-five-cell-target','calls-at-maximum-five-cell-target','total-template-calls']
    scope['ceilingSearch']=attempts
    if candidate['tree']['cost'] is None and unresolved:candidate['status']='paused'
    if candidate['tree']['cost'] is None:
        missing=([f'5:{target}:single']
                 if candidate['status']!='paused' and 24<=target<=five_ceiling
                 and (5,target,'single') not in selected else [])
        result={'status':'incomplete' if candidate['status']=='paused' else 'catalog-gap',
                'target':target,'cells':cells,'reason':'搜索预算已用尽；尚不能判定是否存在路线' if candidate['status']=='paused'
                else '允许的定式无法构造该目标；可调整允许列表，不能据此判定游戏无解',
                'missingProbabilityTables':missing,
                'scope':scope,'randomExecutionVerified':False}
        atomic_json(directory/'planning-report.json',result)
        return result
    root_search_status=candidate['status']
    if not candidate.get('minimumFivePeakCountProvenInScope'):
        candidate=focus(candidate,directory/'focused',node_limit=min(3000,node_limit),
                        maximum_task=target,split_mode='guided',objective='five-peak-count')
    trace=verify_tree(candidate['tree'],cells)
    if trace['finalBoard']!=[[target,1,False]]:
        raise ValueError('结构搜索的最终盘面与目标不一致')
    if allowed_templates is not None and catalog is not None:
        policies=usable_policies(catalog)
        scope['catalogPolicyCount']=len(policies)
    policy_by_template={f'{capacity}:{value}:{kind}':item for (capacity,value,kind),item in policies.items()}
    steps=[]
    missing=set()
    for step in trace['steps']:
        if step['kind']=='leaf':
            capacity,value,kind=step['policyCells'],step['target'],step['exit']
            alias=choices[capacity,value,kind]=='single'
            template=f'{capacity}:{value}:single' if alias else step['template']
            policy=policy_by_template.get(template)
            if policy and policy.get('singleProtectedValue') is not None:
                variants=[p for p in catalog['policies'] if (p.get('cells',5),p['target'],p['exit'])==(capacity,value,kind)
                          and p.get('pendingValue') and p.get('disableStaticFallback')
                          and p.get('warmStartOrdinary')==step.get('warmStartOrdinary')
                          and boundary_fits(p,step['before'])]
                policy=min(variants,key=lambda p:p['id']) if variants else None
            if policy is not None and alias and not policy.get('successNoExtraCombos'):
                policy=None
            if policy is None:missing.add(template)
            step={**step,'policy':policy['id'] if policy else None}
            if alias:
                step.update(exit='single',template=f'{capacity}:{step["target"]}:single',
                            singleConnectionAfter=step['after'])
            if step['exit']=='single' and 'singleConnectionAfter' in step:
                step['connection']='ordinary-single-then-real-automatic-equal-merge'
        steps.append(step)
    route={'id':f'template-contracts-{cells}-{target}','version':2,'kind':'stages',
           'cells':cells,'target':target,'initialPrefix':[],'steps':steps,
           'minimumTemplateTarget':24}
    if catalog is not None and not missing:
        route=improve_execution(route,catalog,selected,boundary_fits)
        steps=route['steps']
    counts=Counter(step['template'] for step in steps if step['kind']=='leaf')
    peak=max((int(key.split(':')[1]) for key in counts if key.startswith('5:')),default=0)
    route['bufferRescuePolicies']={}
    if catalog is not None:
        configure_recovery(route,catalog,allowed_buffers=None if allowed_templates is None else set())
    rescues=route['bufferRescuePolicies']
    result={'status':'missing-probability-tables' if missing else 'candidate',
            'target':target,'cells':cells,'scope':scope,
            'five64Calls':sum(count for key,count in counts.items() if key.startswith('5:64:')),
            'maximumFiveCellTarget':max((int(key.split(':')[1]) for key in counts if key.startswith('5:')),default=0),
            'highestTemplate':max(counts,key=lambda key:tuple(map(int,key.split(':')[:2]))) if counts else None,
            'highestFiveCellCalls':sum(count for key,count in counts.items() if key.startswith(f'5:{peak}:')),
            'rescueFive64Policies':rescues.get('64',[]),'leafCounts':dict(counts),
            'steps':len(steps),'missingProbabilityTables':sorted(missing),
            'randomExecutionVerified':False,
            'idealExitVerified':True,'searchStatus':root_search_status,
            'executionContractVersion':route.get('executionContractVersion'),
            'startupContract':route.get('startupContract'),
            'executionExpansions':len(route.get('executionExpansions',[])),
            'lexicographicOrderProvenInScope':bool(not route.get('startupContract') and not route.get('executionExpansions')
                                                  and not unresolved and candidate.get('minimumFivePeakCountProvenInScope'))}
    if missing:
        result['reason']='结构路线已找到，但所选定式缺少待出数概率表；不能作为可执行路线'
        atomic_json(directory/'structural-route.json',route)
    else:
        validate_bound_route(route,catalog,selected)
        atomic_json(directory/'route.json',route)
    atomic_json(directory/'planning-report.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',type=int)
    parser.add_argument('--cells',type=int,required=True)
    parser.add_argument('--catalog',type=Path)
    parser.add_argument('--allow-template',action='append',dest='allowed_templates',
                        help='可重复指定任意不小于五格的定式，例如 6:40:single；省略则使用目录中的全部定式')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--maximum',type=int)
    parser.add_argument('--edge-depth',type=int,default=5)
    parser.add_argument('--node-limit',type=int,default=3000)
    args=parser.parse_args()
    if args.catalog is None and args.allowed_templates is None:
        parser.error('须指定 --catalog 或至少一个 --allow-template')
    catalog=json.loads(args.catalog.read_text(encoding='utf-8')) if args.catalog else None
    result=plan_route(args.target,args.cells,catalog,args.out,maximum=args.maximum,
                      allowed_templates=args.allowed_templates,edge_depth=args.edge_depth,node_limit=args.node_limit)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
