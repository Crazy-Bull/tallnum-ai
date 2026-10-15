"""Extend the measured erase-anchor/rewind rescue to new single entrances."""
from copy import deepcopy
import json
from pathlib import Path

from .common import atomic_json
from .no80_route import OUT, ROOT, audit


def main():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    route=read(OUT/'route-migrated.json')
    catalog=read(OUT/'catalog-v8.json')
    available=read(OUT/'catalog-dynamic.json')['policies']
    # Single 6 after protected 18 is the measured blocked entry. Target 16
    # has the same decimal head, so its buffer can erase 18 and rewind the
    # producer of 18. Other mappings obey exactly the same head condition.
    for anchor,target in [(10,12),(12,16),(14,16),(16,12),(18,16),(22,24),(28,24),
                          (34,32),(38,32),(44,40),(56,60),(68,64)]:
        if anchor//10!=target//10:continue
        candidates=[p for p in available if p['target']==target and p['exit'] in ('single','match')
                    and p.get('cells',5)==5 and p.get('successNoExtraCombos')
                    and p.get('maxGoalCells',5)<=4 and p.get('maxValue',0)>=48]
        if not candidates:continue
        item=deepcopy(candidates[0]);old_id=item['id'];native_exit=item['exit']
        item.update(id=old_id+'-boundary-buffer',exit='buffer',
                    nativeExitOverride=native_exit,
                    pendingNative=str(ROOT/'automation/pending_value_realboard.exe'),
                    realBoardAlternatives=True)
        meta=read(Path(item['pendingValueMeta']))
        meta['exit']='buffer'
        item['pendingValueMeta']=str(OUT/'new-pending'/(item['id']+'.json'))
        atomic_json(item['pendingValueMeta'],meta)
        if item['id'] not in {p['id'] for p in catalog['policies']}:
            catalog['policies'].append(item)
        route.setdefault('bufferRescuePolicies',{})[str(anchor)]=[item['id']]
    route['singleBoundaryBufferRescue']=True
    route['realBoundaryRewind']=True
    report=audit(route,catalog)
    report['boundaryRescuePolicies']=route['bufferRescuePolicies']
    for name,value in [('route-v9',route),('catalog-v9',catalog),('boundary-rescue-audit',report)]:
        atomic_json(OUT/(name+'.json'),value)
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
