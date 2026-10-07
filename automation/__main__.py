from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import os

os.environ.setdefault('OPENBLAS_NUM_THREADS','1')

# Optional project-local dependencies avoid changing the machine Python setup.
deps = Path(__file__).parent/'.deps'
if deps.exists():
    sys.path.insert(0,str(deps))

from .common import atomic_json, event, fingerprint, execution_fingerprint
from .planner import Planner
from .library import load_catalog, prepare_missing, register, discover


def main():
    if len(sys.argv)>1 and sys.argv[1]=='route':
        from .route_cli import main as route_main
        return route_main(sys.argv[2:])
    parser=argparse.ArgumentParser(description='Tallnum five-cell route composition')
    parser.add_argument('command',choices=['plan','prepare','import','discover','validate','play'])
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--target',type=int,default=768)
    parser.add_argument('--rounds',type=int,default=5000)
    parser.add_argument('--attempts',type=int,default=100)
    parser.add_argument('--candidate-limit',type=int,default=20)
    parser.add_argument('--table')
    parser.add_argument('--source')
    parser.add_argument('--petsc-result',type=Path)
    parser.add_argument('--petsc-rounds',type=int,default=3)
    parser.add_argument('--exit',choices=['single','match','extend'])
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--browser',choices=('chrome','msedge'),default='chrome')
    parser.add_argument('--cdp-endpoint',help='Existing browser CDP WebSocket endpoint; otherwise discover Chrome remote debugging')
    parser.add_argument('--resume-current-game',action='store_true',help='Restore the current route from its confirmed action journal')
    parser.add_argument('--finish-current-game',action='store_true',
                        help='Finish the current round, keep its score panel for 10 seconds, log and restart')
    args=parser.parse_args()
    args.directory=args.directory.resolve()
    args.directory.mkdir(parents=True,exist_ok=True)
    if not 1<=args.rounds<=1000000 or not 1<=args.attempts<=1000000:
        parser.error('rounds/attempts must be in [1, 1000000]')
    if not 1<=args.candidate_limit<=20:
        parser.error('candidate-limit must be in [1, 20]')
    if args.command=='discover':
        atomic_json(args.directory/'discovered.json',discover())
        event('discovered',path=str(args.directory/'discovered.json'))
        return
    if args.command=='import':
        if not all((args.table,args.source,args.exit)):
            parser.error('import requires --table --source --exit')
        if args.petsc_result and args.petsc_rounds<2:
            parser.error('petsc-rounds must be at least 2')
        item=register(args.directory,args.table,args.source,args.exit)
        if args.petsc_result:
            from .certify import attach
            item=attach(args.directory,item,args.petsc_result,args.petsc_rounds)
        event('imported',id=item['id'],statistics=item['statistics'])
        return
    def plan():
        result=Planner(load_catalog(args.directory,certified_only=True,clean_only=True,include_shared=True)).plan(args.target)
        atomic_json(args.directory/'plan.json',result)
        event('plan',status=result['status'],routes=len(result['routes']),missing=result['missing'],triples=result['triples'])
        return result
    if args.command in ('plan','prepare'):
        result=plan()
        if args.command=='prepare':
            for _ in range(8):
                if not result['missing']:
                    break
                previous=result['missing']
                prepare_missing(args.directory,previous,args.rounds)
                from .certify import certify_baselines
                certify_baselines(args.directory)
                result=plan()
                if result['missing']==previous:
                    raise RuntimeError('Required policies remain unusable; inspect nontermination/statistics')
            if args.target==768 and not result['missing']:
                from .aggressive import calculate
                from .certify import attach_variants
                calculate(args.directory)
                attach_variants(args.directory)
                result=plan()
            event('prepared',status=result['status'],routes=len(result['routes']))
        return
    file=args.directory/'plan.json'
    result=json.loads(file.read_text(encoding='utf-8'))
    if result['target'] != args.target or not result['routes']:
        raise ValueError('Prepare a matching target plan first')
    catalog=load_catalog(args.directory,certified_only=True,clean_only=True,include_shared=True)
    available={p['id'] for p in catalog['policies']}
    def route_policies(node):
        if node['kind']=='leaf':
            return {node['id']}
        return set().union(*(route_policies(child) for child in node['children']))
    if any(not route_policies(route)<=available for route in result['routes']):
        raise ValueError('Prepared plan references policies from an older EDGE rule; run prepare again')
    if args.command=='validate':
        from .validation import rank
        execution_sha=execution_fingerprint()
        validation=rank(result,catalog,args.attempts,args.directory/'validation-cache',args.candidate_limit)
        if execution_fingerprint()!=execution_sha:
            raise RuntimeError('Execution code changed during validation; rerun validation')
        validation.update(planSha256=fingerprint(file),catalogSha256=fingerprint(args.directory/'catalog.json'),
                          executionSha256=execution_sha)
        atomic_json(args.directory/'validation.json',validation)
        event('validated',verified=validation['verified'],selectedRoute=validation['selectedRoute'])
    else:
        from .browser import play
        validation=json.loads((args.directory/'validation.json').read_text(encoding='utf-8'))
        if (not validation['verified'] or validation['planSha256']!=fingerprint(file)
                or validation['catalogSha256']!=fingerprint(args.directory/'catalog.json')
                or validation.get('executionSha256')!=execution_fingerprint()):
            raise ValueError('Route is not verified, or plan/catalog changed; validate first')
        route=next(r for r in result['routes'] if r['id']==validation['selectedRoute'])
        atomic_json(args.directory/'session.json',{'route':route,'planSha256':validation['planSha256']})
        play(route,catalog,args.directory,args.directory/'control.json',args.headless,args.browser,args.finish_current_game,args.cdp_endpoint,args.resume_current_game)


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        event('error',message=str(error))
        raise SystemExit(1)
