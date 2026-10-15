"""Use tidy ordinary producers followed by checked real GROUP connections."""
from copy import deepcopy
import json

from .common import atomic_json
from .no80_route import OUT, EVIDENCE, audit
from .route_search import Block, normalize


def convert(route,catalog,prefix_length):
    route=deepcopy(route)
    singles={p['target']:p for p in catalog['policies'] if p.get('cells',5)==5
             and p['exit']=='single' and p.get('singleTidyExit')}
    result=route['steps'][:prefix_length];changes=[]
    for index,step in enumerate(route['steps'][prefix_length:],prefix_length):
        if step.get('kind')!='leaf' or step.get('exit')!='extend' or step['target'] not in singles:
            result.append(step);continue
        before=step['before'];target=step['target'];item=singles[target]
        ordinary=[b.json() for b in normalize(tuple(Block(*b) for b in before)+(Block(target),))]
        single={**step,'exit':'single','policy':item['id'],'policyCells':5,
                'template':f'5:{target}:single','after':ordinary}
        if before[-1][0]==target:
            if ordinary!=step['after']:raise ValueError('Automatic extension connection differs from contract')
            single['singleConnectionAfter']=deepcopy(step['after'])
            result.append(single)
        else:
            result.extend([single,{'kind':'group','before':ordinary,'after':step['after'],
                                  'indices':[len(before)-1,len(before)]}])
        changes.append({'previousStage':index,'target':target})
    route['steps']=result
    return route,changes


def main():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    original=read(EVIDENCE/'route.json')
    prefix=next(i for i,s in enumerate(original['steps']) if s['after']==[[5120,1,False]])+1
    catalog=read(OUT/'catalog-tidy-five.json')
    route,changes=convert(read(OUT/'route-tidy-five.json'),catalog,prefix)
    if route['steps'][:prefix]!=original['steps'][:prefix]:raise ValueError('Opening changed')
    report=audit(route,catalog);report['ordinaryConnections']=changes
    for name,value in [('route-ordinary-tidy',route),('catalog-ordinary-tidy',catalog),('ordinary-tidy-audit',report)]:
        atomic_json(OUT/(name+'.json'),value)
    print(json.dumps(report))


if __name__=='__main__':main()
