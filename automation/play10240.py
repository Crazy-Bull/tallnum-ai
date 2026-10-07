"""Play the verified strict dynamic 10240 route in the existing Chrome tab."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
from .browser import play
from .common import atomic_json, fingerprint
from .opening128_40 import build
from .single_six import use_single_six
from .play_upgrade640 import with_half_boundary

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'automation/runs/six-strict-single-002/validation-100-entry-gate-fix'
OPENING = ROOT / 'automation/runs/binary10240/min24/strict-match-edge-guard-003/catalog.json'
DIRECTORY = ROOT / 'automation/runs/six-strict-single-002/chrome-play'


def prepare(directory=DIRECTORY):
    read = lambda path: json.loads(path.read_text(encoding='utf-8'))
    summary = read(EVIDENCE/'summary.json')
    engine = read(EVIDENCE/'validation.json.engine-check.json')
    config = read(EVIDENCE/'configuration.json')
    if (summary['attempts'] != 100 or engine['games'] != 100
            or not engine['seededRngParity'] or engine['forcedDraws']
            or summary['outOfModelBoardGames'] or summary['sixSingleExitViolations']):
        raise ValueError('Missing verified strict dynamic test evidence')
    for name in ('route','catalog'):
        if fingerprint(EVIDENCE.parent/'pending-search'/f'{name}.json') != config[f'{name}Sha256']:
            raise ValueError('Validated input changed: '+name)
    suffix, catalog = read(EVIDENCE/'route.json'), read(EVIDENCE/'catalog.json')
    source_route=read(EVIDENCE.parent/'pending-search/route.json')
    if suffix['steps'] != source_route['steps']:
        raise ValueError('Validated route steps changed')
    opening, opening_catalog = use_single_six(*build(read(OPENING)))
    if opening['completionContract'] != suffix['initialPrefix']:
        raise ValueError('Opening/continuation contracts differ')
    route = deepcopy(suffix)
    route.update(id=suffix['id']+'-chrome-full-opening', initialPrefix=[],
                 steps=opening['steps']+suffix['steps'],
                 releaseAtStage=opening['releaseAtStage'], browserOpeningContract=True,
                 completionContract=[[10240,1,False]])
    route = with_half_boundary(route)
    policies = {p['id']:p for p in catalog['policies']+opening_catalog['policies']}
    catalog = {'policies':list(policies.values())}
    directory.mkdir(parents=True,exist_ok=True)
    atomic_json(directory/'route.json',route)
    atomic_json(directory/'catalog.json',catalog)
    atomic_json(directory/'session.json',{'routeId':route['id'],'source':str(EVIDENCE),
        'routeSha256':config['routeSha256'],'catalogSha256':config['catalogSha256'],
        'validatedRouteSnapshotSha256':fingerprint(EVIDENCE/'route.json'),
        'validatedCatalogSnapshotSha256':fingerprint(EVIDENCE/'catalog.json'),
        'openingSource':str(OPENING),'validation':summary,'originalEngineCheck':engine,
        'twoVisiblePreviews':True,'forcedDraws':False,'existingChromeTab':True})
    return route,catalog


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--resume-current-game',action='store_true')
    parser.add_argument('--directory',type=Path,default=DIRECTORY)
    args=parser.parse_args()
    os.environ['PATH']=str(Path(os.environ.get('TALLNUM_MSYS_ROOT', str(ROOT/'.tools/msys64')))/'ucrt64/bin')+os.pathsep+os.environ['PATH']
    os.environ.setdefault('TALLNUM_POLICY_CACHE_MB','6144')
    route,catalog=prepare(args.directory)
    if args.prepare_only:
        print(json.dumps({'steps':len(route['steps']),'policies':len(catalog['policies']),
                          'directory':str(args.directory)}));return
    control=args.directory/'control.json'
    atomic_json(control,{'mode':'run','stopAfterTarget':False})
    play(route,catalog,args.directory,control,browser='chrome',
         resume_current_game=args.resume_current_game)


if __name__=='__main__':main()
