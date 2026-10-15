"""Ten-cell opening controller using real unlocks and six-cell proposals.

Only the two visible previews are searched. No hidden queue, RNG state,
artificial draws, board resets, or removal of bootstrap residuals is allowed.
Template probabilities are never used as real-opening probabilities.
"""
from collections import Counter, OrderedDict
from copy import deepcopy
import math

from . import game
from .route_runtime import StageExecutor, RouteExecutor
from .runtime import RouteFailure, IncompatibleState
from .library import PolicyWorker


def actions(obs):
    if obs['queue'] and obs['queue'][0] is not None:
        yield {'kind': 'drop'}
        if len(obs['tower']) > 1:
            yield {'kind': 'up'}
            yield {'kind': 'down'}
    tower = obs['tower']
    if not any(t['kind'] == 'group' for t in tower):
        for i in range(len(tower)-1):
            for end in range(i+2, min(i+5, len(tower))+1):
                total = sum(t['value'] for t in tower[i:end])
                neighbors = tower[i-1:i] + tower[end:end+1]
                # A Group is useful here only if it merges or unlocks an EDGE.
                if any(t['value'] == total or total//10 > 0 and t['value']//10 == total//10
                       for t in neighbors):
                    yield {'kind': 'group', 'indices': list(range(i, end))}
    if any(a['value']//10 > 0 and a['value']//10 == b['value']//10
           for a,b in zip(tower, tower[1:])):
        yield {'kind': 'edge'}


def score(obs):
    if obs['gameOver']:
        return -1e9
    tower = obs['tower']; mass = sum(t['value'] for t in tower)
    unlocked = obs['unlocked']
    value = 1000*(10 in unlocked) + 1000*(15 in unlocked)
    value += 2*min(mass, 200) - 75*game.physical(obs)
    ordinary = [t['value'] for t in tower if t['kind'] == 'tile']
    value += 12*sum(math.log2(max(2,v)) for v in ordinary)
    if 15 in unlocked:
        value += 45*sum(math.log2(v/10) for v in ordinary if v%10 == 0 and v <= 320)
        value -= .25*sum(v for v in ordinary if v >= 64 and v%10 != 0)
    if 320 in ordinary:
        value += 10000
        if tower[0]['kind'] == 'tile' and tower[0]['value'] == 320:
            value += 3000
            value -= 30*sum(t['value'] > 48 or t['kind'] == 'group' for t in tower[1:])
    return value


def search_action(obs, width=8, depth=4):
    """Bounded receding search; at most two real draws have known values."""
    frontier = [(deepcopy(obs), None, 0)]
    best = None; seen = set()
    for _ in range(depth):
        next_frontier = []
        for state, first, cost in frontier:
            for action in actions(state):
                try:
                    after = game.predict(state, action)
                except (ValueError, IndexError):
                    continue
                if after['gameOver']:
                    continue
                key = (tuple(game.signature(after)), tuple(after['queue']), tuple(after['unlocked']))
                if key in seen:
                    continue
                seen.add(key)
                total_cost = cost + (1 if action['kind'] in ('drop','up','down') else .1)
                entry = (after, first or action, total_cost)
                rank = score(after)-.5*total_cost
                if best is None or rank > best[0]:
                    best = (rank, entry[1])
                next_frontier.append(entry)
        frontier = sorted(next_frontier, key=lambda x: score(x[0])-.5*x[2], reverse=True)[:width]
        if not frontier:
            break
    return best[1] if best else {'kind': 'drop'}


