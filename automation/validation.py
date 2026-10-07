from __future__ import annotations

import math
import time
import hashlib
import json
from pathlib import Path
import numpy as np
from . import game
from .runtime import Executor, RouteFailure, IncompatibleState
from .common import event, atomic_json, execution_fingerprint


def summarize(records, bootstrap_seed=918273):
    n = len(records)
    wins = np.array([r['outcome']=='success' for r in records], dtype=float)
    costs = np.array([r['drops'] for r in records], dtype=float)
    successes = int(wins.sum())
    failures = [r['drops'] for r in records if r['outcome']=='failure']
    invalid = sum(r['outcome']=='incompatible' for r in records)
    unfinished = sum(r['outcome']=='limit' for r in records)
    estimate = float(costs.sum()/successes) if successes and not invalid and not unfinished else None
    interval = None
    if estimate is not None:
        rng = np.random.default_rng(bootstrap_seed)
        samples = []
        for _ in range(500):
            indices = rng.integers(0, n, n)
            w = wins[indices].sum()
            samples.append(costs[indices].sum()/w if w else math.inf)
        # Nearest-rank endpoints preserve an infinite upper bound when a
        # bootstrap sample has no successes, without inf-inf interpolation.
        low, high = np.quantile(samples, [.025,.975], method='inverted_cdf')
        interval = [float(low) if np.isfinite(low) else None, float(high) if np.isfinite(high) else None]
    return {'attempts':n, 'successes':successes, 'successRate':successes/n if n else 0,
            'successDrops':float(costs[wins==1].mean()) if successes else None,
            'failureDrops':float(np.mean(failures)) if failures else None,
            'incompatible':invalid, 'unfinished':unfinished, 'expectedTotalDrops':estimate,
            'confidence95':interval, 'valid':not invalid and not unfinished}


def validate(route, catalog, attempts=100, seed_start=100000, max_actions=100000, progress=True):
    if route.get('version') == 2:
        from .route_runtime import RouteExecutor
        executor = RouteExecutor(route, catalog)
    else:
        executor = Executor(route, catalog)
    records = []
    first_success_replay = None
    started = time.monotonic()
    try:
        for i in range(attempts):
            seed = (seed_start+i) & 0xffffffff
            state = game.new_game(seed, route['cells'] if route.get('version')==2 else 7)
            if route.get('initialPrefix'):
                state['tower']=[game.tile(state,v) for v,span,group in route['initialPrefix']]+state['tower']
            executor.reset()
            outcome, reason = 'limit', 'action-budget'
            try:
                for action_index in range(max_actions):
                    if progress and action_index and action_index%10000==0:
                        event('validation-attempt',attempt=i+1,stage=executor.stage,drops=state['drops'],actions=action_index)
                    before = game.observation(state)
                    action = executor.next_action(before)
                    if action is None:
                        outcome, reason = 'success', ''
                        if first_success_replay is None:
                            first_success_replay={'version':4,'numberSet':'standard','towerLimit':state['towerLimit'],
                                'poolUnlockAction':0 if state['towerLimit']==7 else None,'seed':seed,'actions':state['actionLog'][:],
                                'initialPrefix':route.get('initialPrefix',[])}
                        break
                    state = game.apply(state, action)
                    executor.accept(before, action, game.observation(state))
            except RouteFailure as error:
                outcome, reason = 'failure', str(error)
            except IncompatibleState as error:
                outcome, reason = 'incompatible', str(error)
            records.append({'seed':seed,'outcome':outcome,'reason':reason,'drops':state['drops'],
                            'actions':state['actions'],'stage':executor.stage,'failureContext':getattr(executor,'failure_context',None),
                            'board':game.signature(state) if outcome=='incompatible' else None})
            if progress and (i+1)%100==0:
                event('validation-progress', completed=i+1, attempts=attempts)
            # Deterministic structural mismatches invalidate the route. Do not
            # burn the remaining 10,000 simulations on a known adapter defect.
            if outcome in ('incompatible','limit'):
                break
    finally:
        executor.close()
    return {'routeId':route['id'], 'seedStart':seed_start, 'requestedAttempts':attempts,
            'elapsedSeconds':time.monotonic()-started, **summarize(records), 'records':records,
            'firstSuccessReplay':first_success_replay}


def rank(plan, catalog, attempts=100, cache_directory=None, candidate_limit=20):
    if not isinstance(candidate_limit,int) or not 1<=candidate_limit<=20:
        raise ValueError('Candidate limit must be in [1, 20]')
    def cached(route, seed):
        identity=json.dumps({'route':route,'catalog':catalog,'attempts':attempts,'seed':seed,
                             'execution':execution_fingerprint()},sort_keys=True)
        key=hashlib.sha256(identity.encode()).hexdigest()
        path=Path(cache_directory)/(key+'.json') if cache_directory else None
        if path and path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
        result=validate(route,catalog,attempts,seed)
        if path:
            atomic_json(path,result)
        return result
    results = [cached(r,100000) for r in plan['routes'][:candidate_limit]]
    eligible = [r for r in results if r['valid'] and r['expectedTotalDrops'] is not None]
    eligible.sort(key=lambda r:r['expectedTotalDrops'])
    selected = eligible[0]['routeId'] if eligible else None
    holdout = None
    if selected:
        route = next(r for r in plan['routes'] if r['id']==selected)
        holdout = cached(route,2000000000)
    overlap = False
    if len(eligible)>1:
        first, second = eligible[:2]
        a,b=first['confidence95'],second['confidence95']
        overlap = a[1] is None or b[0] is None or a[1]>=b[0]
    return {'selectedRoute':selected, 'results':results, 'holdout':holdout,
            'candidatesEvaluated':len(results), 'candidateLimit':candidate_limit,
            'selectionScope':'first-modeled-candidates',
            'rankingUncertain':overlap, 'verified': bool(holdout and holdout['valid'] and holdout['successes']>0)}
