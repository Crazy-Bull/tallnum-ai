"""Play the locally validated 640 variant route in the existing Chrome tab."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
from .browser import play
from .common import atomic_json, fingerprint
from .upgrade640 import WORK


def with_half_boundary(route):
    output=deepcopy(route)
    boundary=[[route['target']//2,1,False]]
    starts=[i for i,s in enumerate(route['steps']) if s['before']==boundary]
    if not starts:raise ValueError('No reusable half-boundary suffix')
    steps=deepcopy(route['steps'][starts[0]:])
    if steps[-1]['after']!=[[route['target'],1,False]]:
        raise ValueError('Half-boundary suffix has no ordinary target exit')
    output['continuation']={'id':route['id']+'-half-boundary','version':2,'kind':'stages',
        'cells':route['cells'],'target':route['target'],'initialPrefix':boundary,'steps':steps}
    return output


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=WORK/'chrome-play')
    parser.add_argument('--cache-mb',type=int,default=6144)
    parser.add_argument('--stop-at-target',action='store_true',help='Otherwise continue with the virtual half-value bottom')
    parser.add_argument('--resume-current-game',action='store_true')
    args=parser.parse_args()
    if args.cache_mb<=0:parser.error('Cache budget must be positive')
    route_file=WORK/'optimized-variants-route.json'
    route=json.loads(route_file.read_text())
    report=json.loads((WORK/'optimized-variants-validation.json').read_text())
    if report['routeId']!=route['id'] or not report['valid'] or not report['successes']:
        raise ValueError('The selected route has no completed successful local validation')
    if not args.stop_at_target:route=with_half_boundary(route)
    catalog=json.loads((WORK/'catalog.json').read_text())
    needed={s['policy'] for s in route['steps'] if s['kind']=='leaf'}
    catalog={'policies':[p for p in catalog['policies'] if p['id'] in needed]}
    if len(catalog['policies'])!=len(needed):raise ValueError('Missing runtime policies')
    os.environ.setdefault('TALLNUM_POLICY_CACHE_MB',str(args.cache_mb))
    args.directory.mkdir(parents=True,exist_ok=True)
    atomic_json(args.directory/'session.json',{'route':route,'routeSha256':fingerprint(route_file),
        'validation':report['routeId'],'stopAfterTarget':args.stop_at_target})
    control=args.directory/'control.json'
    atomic_json(control,{'mode':'run','stopAfterTarget':args.stop_at_target})
    play(route,catalog,args.directory,control,browser='chrome',resume_current_game=args.resume_current_game)


if __name__=='__main__':main()
