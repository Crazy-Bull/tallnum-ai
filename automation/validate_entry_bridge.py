"""Paired real-game validation using the saved, unchanged opening replays.

One completed game is saved at a time. All real drops retain the original RNG;
only observation() (two previews) is passed to the controller.
"""
import argparse
from copy import deepcopy
from collections import Counter
import json
from pathlib import Path
import shutil
import subprocess
import sys
import os
import time
import msvcrt
import ijson

from . import game
from .common import fingerprint
from .full10240 import bind40
from .route_runtime import RouteExecutor

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / 'automation/runs/binary10240/min24/strict-match-edge-guard-003'
DEFAULT_OUT = ROOT / 'automation/runs/binary10240/min24/entry-bridge-004'


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as dest:
        json.dump(value, dest, separators=(',', ':'))
    temporary.replace(path)


def row(state, action):
    return {'action': action, 'board': game.signature(state), 'queue': state['queue'][:],
            'unlocked': state['unlocked'][:], 'rngState': state['rngState'],
            'gameOver': state['gameOver']}


def play(old_replay, old_record, executor, regression=False, *, checkpoint=None, start_stage=None, max_actions=25000):
    seed = old_replay['seed']
    state = game.new_game(seed, 10)
    if state != old_replay['initial']:
        raise ValueError('Original seeded initial state differs')
    trace = []
    if not old_record['joined40']:
        # Preserve the verified opening failures: this change concerns only
        # continuation entry handling. No synthetic restart or queue edits.
        return {'record': old_record, 'replay': old_replay}
    if checkpoint is not None:
        if str(checkpoint) not in old_record['milestones']:
            return {'record':old_record,'replay':old_replay}
        def reached():
            return any(t['kind']=='tile' and t['value']==checkpoint for t in state['tower'])
    elif regression:
        wanted = [4, 6, 4, 5120, 960, 640, 256, 32]
        def reached():
            return ([t['value'] for t in state['tower']] == wanted
                    and state['queue'][:2] == [15, 8])
    else:
        def reached():
            # A terminal GROUP/EDGE can finish the opening at the same drop
            # count. Replay those free actions too, before binding ordinary40.
            return (state['drops'] == old_record['milestones']['finalSingle40']
                    and any(t['kind'] == 'tile' and t['value'] == 40 for t in state['tower'])
                    and not any(t['kind'] == 'group' for t in state['tower']))
    for previous in old_replay['trace']:
        if reached():
            break
        state = game.apply(state, previous['action'])
        fresh = row(state, previous['action'])
        if json.dumps(fresh, sort_keys=True) != json.dumps(previous, sort_keys=True):
            raise ValueError('Saved prefix differs from seeded real-game replay')
        trace.append(fresh)
    if not reached():
        raise ValueError('Saved replay does not contain the required entry')
    if checkpoint is not None:
        executor.reset()
        executor.stage=start_stage
        executor.initial_bound=True
        executor.fixed_ids={next(t['id'] for t in state['tower'] if t['kind']=='tile' and t['value']==checkpoint)}
        executor._contract(game.observation(state),executor.route['steps'][start_stage]['before'])
        milestones={k:v for k,v in old_record['milestones'].items() if v<=state['drops']}
    elif regression:
        executor.reset()
        executor.stage = 213
        executor.initial_bound = True
        executor.fixed_ids = {t['id'] for t in state['tower'][3:]}
        milestones = {k: v for k, v in old_record['milestones'].items() if v <= state['drops']}
    else:
        bind40(executor, game.observation(state))
        milestones = {k: v for k, v in old_record['milestones'].items()
                      if v <= old_record['milestones']['finalSingle40']}
    context = None
    reason = 'action-budget'
    outcome = 'limit'
    try:
        for count in range(max_actions):
            ordinary = {t['value'] for t in state['tower'] if t['kind'] == 'tile'}
            for target in (80, 120, 160, 320, 640, 1280, 2560, 5120, 10240):
                if target in ordinary:
                    milestones.setdefault(str(target), state['drops'])
            if 10240 in ordinary:
                outcome, reason = 'success', ''
                break
            if state['gameOver']:
                outcome, reason = 'failure', executor.failure_reason or 'actual-game-over'
                break
            if regression and executor.stage > 213:
                outcome, reason = 'regression-passed', 'five-cell32-match-completed'
                break
            before = game.observation(state)
            action = executor.next_action(before)
            if executor.failure_reason and context is None:
                context = deepcopy(executor.failure_context)
            if action is None:
                raise ValueError('Executor finished without actual 10240')
            state = game.apply(state, action)
            executor.accept(before, action, game.observation(state))
            trace.append(row(state, action))
            if count and count % 2000 == 0:
                print(json.dumps({'seed': seed, 'drops': state['drops'], 'stage': executor.stage,
                                  'bridges': len(executor.entry_bridge_events)}), flush=True)
    except Exception:
        # Infrastructure exceptions remain distinct from game deaths.
        executor.validation_error_checkpoint = {'state': state, 'trace': trace,
                                                 'seed': seed, 'stage': executor.stage}
        raise
    record = {'seed': seed, 'outcome': outcome, 'reason': reason, 'drops': state['drops'],
              'actions': state['actions'], 'stage': executor.stage, 'milestones': milestones,
              'joined40': True, 'failureContext': context, 'board': game.signature(state),
              'unlocked': state['unlocked'][:], 'entryBridges': deepcopy(executor.entry_bridge_events)}
    return {'record': record, 'replay': {'seed': seed, 'initial': old_replay['initial'],
                                        'trace': trace, 'outcome': outcome}}


