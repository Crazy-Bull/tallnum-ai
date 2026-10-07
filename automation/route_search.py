"""Version 2: persistent, cost-bounded memoized search of stage contracts.

Boards here describe the protected prefix, not an invented deterministic exit
board of a random policy. The active residual region is explicitly unknown.
Contracts are checked against the full board by RouteExecutor in simulation.
Minimality is only a statement about this structural graph, never the game.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3

from .common import atomic_json, event
from .planner import Metrics, pareto, ordinary

VERSION = 'weighted-contract-search-4-explicit-buffers'
SCALE = 48 ** 3
DEFAULT_ALPHAS = (0, .001, .005, .01, .05)


def template_alphas(target, requested=None):
    """Small five-cell goals use only the unpenalized objective."""
    return [0] if target < 48 else list(DEFAULT_ALPHAS if requested is None else requested)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(value):
    return sha256(encoded(value).encode()).hexdigest()


def ordinary_possible(value):
    # Rule-level necessary condition, NOT a reachability assertion.
    return value == 15 or value >= 2 and value % 2 == 0


def template_key(target, kind):
    return f'5:{target}:{kind}'


def difficulty_profile(path):
    """Compare highest stages first; any number of lower stages comes later.

    This is a conservative candidate preference, not a failure probability or
    a replacement for the separate proof of minimum cubic structural cost.
    """
    return tuple(sorted((s['target'] for s in path['steps'] if s['kind']=='leaf'), reverse=True))


def metrics_json(metrics):
    return {**metrics.json(), 'c': metrics.cost}


def representatives(routes, limit=20):
    front = pareto(routes)
    if len(front) <= limit:
        return front
    selected = []
    for key in (lambda r: (-r['metrics'].p, r['id']),
                lambda r: (r['metrics'].cost, r['id']),
                lambda r: (r['metrics'].expected, r['id'])):
        item = min(front, key=key)
        if item not in selected:
            selected.append(item)
    while len(selected) < limit:
        remaining = [r for r in front if r not in selected]
        selected.append(min(remaining, key=lambda r: (
            -min(abs(r['metrics'].p - s['metrics'].p) for s in selected),
            r['metrics'].expected, r['id'])))
    return sorted(selected, key=lambda r: (r['metrics'].p, r['id']))


class Weights:
    def __init__(self, overrides=None):
        if overrides is not None and not isinstance(overrides, dict):
            raise ValueError('Weight overrides must be a JSON object')
        self.overrides = overrides or {}
        for key, value in self.overrides.items():
            if not isinstance(key, str) or isinstance(value, bool):
                raise ValueError('Weight overrides map template keys to positive numbers')
            fields = key.split(':')
            if (len(fields) != 3 or fields[0] != '5' or not fields[1].isdigit()
                    or not 2 <= int(fields[1]) <= 65535 or fields[2] not in ('single', 'match', 'extend', 'buffer')):
                raise ValueError('Weight keys must be 5:target:single|match|extend|buffer')
            weight = Fraction(str(value))
            if weight <= 0:
                raise ValueError('Weights must be strictly positive')

    def units(self, target, kind):
        value = self.overrides.get(template_key(target, kind))
        return Fraction(target ** 3) if value is None else Fraction(str(value)) * SCALE


@dataclass(frozen=True)
class Block:
    value: int
    span: int = 1
    group: bool = False
    buffer: bool = False

    def json(self):
        result=[self.value, self.span, self.group]
        return [*result,True] if self.buffer else result


def normalize(board):
    board = list(board)
    while True:
        pair = next((i for i in range(len(board)-2, -1, -1)
                     if board[i].value == board[i+1].value), None)
        if pair is None:
            return tuple(board)
        board[pair:pair+2] = [Block(board[pair].value * 2)]


def edge_board(board):
    board = list(board)
    def eligible(i):
        return board[i].value // 10 > 0 and board[i].value // 10 == board[i+1].value // 10
    while any(eligible(i) for i in range(len(board)-1)):
        i = len(board)-2
        while i >= 0:
            if eligible(i):
                board[i:i+2] = [Block((board[i].value // 10) * 2)]
                i -= 1
            i -= 1
    return normalize(board)


class SearchStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS memo (namespace TEXT, key TEXT, value TEXT, PRIMARY KEY(namespace,key))')
        self.db.execute('CREATE TABLE IF NOT EXISTS dependencies (parent TEXT, child TEXT, PRIMARY KEY(parent,child))')
        self.hits = 0

    def get(self, namespace, key):
        row = self.db.execute('SELECT value FROM memo WHERE namespace=? AND key=?', (namespace, key)).fetchone()
        if row:
            self.hits += 1
            return json.loads(row[0])

    def put(self, namespace, key, value):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO memo VALUES (?,?,?)', (namespace, key, encoded(value)))

    def depends(self, parent, child):
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO dependencies VALUES (?,?)', (parent, child))

    def close(self):
        self.db.close()


class SearchPaused(Exception):
    pass


class RouteSearch:
    def __init__(self, directory, catalog, *, target, cells=7, max_value=None,
                 weights=None, candidate_limit=20, node_limit=0, leaf_targets=None,
                 progress=True, local_template_bounds=False, max_leaf_target=None,
                 initial_prefix=None, template_bound_overrides=None):
        if cells not in (6, 7, 10) or type(target) is not int or not 2 <= target <= 65535:
            raise ValueError('Require 6/7/10 cells and integer target in [2,65535]')
        maximum = min(65535, max(48, 2*target)) if max_value is None else max_value
        if type(maximum) is not int or not target <= maximum <= 65535:
            raise ValueError('Maximum intermediate value must be in [target,65535]')
        if type(candidate_limit) is not int or not 3 <= candidate_limit <= 20 or type(node_limit) is not int or node_limit < 0:
            raise ValueError('Candidate limit must be 3..20; node limit must be nonnegative')
        self.directory = Path(directory)
        self.initial = tuple(Block(*b) for b in (initial_prefix or []))
        if (any(b.group or b.span != 1 or not ordinary_possible(b.value) or b.value > maximum for b in self.initial)
                or sum(b.span for b in self.initial) > cells-5):
            raise ValueError('Initial prefix must leave five working cells')
        self.local_template_bounds=local_template_bounds
        self.max_leaf_target=max_leaf_target or maximum
        self.template_bound_overrides=template_bound_overrides or {}
        if not 2 <= self.max_leaf_target <= maximum:
            raise ValueError('Leaf target cap must fit the structural maximum')
        self.directory.mkdir(parents=True, exist_ok=True)
        self.catalog, self.cells, self.target, self.maximum = catalog, cells, target, maximum
        self.weights, self.limit = Weights(weights), candidate_limit
        self.node_limit, self.nodes = node_limit, 0
        self.progress = progress
        self.targets = sorted(set(leaf_targets if leaf_targets is not None else
                                  [*range(2, maximum+1, 2), *([15] if maximum >= 15 else [])]))
        if any(type(t) is not int or not 2 <= t <= maximum or not ordinary_possible(t) for t in self.targets):
            raise ValueError('Leaf single targets must satisfy ordinary number rules and maximum')
        self.config = {'algorithm': VERSION, 'cells': cells, 'maxValue': maximum,
                       'weights': self.weights.overrides, 'limit': candidate_limit,
                       'candidateRanking': 'descending-endgame-targets-then-cubic-cost',
                       'leafTargets': self.targets, 'rules': self.rules_fingerprint(),
                       'initialPrefix': [b.json() for b in self.initial],
                       'localTemplateBounds': local_template_bounds,
                       'maxLeafTarget': self.max_leaf_target,
                       'templateBoundOverrides': self.template_bound_overrides,
                       'nonstandardConstruction':'explicit-standard-single-buffer-edge-v1',
                       'bufferContract':'adjacent-ordinary-or-group-up-to-four-cells-v1',
                       'residualContract': 'unknown-active-region-retained-and-checked-v1'}
        self.namespace = identity(self.config)
        self.requirements = {}
        # Every leaf adds exactly its target to the protected sum. Group and
        # normal merges conserve it, EDGE decreases it. This relaxation is an
        # admissible bound and avoids starting a large target at budget zero.
        self.minimum_cost_per_value = Fraction(4)
        for key in self.weights.overrides:
            target, kind = key.split(':')[1:]
            self.minimum_cost_per_value = min(self.minimum_cost_per_value,
                                              self.weights.units(int(target), kind)/int(target))
        self.store = SearchStore(self.directory/'routes.sqlite3')

    @staticmethod
    def rules_fingerprint():
        root = Path(__file__).parent
        return identity({name: sha256((root/name).read_bytes()).hexdigest()
                         for name in ('game.py', 'route_search.py', 'route_discovery.py', 'route_synthesis.py', 'vendor/tallnum.mjs')})

    def close(self):
        self.store.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def lower_bound(self, board):
        return max(0, self.target-sum(b.value for b in board))*self.minimum_cost_per_value

    def requirement(self, target, kind):
        if kind in ('single','match') and not ordinary(target):
            raise ValueError('Nonstandard ordinary goals require explicit single/buffer/EDGE construction')
        key = template_key(target, kind)
        maximum=self.maximum
        bases=list(range(1,maximum+1,2))
        if self.local_template_bounds:
            maximum=max(48,2*target) if target < 48 else target
            maximum=self.template_bound_overrides.get(key,maximum)
            if not target <= maximum <= self.maximum:
                raise ValueError('Template bound must fit the structural maximum')
            bases=[1,3,5,15]
        if kind=='buffer':bases=[1,3,5,15]
        result = {'key': key, 'cells': 5, 'target': target, 'exit': kind,
                  'maxValue': maximum, 'maxGoalCells': {'single': 1, 'match': 5, 'extend': 4,'buffer':4}[kind],
                  'bases': bases, 'aggressiveness': template_alphas(target)}
        self.requirements[key] = result
        return result

    def successors(self, board):
        """Finite macro graph. Every free transition strictly reduces block count.

        A leaf has an unknown residual region and a protected-prefix contract.
        No rotations of that prefix are assumed free (real rotations drop).
        """
        used = sum(b.span for b in board)
        if any(b.buffer for b in board):
            after=edge_board(board)
            if after!=board and all(b.value<=self.maximum for b in after):
                yield {'kind':'edge'},after,Fraction(0)
            return
        if self.cells-used >= 5:
            # Ordinary single exits are appended. Equal boundary exits use
            # match statistics, which also allow a group immediately to merge.
            for target in self.targets:
                if target > self.max_leaf_target or not ordinary(target):
                    continue
                if any(b.group for b in board):
                    # A policy may need Group internally. Only an immediate
                    # match is admitted with an existing protected Group.
                    if not board or board[-1].value != target:
                        continue
                kind = 'match' if board and board[-1].value == target else 'single'
                after = normalize((*board, Block(target)))
                if any(b.value > self.maximum for b in after):
                    continue
                yield {'kind': 'leaf', 'target': target, 'exit': kind,
                       'template': template_key(target, kind)}, after, self.weights.units(target, kind)
            if board and not any(b.group for b in board):
                anchor=board[-1].value
                # A nonstandard equal boundary is matched by constructing a
                # Group buffer, never by pretending to synthesize a new tile.
                goals=([anchor] if not ordinary(anchor) else [])
                if anchor>=10:
                    goals+=list(range((anchor//10)*10,(anchor//10)*10+10))
                for target in sorted(set(goals)):
                    if not 2<=target<=min(self.max_leaf_target,self.maximum):continue
                    if target==anchor and ordinary(anchor):continue
                    after=normalize((*board,Block(target,4,True,True)))
                    if sum(b.span for b in after)>=self.cells or any(b.value>self.maximum for b in after):continue
                    yield {'kind':'leaf','target':target,'exit':'buffer','template':template_key(target,'buffer'),
                           'purpose':'equal-buffer' if target==anchor else 'edge-buffer'},after,self.weights.units(target,'buffer')
            if len(board) >= 2 and not any(b.group for b in board):
                target = board[-2].value-board[-1].value
                if 2 <= target <= self.max_leaf_target and ordinary_possible(target):
                    after = normalize((*board[:-2], Block(2*board[-2].value)))
                    if all(b.value <= self.maximum for b in after):
                        yield {'kind': 'leaf', 'target': target, 'exit': 'extend',
                               'template': template_key(target, 'extend')}, after, self.weights.units(target, 'extend')
        if not any(b.group for b in board):
            for start in range(len(board)):
                for end in range(start+2, min(len(board), start+5)+1):
                    value = sum(b.value for b in board[start:end])
                    if value <= self.maximum:
                        after = normalize((*board[:start], Block(value, end-start, True), *board[end:]))
                        if all(b.value <= self.maximum for b in after):
                            yield {'kind': 'group', 'indices': list(range(start, end))}, after, Fraction(0)
        after = edge_board(board)
        if after != board and all(b.value <= self.maximum for b in after):
            yield {'kind': 'edge'}, after, Fraction(0)

    def _structures(self, paths):
        unique = {}
        for p in paths:
            key=identity(p['steps'])
            previous=unique.get(key,{})
            unique[key]={**p}
            if p.get('baseline') or previous.get('baseline'):unique[key]['baseline']=True
        ranked = sorted(unique.values(), key=lambda p: (difficulty_profile(p), Fraction(p['units']), identity(p['steps'])))
        chosen, counts = [], set()
        for p in ranked:
            key = encoded(Counter(s['template'] for s in p['steps'] if s['kind']=='leaf'))
            if key not in counts:
                chosen.append(p)
                counts.add(key)
                if len(chosen) == self.limit:
                    break
        for p in ranked:
            if len(chosen) >= self.limit:
                break
            if p not in chosen:
                chosen.append(p)
                if len(chosen) == self.limit:
                    break
        # Preserve the cubic-cost endpoint at EVERY memo state: conservative
        # candidate pruning must not invalidate the independent cost proof.
        if ranked:
            cheapest = min(ranked, key=lambda p: (Fraction(p['units']), identity(p['steps'])))
            if cheapest not in chosen:
                chosen[-1] = cheapest
            baseline=next((p for p in ranked if p.get('baseline')),None)
            if baseline is not None and not any(p.get('baseline') for p in chosen):
                chosen[-2 if len(chosen)>1 else -1]=baseline
        return sorted(chosen, key=lambda p: (difficulty_profile(p), Fraction(p['units']), identity(p['steps'])))

    def _state_key(self, board, budget):
        state = {'board': [b.json() for b in board], 'target': self.target,
                 'budget': str(budget), 'fixed': 'entire-prefix', 'residual': 'unknown'}
        return identity(state)

    def _open_frame(self, board, budget):
        key = self._state_key(board, budget)
        cached = self.store.get(self.namespace, key)
        if cached and cached['complete']:
            return None, cached
        if self.node_limit and self.nodes >= self.node_limit:
            raise SearchPaused()
        self.nodes += 1
        if self.nodes % 1000 == 0:
            update = {'nodes': self.nodes, 'cacheHits': self.store.hits,
                      'target': self.target, 'cells': self.cells}
            if callable(self.progress):
                self.progress(update)
            elif self.progress:
                event('route-search-progress', **update)
        if any(not b.group and b.value == self.target for b in board):
            answer = {'complete': True, 'paths': [{'steps': [], 'units': '0'}], 'next': None}
            self.store.put(self.namespace, key, answer)
            return None, answer
        partial = cached or {'complete': False, 'cursor': 0, 'paths': [], 'next': None}
        return {'key': key, 'board': board, 'budget': budget, 'cursor': partial['cursor'],
                'choices': enumerate(self.successors(board)), 'pending': None,
                'paths': partial['paths'],
                'over': Fraction(partial['next']) if partial['next'] is not None else None}, None

    @staticmethod
    def _raise_bound(frame, next_bound):
        if next_bound is not None and (frame['over'] is None or next_bound < frame['over']):
            frame['over'] = next_bound

    def _include_child(self, frame, op, after, cost, child):
        for route in child['paths']:
            step = {**op, 'before': [b.json() for b in frame['board']], 'after': [b.json() for b in after]}
            frame['paths'].append({'steps': [step, *route['steps']], 'units': str(cost+Fraction(route['units']))})
        frame['paths'] = self._structures(frame['paths'])
        if child['next'] is not None:
            self._raise_bound(frame, cost+Fraction(child['next']))

    def _visit(self, board, budget):
        # Explicit DFS frames implement the same top-down memoized search.
        # Large/custom goals can need thousands of cheap leaves: a Python
        # recursion limit must never turn a valid query into an exception.
        stack = []
        try:
            root, answer = self._open_frame(board, budget)
            if answer is not None:
                return answer
            stack.append(root)
            while stack:
                frame = stack[-1]
                try:
                    index, (op, after, cost) = next(frame['choices'])
                except StopIteration:
                    answer = {'complete': True, 'paths': frame['paths'],
                              'next': str(frame['over']) if frame['over'] is not None else None}
                    self.store.put(self.namespace, frame['key'], answer)
                    stack.pop()
                    if not stack:
                        return answer
                    parent = stack[-1]
                    op, after, cost = parent['pending']
                    self._include_child(parent, op, after, cost, answer)
                    parent['pending'] = None
                    parent['cursor'] += 1
                    continue
                if index < frame['cursor']:
                    continue
                frame['cursor'] = index
                estimate = cost+self.lower_bound(after)
                if estimate > frame['budget']:
                    self._raise_bound(frame, estimate)
                    frame['cursor'] = index+1
                    continue
                frame['pending'] = op, after, cost
                child, answer = self._open_frame(after, frame['budget']-cost)
                if answer is None:
                    stack.append(child)
                else:
                    self._include_child(frame, op, after, cost, answer)
                    frame['pending'] = None
                    frame['cursor'] = index+1
        except (SearchPaused, KeyboardInterrupt):
            for frame in reversed(stack):
                self.store.put(self.namespace, frame['key'], {'complete': False, 'cursor': frame['cursor'],
                               'paths': frame['paths'], 'next': str(frame['over']) if frame['over'] is not None else None})
            raise

    def available(self, requirement):
        return [p for p in self.catalog.get('policies', [])
                if p['target'] == requirement['target'] and p['exit'] == requirement['exit']
                and p.get('maxValue', p['target']) == requirement['maxValue']
                and p.get('bases') == requirement['bases']
                and p.get('maxGoalCells') == requirement['maxGoalCells']
                and float(p.get('variantAggressiveness', p.get('aggressiveness', 0))) in template_alphas(requirement['target'], requirement.get('aggressiveness'))
                and p.get('statistics', {}).get('usable')
                and p.get('statistics', {}).get('p', 0) > 0
                and p.get('petsc', {}).get('verified') and p.get('exitSemantics') in ('success-board-v2','success-board-clean-v3')
                and p.get('petsc', {}).get('exitEvaluationRounds', 0) >= 2]

    def compose(self, structure):
        # Cache actual metrics separately from structural weights. A changed
        # policy invalidates dependent statistics without discarding structure.
        dependency = []
        for step in structure['steps']:
            if step['kind'] == 'leaf':
                req = self.requirement(step['target'], step['exit'])
                dependency.extend(self.available(req))
        key = identity({'steps': structure['steps'], 'policies': dependency, 'limit': self.limit,
                        'target': self.target, 'cells': self.cells, 'rules': self.config['rules'],
                        'weightedUnits': structure['units'],'initialPrefix':[b.json() for b in self.initial],
                        'baseline':bool(structure.get('baseline'))})
        cached = self.store.get('metrics-'+VERSION, key)
        if cached is not None:
            return cached
        routes = [{'id': 'empty', 'steps': [], 'metrics': Metrics(1, 0, 0)}]
        prefix_dependencies = {}
        for index, step in enumerate(structure['steps']):
            if step['kind'] != 'leaf':
                for route in routes:
                    route['steps'].append(step)
                continue
            choices = self.available(self.requirement(step['target'], step['exit']))
            prefix_dependencies.update({p['id']: p for p in choices})
            prefix_key = identity({'steps': structure['steps'][:index+1],
                                   'policies': [prefix_dependencies[k] for k in sorted(prefix_dependencies)],
                                   'cells': self.cells, 'limit': self.limit, 'rules': self.config['rules']})
            prefix = self.store.get('metric-prefix-'+VERSION, prefix_key)
            if prefix is not None:
                routes = [{**r, 'metrics': Metrics(r['metrics']['p'], r['metrics']['u'], r['metrics']['v'])}
                          for r in prefix]
                continue
            expanded = []
            for route in routes:
                for policy in choices:
                    stats = policy['statistics']
                    metrics = route['metrics'].then(Metrics(stats['p'], stats['u'], stats['v']))
                    steps = [*route['steps'], {**step, 'policy': policy['id'], 'cells': 5}]
                    expanded.append({'id': identity(steps), 'steps': steps, 'metrics': metrics})
                    self.store.depends(key, identity(policy))
                    self.store.depends(prefix_key, identity(policy))
            routes = representatives(expanded, self.limit)
            self.store.put('metric-prefix-'+VERSION, prefix_key,
                           [{**r, 'metrics': metrics_json(r['metrics'])} for r in routes])
        result = [{**r, 'id': identity(r['steps']), 'metrics': metrics_json(r['metrics']),
                   'version': 2, 'kind': 'stages', 'target': self.target, 'cells': self.cells,
                   'initialPrefix': [b.json() for b in self.initial],
                   'baseline': bool(structure.get('baseline')),
                   'structuralUnits': structure['units'], 'weightedDifficulty': float(Fraction(structure['units'])/SCALE),
                   'leafCounts': dict(Counter(s['template'] for s in structure['steps'] if s['kind']=='leaf'))}
                  for r in routes]
        self.store.put('metrics-'+VERSION, key, result)
        return result

    def plan(self, *, write_result=True):
        run_key = identity({'target': self.target, 'namespace': self.namespace})
        run = self.store.get('runs', run_key) or {'bound': str(self.lower_bound(self.initial)), 'structures': [], 'minimum': None, 'complete': False}
        if self.local_template_bounds:
            from .route_baseline import legacy_structure
            baseline=legacy_structure(self)
            if baseline and not any(p.get('baseline') for p in run['structures']):
                run['structures'].append(baseline)
        status = 'searching'
        if not ordinary_possible(self.target):
            run.update(complete=True, reason='ordinary-odd-target-excluded-by-rules')
        if not run['complete'] and (not run.get('discovery') or run['discovery']['truncated']):
            from .route_discovery import CandidateDiscovery
            discovery = CandidateDiscovery(self, min(self.node_limit or 2000, 2000))
            seeds, run['discovery'] = discovery.discover()
            self.nodes += discovery.nodes
            run['structures'] = self._structures(run['structures']+seeds)
            self.store.put('runs', run_key, run)
        try:
            while not run['complete']:
                bound = Fraction(run['bound'])
                answer = self._visit(self.initial, bound)
                if answer['paths'] and run['minimum'] is None:
                    run['minimum'] = str(min(Fraction(p['units']) for p in answer['paths']))
                run['structures'] = self._structures(run['structures']+answer['paths'])
                # Minimum proof precedes any candidate stopping. Continuing
                # after this scope is a configurable new search, not a claim
                # that every more expensive structure was evaluated.
                if answer['next'] is None or (run['minimum'] is not None and len(run['structures']) >= self.limit):
                    run['complete'] = True
                    run['exhausted'] = answer['next'] is None
                else:
                    run['bound'] = answer['next']
                self.store.put('runs', run_key, run)
        except (SearchPaused, KeyboardInterrupt):
            status = 'paused'
            root_key = self._state_key(self.initial, Fraction(run['bound']))
            partial = self.store.get(self.namespace, root_key)
            if partial:
                run['structures'] = self._structures(run['structures']+partial['paths'])
            self.store.put('runs', run_key, run)
        routes = []
        for structure in run['structures']:
            for step in structure['steps']:
                if step['kind'] == 'leaf':
                    self.requirement(step['target'], step['exit'])
            routes.extend(self.compose(structure))
        modeled = [{**r, 'metrics': Metrics(r['metrics']['p'], r['metrics']['u'], r['metrics']['v'])} for r in routes]
        selected=representatives(modeled,self.limit)
        baseline=next((r for r in sorted(modeled,key=lambda r:r['metrics'].expected) if r.get('baseline')),None)
        if baseline is not None and not any(r.get('baseline') for r in selected):
            selected=selected[:self.limit-1]+[baseline]
        routes = [{**r, 'metrics': metrics_json(r['metrics'])} for r in selected]
        routes.sort(key=lambda r: (r['metrics']['expectedTotalDrops'] if r['metrics']['expectedTotalDrops'] is not None else math.inf, r['id']))
        missing = [r for r in self.requirements.values() if not self.available(r)]
        if status != 'paused':
            status = 'ready-for-simulation' if routes else 'missing-policies' if missing else 'no-route-in-scope'
        structures = [{**s, 'weightedDifficulty': float(Fraction(s['units'])/SCALE),
                       'highestEndgameTarget': max((x['target'] for x in s['steps'] if x['kind']=='leaf'), default=0),
                       'difficultyProfile': list(difficulty_profile(s)),
                       'leafCount': sum(x['kind']=='leaf' for x in s['steps']),
                       'leafCounts': dict(Counter(x['template'] for x in s['steps'] if x['kind']=='leaf'))}
                      for s in run['structures']]
        result = {'version': 2, 'planner': VERSION, 'target': self.target, 'cells': self.cells,
                  'config': self.config, 'status': status, 'routes': routes, 'structures': structures,
                  'missing': missing, 'requirements': list(self.requirements.values()),
                  'search': {**{k:v for k,v in run.items() if k!='structures'}, 'nodesThisRun': self.nodes,
                             'cacheHits': self.store.hits},
                  'minimumStructuralUnits': run['minimum'], 'globallyOptimal': False,
                  'lowestKnownStructuralUnits': str(min((Fraction(s['units']) for s in run['structures']), default=Fraction(0))) if run['structures'] else None,
                  'candidateRankingProvenOptimal': False,
                  'structuralMinimumProven': run['minimum'] is not None,
                  'structuralMinimumScope': 'optimistic protected-prefix contract graph, NOT policy reachability',
                  'executableMinimumProven': False,
                  'approximation': 'unknown residual contracts; independent five-cell entry moments; 20-point heuristic',
                  'objective': 'drops-including-whole-game-restarts'}
        if write_result:
            atomic_json(self.directory/'route-plan.json', result)
        return result
