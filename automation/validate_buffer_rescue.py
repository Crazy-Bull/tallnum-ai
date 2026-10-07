"""Paired 10240 validation of certified buffer rescues and stage rollback."""
from __future__ import annotations

from collections import Counter
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .common import fingerprint
from .route_runtime import RouteExecutor
from .validate_entry_bridge import play, write_json


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'automation/runs/binary10240/min24'
BASE = RUNS / 'entry-bridge-004'
ORIGINAL = RUNS / 'strict-match-edge-guard-003'
OUT = RUNS / 'buffer-rescue-005'


def summary(records, baseline):
    wins = [r for r in records if r['outcome'] == 'success']
    losses = [r for r in records if r['outcome'] == 'failure']
    average = lambda rows: sum(r['drops'] for r in rows) / len(rows) if rows else None
    events = [e for r in records for e in r.get('bufferRescues', [])]
    return {'attempts': len(records), 'successes': len(wins),
            'successRate': len(wins) / len(records) if records else None,
            'meanDropsSuccess': average(wins), 'meanDropsFailure': average(losses),
            'failureReasons': dict(Counter(r['reason'] for r in losses)),
            'rescueAttempts': len(events),
            'rescueCompletions': sum(e['outcome'] == 'recovered' for e in events),
            'rescueUnavailable': sum(e['outcome'] == 'unavailable' for e in events),
            'liveSearchDecisions': sum(len(r.get('liveSearch', [])) for r in records),
            'searchErrors':dict(Counter(e['error'] for r in records for e in r.get('liveSearch',[]) if e.get('error'))),
            'outOfModelBoardGames':sum(any(e.get('error')=='out-of-model-board' for e in r.get('liveSearch',[])) for r in records),
            'searchErrorPolicies':dict(Counter(e.get('policy','unknown') for r in records for e in r.get('liveSearch',[]) if e.get('error'))),
            'staticSearchFallbacks':sum(bool(e.get('searchFallback')) for r in records for e in r.get('liveSearch',[])),
            'sixSingleExits':sum(len(r.get('sixSingleExits',[])) for r in records),
            'sixSingleExitViolations':sum(e.get('strict') and not e.get('tidy') for r in records for e in r.get('sixSingleExits',[])),
            'meanSelectedPolicyProbability': (sum(e['score'] for r in records
                for e in r.get('liveSearch', []) if isinstance(e.get('score'), (int,float))) /
                sum(isinstance(e.get('score'), (int,float)) for r in records
                    for e in r.get('liveSearch', [])) if any(isinstance(e.get('score'), (int,float))
                    for r in records for e in r.get('liveSearch', [])) else None),
            'successesGained': [r['seed'] for r in records if r['outcome'] == 'success'
                                and baseline[r['seed']]['outcome'] != 'success'],
            'successesLost': [r['seed'] for r in records if r['outcome'] != 'success'
                              and baseline[r['seed']]['outcome'] == 'success']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=OUT)
    parser.add_argument('--policy-dir', type=Path, default=OUT / 'policies')
    parser.add_argument('--mapping', type=Path,
                        help='JSON mapping of match targets to certified buffer targets')
    parser.add_argument('--route-file', type=Path,
                        help='use an already prepared route snapshot')
    parser.add_argument('--catalog-file', type=Path,
                        help='use an already prepared catalog snapshot')
    parser.add_argument('--baseline-run', type=Path,
                        help='paired seed/replay source; defaults to entry-bridge-004')
    parser.add_argument('--seed-limit', type=int, default=100)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    games = out / 'games'
    games.mkdir(exist_ok=True)
    route_file = (args.route_file or ORIGINAL / 'continuation40.json').resolve()
    catalog_file = (args.catalog_file or ORIGINAL / 'catalog.json').resolve()
    baseline_run = (args.baseline_run or BASE).resolve()
    route = json.loads(route_file.read_text(encoding='utf-8'))
    catalog = json.loads(catalog_file.read_text(encoding='utf-8'))
    extra = json.loads((args.policy_dir / 'catalog.json').read_text(encoding='utf-8'))['policies']
    mapping = (json.loads(args.mapping.read_text(encoding='utf-8')) if args.mapping
               else {'32': [30]})
    match_targets = {str(s['target']) for s in route['steps']
                     if s.get('exit') == 'match'}
    if args.mapping and set(mapping) != match_targets:
        raise ValueError(f'Buffer rescue must cover every match target: {match_targets}')
    selected = []
    for match_target, buffer_targets in mapping.items():
        if not buffer_targets:
            raise ValueError(f'No buffer for match {match_target}')
        route_ids = []
        for buffer_target in buffer_targets:
            candidates = [p for p in extra if p['target'] == buffer_target
                          and p['exit'] == 'buffer'
                          and p.get('petsc', {}).get('verified')
                          and p['petsc'].get('exitEvaluationRounds', 0) >= 2
                          and p.get('successNoExtraCombos') is True
                          and p.get('maxValue', 0) >= 48
                          and p.get('maxGoalCells', 5) <= 4 and p.get('cells') == 5]
            if not candidates:
                raise ValueError(f'No certified clean buffer for {match_target}: {buffer_target}')
            item = max(candidates, key=lambda p: p['statistics']['p'])
            if int(match_target) // 10 != buffer_target // 10 or int(match_target) == buffer_target:
                raise ValueError('Buffer and match must have distinct targets with the same head')
            selected.append(item)
            route_ids.append(item['id'])
        route.setdefault('bufferRescuePolicies', {})[match_target] = route_ids
    catalog['policies'].extend({p['id']: p for p in selected}.values())
    configuration = {'baseline': str(baseline_run), 'attempts': args.seed_limit,
                     'sameSeeds': True, 'twoVisiblePreviews': True, 'forcedDraws': False,
                     'routeSha256': fingerprint(route_file),
                     'catalogSha256': fingerprint(catalog_file),
                     'baselineRun': str(baseline_run),
                     'seedLimit': args.seed_limit,
                     'bufferPolicies': [{key: p[key] for key in ('id', 'policySha256')}
                                        | {'petscRounds': p['petsc']['exitEvaluationRounds']}
                                        for p in selected],
                     'bufferMapping': mapping,
                     'sourceHashes': {name: fingerprint(ROOT / 'automation' / name)
                                      for name in ('common.py', 'runtime.py', 'route_runtime.py',
                                                   'entry_bridge.py', 'validate_buffer_rescue.py')}}
    saved = out / 'configuration.json'
    if saved.exists() and json.loads(saved.read_text(encoding='utf-8')) != configuration:
        raise ValueError('Saved run configuration differs; do not mix checkpoints')
    write_json(saved, configuration)
    write_json(out / 'route.json', route)
    write_json(out / 'catalog.json', catalog)
    for name in ('runtime.py', 'route_runtime.py', 'entry_bridge.py', 'validate_buffer_rescue.py'):
        shutil.copyfile(ROOT / 'automation' / name, out / name)
    baseline = {r['seed']: r for r in map(json.loads,
                 (baseline_run / 'main-ledger.jsonl').read_text(encoding='utf-8').splitlines())}
    executor = RouteExecutor(route, catalog)
    records = []
    try:
        for seed in list(baseline)[:args.seed_limit]:
            checkpoint = games / f'{seed}.json'
            if checkpoint.exists():
                result = json.loads(checkpoint.read_text(encoding='utf-8'))
            else:
                old = json.loads((baseline_run / 'games' / f'{seed}.json').read_text(encoding='utf-8'))
                result = play(old['replay'], old['record'], executor)
                result['record']['bufferRescues'] = executor.buffer_rescue_events[:]
                result['record']['liveSearch'] = executor.search_events[:]
                result['record']['sixSingleExits'] = executor.single_exit_events[:]
                write_json(checkpoint, result)
            records.append(result['record'])
            progress = {**summary(records, baseline), 'stage': 'simulation',
                        'lastSeed': seed, 'lastRouteStage': result['record']['stage'],
                        'updatedAt': time.time()}
            write_json(out / 'progress.json', progress)
            print(json.dumps(progress), flush=True)
    except Exception as error:
        write_json(out / 'infrastructure-error.json',
                   {'error': repr(error), 'completed': len(records),
                    'checkpoint': getattr(executor, 'validation_error_checkpoint', None)})
        raise
    finally:
        executor.close()
    result_summary = summary(records, baseline)
    write_json(out / 'summary.json', result_summary)
    with (out / 'main-ledger.jsonl').open('w', encoding='utf-8') as dest:
        for record in records:
            dest.write(json.dumps(record, separators=(',', ':')) + '\n')
    temporary = out / 'validation.tmp'
    with temporary.open('w', encoding='utf-8') as dest:
        dest.write('{"configuration":')
        json.dump(configuration, dest)
        dest.write(',"reports":[{"mode":"buffer-rescue-paired","summary":')
        json.dump(result_summary, dest)
        dest.write(',"replays":[')
        for index, record in enumerate(records):
            if index:
                dest.write(',')
            replay = json.loads((games / f'{record["seed"]}.json').read_text(encoding='utf-8'))['replay']
            json.dump(replay, dest, separators=(',', ':'))
        dest.write(']}]}\n')
    temporary.replace(out / 'validation.json')
    write_json(out / 'progress.json', {**result_summary, 'stage': 'awaiting-js-replay',
                                       'updatedAt': time.time()})
    with (out / 'replay-check.log').open('w', encoding='utf-8') as log:
        checked = subprocess.run(['node', str(ROOT / 'automation/binary_random_check.mjs'),
                                  str(out / 'validation.json')], stdout=log,
                                 stderr=subprocess.STDOUT)
    if checked.returncode:
        raise RuntimeError('Original JavaScript engine replay failed')
    result_summary['originalEngineCheck'] = json.loads(
        (out / 'validation.json.engine-check.json').read_text(encoding='utf-8'))
    write_json(out / 'summary.json', result_summary)
    write_json(out / 'progress.json', {**result_summary, 'stage': 'complete',
                                       'updatedAt': time.time()})


if __name__ == '__main__':
    main()
