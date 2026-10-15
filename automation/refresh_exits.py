"""Re-export certified fixed policies under corrected success-board semantics."""
from pathlib import Path
import argparse
import json
from .library import load_catalog, register
from .certify import attach
from .common import atomic_json, event


def refresh(directory):
    directory=Path(directory).resolve()
    backup=directory/'catalog-before-success-board-v2.json'
    if not backup.exists():
        atomic_json(backup,load_catalog(directory))
    previous=json.loads(backup.read_text(encoding='utf-8'))['policies']
    done={p['id']:p for p in load_catalog(directory)['policies']}
    mappings={}
    for old in previous:
        evidence=old.get('petsc',{})
        if not evidence.get('verified'):
            continue
        item=register(directory,old['table'],old['source'],old['exit'])
        if item.get('exitSemantics') not in ('success-board-v2','success-board-clean-v3'):
            raise RuntimeError('Rebuild native policy bridge before refreshing exits')
        current=done.get(item['id'],item)
        if not current.get('petsc',{}).get('exitEvaluationRounds',0)>=2:
            current=attach(directory,item,evidence['improvementResult'],evidence['rounds'])
            done[item['id']]=current
        mappings[old['id']]=item['id']
        atomic_json(directory/'success-board-v2-mapping.json',mappings)
        event('refreshed-exit',target=item['target'],exit=item['exit'],policy=item['id'],
              successProbability=current['statistics']['p'],completed=len(mappings))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',type=Path,required=True)
    refresh(parser.parse_args().directory)
