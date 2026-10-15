"""Add clean-exit variants from every historical five-cell catalog."""
import json
from pathlib import Path

from .common import atomic_json
from .library import load_catalog, table_header
from .route_variants import prepare_variants
from .route_search import template_alphas
from .aggressive import RISK


def main():
    workspace=Path('F:/TallnumData/tallnumai-cleanexit').resolve()
    catalogs=list(Path('automation/runs').resolve().rglob('catalog.json'))
    old_items={}
    requirements={}
    for path in catalogs:
        try:items=json.loads(path.read_text(encoding='utf-8')).get('policies',[])
        except (OSError,ValueError):continue
        for item in items:
            old_items.setdefault(item.get('id'),item)
            try:header=table_header(item['table'])
            except (OSError,ValueError,KeyError):continue
            if header['cells']!=5 or header['target']<24 or header['maxValue']<48:continue
            req={'key':f"5:{header['target']}:{item['exit']}",'cells':5,
                 'target':header['target'],'exit':item['exit'],
                 'maxValue':max(48,header['maxValue']),
                 'maxGoalCells':header['maxGoalCells'],'bases':header['bases'],
                 'successNoExtraCombos':True,
                 'aggressiveness':[0] if header['target']<48 else [0,*map(float,RISK)]}
            key=(req['target'],req['exit'],req['maxValue'],req['maxGoalCells'],tuple(req['bases']))
            requirements[key]=req
    current=load_catalog(workspace)
    by_id={p['id']:p for p in current['policies']}
    for identifier,item in old_items.items():
        if identifier:by_id.setdefault(identifier,item)
    atomic_json(workspace/'catalog.json',{'version':1,'policies':list(by_id.values())})
    state={'successNoExtraCombos':True,'uniqueFiveCellTemplates':len(requirements),
           'historicalCatalogsScanned':len(catalogs),'completed':[],'failed':[]}
    atomic_json(workspace/'supplement-recalculation.json',state)
    for key,req in sorted(requirements.items()):
        try:
            result=prepare_variants(workspace,[req],1500)[0]
            state['completed'].append({'key':key,'complete':result['complete'],
                                       'variants':len(result['variants']),
                                       'requirement':req})
        except Exception as exc:
            state['failed'].append({'key':key,'error':repr(exc),'requirement':req})
        atomic_json(workspace/'supplement-recalculation.json',state)
        complete=not state['failed'] or state['failed'][-1].get('key')!=key
        print(json.dumps({'template':key,'complete':complete},ensure_ascii=False),flush=True)
    state['allComplete']=not state['failed'] and all(x['complete'] for x in state['completed'])
    atomic_json(workspace/'supplement-recalculation.json',state)


if __name__=='__main__':main()