def summarize(records):
    successes = [r for r in records if r['outcome'] == 'success']
    failures = [r for r in records if r['outcome'] == 'failure']
    mean = lambda rows: sum(r['drops'] for r in rows) / len(rows) if rows else None
    return {'attempts': len(records), 'successes': len(successes),
            'successRate': len(successes) / len(records) if records else None,
            'meanDropsSuccess': mean(successes), 'meanDropsFailure': mean(failures),
            'failureReasons': dict(Counter(r['reason'] for r in failures)),
            'bridgeCount': sum(len(r.get('entryBridges', [])) for r in records),
            'unfinished': sum(r['outcome'] == 'limit' for r in records)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASE)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--regression', action='store_true')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    games = args.out / 'games'
    games.mkdir(exist_ok=True)
    with (args.out / 'run.lock').open('a+b') as lock:
        if lock.tell() == 0:
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        old_records = {r['seed']: r for r in map(json.loads, (args.baseline / 'main-ledger.jsonl').read_text().splitlines())}
        route = json.loads((args.baseline / 'continuation40.json').read_text())
        catalog = json.loads((args.baseline / 'catalog.json').read_text())
        sources = ['runtime.py', 'route_runtime.py', 'entry_bridge.py']
        configuration = {'baseline': str(args.baseline), 'attempts': 1 if args.regression else 100,
                         'seedCohort': 'original-main', 'opening': 'unchanged-saved-real-opening',
                         'routeSha256': fingerprint(args.baseline / 'continuation40.json'),
                         'catalogSha256': fingerprint(args.baseline / 'catalog.json'),
                         'controller': 'entry-bridge-depth4-width20-one-observed-drop',
                         'sourceHashes': {p: fingerprint(ROOT / 'automation' / p) for p in sources},
                         'policyModified': False, 'forcedDraws': False, 'visiblePreviews': 2,
                         'policyCertification': 'unchanged, already PETSc-verified policies',
                         'regression': args.regression}
        saved_config = args.out / 'configuration.json'
        if saved_config.exists() and json.loads(saved_config.read_text()) != configuration:
            raise ValueError('Resume configuration differs from the completed checkpoints')
        write_json(saved_config, configuration)
        for name in sources:
            shutil.copyfile(ROOT / 'automation' / name, args.out / name)
        executor = RouteExecutor(route, catalog)
        records = []
        try:
            with (args.baseline / 'validation.json').open('rb') as source:
                for replay in ijson.items(source, 'reports.item.replays.item', use_float=True):
                    seed = replay['seed']
                    if args.regression and seed != 2868527136:
                        continue
                    checkpoint = games / f'{seed}.json'
                    if checkpoint.exists():
                        record = json.loads(checkpoint.read_text())['record']
                    else:
                        result = play(replay, old_records[seed], executor, args.regression)
                        record = result['record']
                        write_json(checkpoint, result)
                    records.append(record)
                    progress = {**summarize(records), 'stage': 'simulation', 'updatedAt': time.time(),
                                'lastSeed': seed, 'lastOutcome': record['outcome'],
                                'lastRouteStage': record['stage']}
                    write_json(args.out / 'progress.json', progress)
                    print(json.dumps(progress), flush=True)
                    if args.regression:
                        break
        except Exception as error:
            write_json(args.out / 'infrastructure-error.json',
                       {'error': repr(error), 'completed': len(records),
                        'checkpoint': getattr(executor, 'validation_error_checkpoint', None)})
            raise
        finally:
            executor.close()
        summary = summarize(records)
        write_json(args.out / 'summary.json', summary)
        with (args.out / 'main-ledger.jsonl').open('w', encoding='utf-8') as dest:
            for record in records:
                dest.write(json.dumps(record, separators=(',', ':')) + '\n')
        # Stream the report rather than serialize all games in memory.
        temporary = args.out / 'validation.tmp'
        with temporary.open('w', encoding='utf-8') as dest:
            dest.write('{"configuration":')
            json.dump(configuration, dest)
            dest.write(',"reports":[{"mode":"entry-bridge-paired","summary":')
            json.dump(summary, dest)
            dest.write(',"replays":[')
            for index, record in enumerate(records):
                if index:
                    dest.write(',')
                saved = json.loads((games / f'{record["seed"]}.json').read_text())
                json.dump(saved['replay'], dest, separators=(',', ':'))
            dest.write(']}]}\n')
        temporary.replace(args.out / 'validation.json')
        write_json(args.out / 'progress.json', {**summary, 'stage': 'simulation-complete-awaiting-js-replay',
                                              'updatedAt': time.time()})
        print(json.dumps({'stage': 'original-engine-check', **summary}), flush=True)
        environment = {**os.environ, 'TALLNUM_PYTHON': sys.executable}
        with (args.out / 'replay-check.log').open('w', encoding='utf-8') as log:
            checked = subprocess.run(['node', str(ROOT / 'automation/binary_random_check.mjs'),
                                      str(args.out / 'validation.json')], env=environment,
                                     stdout=log, stderr=subprocess.STDOUT)
        if checked.returncode:
            raise RuntimeError('Original JavaScript engine replay failed; see replay-check.log')
        engine = json.loads((args.out / 'validation.json.engine-check.json').read_text())
        summary['originalEngineCheck'] = engine
        if not args.regression:
            summary['baseline'] = summarize(list(old_records.values()))
            summary['successesGained'] = [r['seed'] for r in records
                                         if r['outcome'] == 'success' and old_records[r['seed']]['outcome'] != 'success']
            summary['successesLost'] = [r['seed'] for r in records
                                       if r['outcome'] != 'success' and old_records[r['seed']]['outcome'] == 'success']
        write_json(args.out / 'summary.json', summary)
        write_json(args.out / 'progress.json', {**summary, 'stage': 'complete', 'updatedAt': time.time()})
        print(json.dumps({'stage': 'complete', **summary}), flush=True)


if __name__ == '__main__':
    main()