class OpeningController:
    def __init__(self, six_catalog, continuation, catalog, worker_factory=PolicyWorker):
        self.six = {p['target']: p for p in six_catalog['policies']
                    if p.get('cells') == 6 and p['exit'] == 'single' and p['target'] in (32,40,48)}
        if set(self.six) != {32,40,48}:
            raise ValueError('Need all three six-cell ordinary single proposals')
        self.worker_factory = worker_factory
        self.workers = OrderedDict()
        self.continuation = continuation; self.catalog = catalog
        self.reset()

    def worker(self, item):
        key = item.get('workerKey', item['id'])
        if key not in self.workers:
            # Keep at most one large six-cell worker resident at once.
            if item.get('cells') == 6:
                for old_key in list(self.workers):
                    if old_key.startswith('six'):
                        self.workers.pop(old_key).close()
            self.workers[key] = self.worker_factory(item)
        return self.workers[key]

    def reset(self):
        self.hint = None; self.hint_drops = 0
        self.joined = False; self.route = None; self.pending_hint = False
        self.counts = Counter(); self.handoff_rejections = Counter()

    def close(self):
        for worker in self.workers.values():
            worker.close()
        self.workers.clear()

    def can_join(self, obs):
        tower = obs['tower']
        if not tower or tower[0]['kind'] != 'tile' or tower[0]['value'] != 320:
            return False
        if set(game.POOL)-set(obs['unlocked']):
            return False
        first = next(s for s in self.continuation['steps'] if s['kind']=='leaf')
        item = next(p for p in self.catalog['policies'] if p['id']==first['policy'])
        return (game.physical({'tower':tower[1:]}) < item.get('cells',5)
                and all(t['value'] <= item['maxValue'] and t['kind'] == 'tile' for t in tower[1:]))

    def next_action(self, obs):
        self.pending_hint = False
        if obs['gameOver']:
            return None
        if self.joined:
            return self.route.next_action(obs)
        if self.can_join(obs):
            candidate = RouteExecutor(self.continuation,self.catalog,worker_factory=self.worker)
            action = candidate.next_action(obs)
            if not candidate.failure_reason:
                self.route = candidate; self.joined = True; self.hint = None
                self.counts['join320'] += 1
                return action
            self.handoff_rejections[candidate.failure_reason] += 1
        if self.hint is not None and obs['drops']-self.hint_drops > 24:
            self.hint = None
        if self.hint is None:
            # Existing large ordinary blocks remain real protected input.
            fixed = []
            for t in obs['tower']:
                if t['kind'] != 'tile' or t['value'] < 32:
                    break
                fixed.append(t)
            active = obs['tower'][len(fixed):]
            if game.physical({'tower':active}) < 6 and 10-len(fixed) >= 6:
                target = 32 if 15 not in obs['unlocked'] else 40
                if active and any(t['value'] in (24,48) for t in active):
                    target = 48
                item = self.six[target]
                if all(t['value'] <= item['maxValue'] for t in active):
                    leaf = {'kind':'leaf','policy':item['id'],'target':target,'exit':'single'}
                    self.hint = StageExecutor({'kind':'stage','target':-1,'towerLimit':10,'children':[leaf]},
                                               {'policies':[item]},self.worker)
                    self.hint.fixed_ids = {t['id'] for t in fixed}
                    self.hint_drops = obs['drops']
        if self.hint is not None:
            try:
                action = self.hint.next_action(obs)
                after = game.predict(obs, action) if action is not None else None
                # Reject unsafe proposals using the complete ten-cell board.
                if (action is not None and not self.hint.failure_reason and not after['gameOver']
                        and not (15 not in obs['unlocked'] and sum(t['value'] for t in after['tower'])
                                 < sum(t['value'] for t in obs['tower']))):
                    self.pending_hint = True
                    self.counts['six'+str(self.hint.leaves[0]['target'])] += 1
                    return action
            except (RouteFailure,IncompatibleState,ValueError):
                pass
            self.hint = None
        self.counts['search'] += 1
        return search_action(obs)

    def accept(self, before, action, after):
        if self.joined:
            self.route.accept(before,action,after)
        elif self.pending_hint and self.hint is not None:
            try:
                self.hint.accept(before,action,after)
            except (RouteFailure,IncompatibleState,ValueError):
                self.hint = None
