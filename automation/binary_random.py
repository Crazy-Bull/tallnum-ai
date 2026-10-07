"""Seeded real-rule stochastic tests of a binary route, with no forced draws."""
import argparse
from collections import Counter
import json
from pathlib import Path
import random
import time

from . import game
from .binary_routes import verify_tree
from .common import atomic_json, fingerprint
from .route_runtime import RouteExecutor
from .runtime import RouteFailure, IncompatibleState
from .validation import summarize


def compile_route(plan, weights, checkpoint=None):
    steps=verify_tree(plan['tree'],plan['cells'])['steps']
    if checkpoint is not None:
        first=next(i for i,s in enumerate(steps) if s['after']==[[checkpoint,1,False]])
        steps=steps[first+1:]
    selected={}
    checked_hashes={}
    def policy_hash(path):
        key=str(Path(path).resolve())
        if key not in checked_hashes:checked_hashes[key]=fingerprint(path)
        return checked_hashes[key]
    for step in steps:
        if step['kind']!='leaf':continue
        entry=weights['entries'][step['template']]
        path=Path(entry.get('manifest',Path(entry['policy']).parent/(entry['policyId']+'.json')))
        item=json.loads(path.read_text(encoding='utf-8'))
        if item['policySha256']!=entry['policySha256'] or policy_hash(item['policy'])!=entry['policySha256']:
            raise ValueError('Selected policy changed')
        selected[item['id']]=item
        step['policy']=item['id']
    # Native adapters can share a single worker while exposing different exits.
    for item in list(selected.values()):
        key=item.get('workerKey',item['id'])
        if key not in selected:
            entry=next(e for e in weights['entries'].values() if e['policyId']==key)
            path=Path(entry.get('manifest',Path(entry['policy']).parent/(key+'.json')))
            worker=json.loads(path.read_text(encoding='utf-8'))
            if policy_hash(worker['policy'])!=worker['policySha256']:raise ValueError('Worker policy changed')
            selected[key]=worker
    return ({'id':'binary-random','version':2,'kind':'stages','cells':plan['cells'],
             'target':plan['target'],'initialPrefix':[] if checkpoint is None else [[checkpoint,1,False]],
             'steps':steps}, {'policies':list(selected.values())})


def initial_state(seed,cells,checkpoint=None):
    state=game.new_game(seed,cells)
    if checkpoint is not None:
        # Explicitly synthetic diagnostic entry. Never count as real-opening success.
        state['tower']=[game.tile(state,checkpoint)]
        state['unlocked']=game.POOL[:]
        state['lastRandomValue']=None;state['repeatCount']=0
        state['queue']=[game.draw(state) for _ in range(4)]
    return state


def run(plan,weights,attempts=100,seed=102401,checkpoint=None,max_actions=20000):
    route,catalog=compile_route(plan,weights,checkpoint)
    executor=RouteExecutor(route,catalog)
    records=[];replays=[];start=time.monotonic()
    rng=random.Random(seed)
    seeds=rng.sample(range(1,2**32),attempts)
    try:
        for index,game_seed in enumerate(seeds):
            state=initial_state(game_seed,plan['cells'],checkpoint)
            initial=json.loads(json.dumps(state))
            executor.reset();trace=[];outcome='limit';reason='action-budget'
            peak=game.physical(state);context=None
            try:
                for _ in range(max_actions):
                    before=game.observation(state)
                    action=executor.next_action(before)
                    if executor.failure_reason:
                        outcome='failure';reason=executor.failure_reason
                        context=executor.failure_context
                        break
                    if action is None:
                        outcome='success';reason='';break
                    state=game.apply(state,action)
                    after=game.observation(state)
                    executor.accept(before,action,after)
                    peak=max(peak,game.physical(state))
                    trace.append({'action':action,'board':game.signature(state),
                                  'queue':state['queue'][:],'unlocked':state['unlocked'][:],
                                  'rngState':state['rngState'],'gameOver':state['gameOver']})
            except RouteFailure as error:outcome='failure';reason=str(error)
            except (IncompatibleState,ValueError) as error:outcome='incompatible';reason=str(error)
            record={'seed':game_seed,'outcome':outcome,'reason':reason,'drops':state['drops'],
                    'actions':state['actions'],'stage':executor.stage,'failureContext':context,
                    'board':game.signature(state),'unlocked':state['unlocked'],
                    'maximumPhysicalCells':peak}
            records.append(record)
            replays.append({'seed':game_seed,'outcome':outcome,'initial':initial,'trace':trace})
            if (index+1)%25==0:
                print(json.dumps({'mode':'real-opening' if checkpoint is None else 'synthetic-checkpoint',
                                  'completed':index+1,'successes':sum(r['outcome']=='success' for r in records)}),flush=True)
    finally:executor.close()
    stats=summarize(records)
    # Conservative route abandonment is not game over; unfinished actual games
    # must not supply an entire-game restart expectation.
    stats['expectedTotalDrops']=None;stats['confidence95']=None
    return {'mode':'real-opening' if checkpoint is None else 'synthetic-checkpoint',
            'checkpoint':checkpoint,'forcedDraws':False,'visiblePreviews':2,
            'wholeGameRestartCostMeasured':False,'elapsedSeconds':time.monotonic()-start,
            **stats,'failureReasons':dict(Counter(r['reason'] for r in records if r['outcome']!='success')),
            'stageCounts':dict(Counter(str(r['stage']) for r in records)),
            'maximumStageReached':max((r['stage'] for r in records),default=0),
            'records':records,'replays':replays}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    parser.add_argument('--weights',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--attempts',type=int,default=100)
    parser.add_argument('--seed',type=int,default=102401)
    parser.add_argument('--max-actions',type=int,default=20000)
    args=parser.parse_args()
    if not 1<=args.attempts<=10000:parser.error('attempts must be 1..10000')
    plan=json.loads(args.plan.read_text());weights=json.loads(args.weights.read_text())
    reports=[]
    for checkpoint in (None,10):
        report=run(plan,weights,args.attempts,args.seed,checkpoint,args.max_actions)
        reports.append(report)
        atomic_json(args.output,{'planSha256':fingerprint(args.plan),'weightsSha256':fingerprint(args.weights),
                                 'reports':reports})
        print(json.dumps({k:v for k,v in report.items() if k not in ('records','replays')},indent=2),flush=True)


if __name__=='__main__':main()
