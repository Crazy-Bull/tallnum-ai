"""Finite template DP. Never enumerates six/seven-cell board states."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import product
import math

from .common import finite_or_none


@dataclass(frozen=True)
class Metrics:
    p: float
    u: float
    v: float

    def __post_init__(self):
        if not all(math.isfinite(x) for x in (self.p, self.u, self.v)):
            raise ValueError('Non-finite absorbing metrics')
        if not 0 <= self.p <= 1 or self.u < 0 or self.v < 0:
            raise ValueError('Invalid absorbing metrics')
        if (self.p == 0 and self.u != 0) or (self.p == 1 and self.v != 0):
            raise ValueError('Impossible conditional cost')

    @property
    def cost(self):
        return self.u + self.v

    @property
    def expected(self):
        return self.cost / self.p if self.p else math.inf

    def then(self, other):
        return Metrics(self.p * other.p,
                       other.p * self.u + self.p * other.u,
                       self.v + (1 - other.p) * self.u + self.p * other.v)

    def json(self):
        return dict(p=self.p, u=self.u, v=self.v,
                    successDrops=self.u / self.p if self.p else None,
                    failureDrops=self.v / (1 - self.p) if self.p < 1 else None,
                    expectedTotalDrops=finite_or_none(self.expected))


def ordinary(n):
    if n <= 0 or (n % 2 and n != 15):
        return False
    while n % 2 == 0:
        n //= 2
    return n in (1, 3, 5, 15)


def leaf_key(target, exit_kind):
    return f'5:{target}:{exit_kind}'


def pareto(routes):
    # Interfaces are already identical within a DP call. Preserve exact ties
    # deterministically, without tolerance-based deletion of better policies.
    result = []
    for route in sorted(routes, key=lambda r: (-r['metrics'].p, r['metrics'].cost, r['id'])):
        m = route['metrics']
        if any(r['metrics'].p >= m.p and r['metrics'].cost <= m.cost for r in result):
            continue
        result = [r for r in result if not (m.p >= r['metrics'].p and m.cost <= r['metrics'].cost)]
        result.append(route)
    return result


class Planner:
    def __init__(self, catalog):
        self.catalog = catalog
        self.missing = {}
        self.triples = {}
        self.unsupported = set()

    def available(self, target, kind):
        return [p for p in self.catalog.get('policies', [])
                if p['target'] == target and p['exit'] == kind
                and p.get('statistics', {}).get('usable', False)]

    def triple(self, target):
        # First two a blocks must collapse to one ordinary 2a. b may be a
        # combination; the extended group merges immediately with lower T.
        candidates = [(a, target - 2*a) for a in range(2, target // 2)
                      if ordinary(a) and ordinary(2*a) and 2 <= target - 2*a <= 65535]
        if not candidates:
            return None
        def key(pair):
            a, b = pair
            missing = int(not self.available(a, 'match')) + int(not self.available(b, 'extend'))
            return abs(a-b), missing, a
        pair = min(candidates, key=key)
        self.triples[str(target)] = {'a': pair[0], 'b': pair[1]}
        return pair

    @lru_cache(None)
    def solve(self, cells, target, exit_kind='single'):
        if target < 2 or target > 65535 or cells not in (5, 6, 7):
            return ()
        # An ordinary exit can only be made from allowed number families.
        if exit_kind == 'single' and not ordinary(target):
            return ()
        if cells == 5 or target < 48:
            variants = self.available(target, exit_kind)
            maximum=max(48,2*target) if target < 48 else target
            if not any(p.get('maxValue',p['target'])==maximum for p in variants):
                key = leaf_key(target, exit_kind)
                self.missing[key] = {'key': key, 'cells': 5, 'target': target, 'exit': exit_kind,
                                     'maxValue': maximum,
                                     'maxGoalCells': {'single': 1, 'match': 5, 'extend': 4}[exit_kind]}
            if target < 48:
                # These approximated leaves exchange their residual blocks.
                # Do not shrink the permitted range in match/extend phases
                # after a single phase with the expanded intermediate bound.
                variants=[p for p in variants if p.get('maxValue',p['target'])==maximum]
            routes = []
            for p in variants:
                s = p['statistics']
                m = Metrics(s['p'], s['u'], s['v'])
                routes.append({'id': p['id'], 'kind': 'leaf', 'cells': cells, 'target': target,
                               'exit': exit_kind, 'policy': p['id'], 'metrics': m,
                               'approximation': cells > 5})
            return tuple(pareto(routes))

        alternatives = []
        pair = self.triple(target) if cells == 6 and exit_kind == 'match' else None
        # Binary produces an ordinary T. If its parent requested a match,
        # normalization immediately also merges T with the parent's lower T.
        if pair is None and target % 2 == 0 and ordinary(target // 2):
            alternatives.append(('binary', [(cells, target//2, 'single'),
                                             (cells-1, target//2, 'match')]))
        if cells == 6 and exit_kind == 'match':
            if pair:
                a, b = pair
                alternatives.append(('ternary', [(6, a, 'single'), (5, a, 'match'), (5, b, 'extend')]))
            # Previously confirmed two-part template; no new unequal split search.
            if target == 240:
                alternatives.append(('extended-pair', [(6, 160, 'single'), (5, 80, 'extend')]))
        routes = []
        for template, specs in alternatives:
            choices = [self.solve(*spec) for spec in specs]
            for children in product(*choices):
                metrics = Metrics(1, 0, 0)
                for child in children:
                    metrics = metrics.then(child['metrics'])
                routes.append({'id': template + '(' + ','.join(c['id'] for c in children) + ')',
                               'kind': template, 'cells': cells, 'target': target, 'exit': exit_kind,
                               'children': list(children), 'metrics': metrics})
        if not alternatives:
            self.unsupported.add((cells, target, exit_kind))
        return tuple(pareto(routes))

    def plan(self, target=768):
        if not isinstance(target, int) or not 2 <= target <= 65535:
            raise ValueError('Target must be an integer in [2, 65535]')
        routes = sorted(self.solve(7, target), key=lambda r: (r['metrics'].expected, r['id']))
        def serialize(route):
            return {k: (v.json() if k == 'metrics' else [serialize(c) for c in v] if k == 'children' else v)
                    for k, v in route.items()}
        return {'version': 1, 'target': target, 'mode': 'standard:7',
                'objective': 'drops-including-whole-game-restarts',
                'approximation': 'independent-uniform-36-entry-policy-statistics',
                'status': 'ready' if routes else 'missing-policies',
                'routes': [serialize(r) for r in routes], 'triples': self.triples,
                'missing': sorted(self.missing.values(), key=lambda p: (p['target'], p['exit'])),
                'unsupported': sorted(self.unsupported), 'globallyOptimal': False}
