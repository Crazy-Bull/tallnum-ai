"""Fast, bounded top-down discovery of low-tier contract candidates.

This supplements exhaustive cost-bound search, never proves minimality. It
includes equal halves and nearby complements followed by an extend contract,
so intermediate odd bases need not force a large five-cell single goal.
Every returned operation comes from RouteSearch.successors().
"""
from fractions import Fraction

from .route_search import Block, difficulty_profile, identity, normalize, ordinary_possible


class CandidateDiscovery:
    def __init__(self, search, node_limit=2000):
        self.search = search
        self.node_limit = node_limit
        self.nodes = 0
        self.truncated = False
        self.memory = {}
        self.actions = {}
        self.namespace = 'complement-discovery-2-explicit-' + search.namespace

    def _action(self, board, target, kind):
        key = (board, target, kind)
        if key not in self.actions:
            found = next(((op, after, cost) for op, after, cost in self.search.successors(board)
                          if op['kind']=='leaf' and op['target']==target and op['exit']==kind), None)
            self.actions[key] = found
        found = self.actions[key]
        if found is None:
            return None
        op, after, cost = found
        return {'steps': [{**op, 'before': [b.json() for b in board],
                           'after': [b.json() for b in after]}], 'units': str(cost)}, after

    @staticmethod
    def _join(*paths):
        return {'steps': [s for p in paths for s in p['steps']],
                'units': str(sum((Fraction(p['units']) for p in paths), Fraction(0)))}

    def _keep(self, paths):
        unique = {identity(p['steps']): p for p in paths}
        ranked = sorted(unique.values(), key=lambda p: (difficulty_profile(p), Fraction(p['units']), identity(p['steps'])))
        keep = ranked[:3]
        if ranked:
            cheap = min(ranked, key=lambda p: (Fraction(p['units']), identity(p['steps'])))
            if cheap not in keep:
                keep[-1] = cheap
        return keep

    def _complements(self, half):
        # These are search priorities, not a restriction on allowed odd bases.
        # The exhaustive search still considers its entire declared domain.
        values = {half//2}
        # With one protected slot already occupied, building B usually needs
        # a B/2 leaf and the final extend costs half-B. Balancing these two
        # high stages suggests B close to 2*half/3, not only powers of two.
        # Round to multiples of four so B/2 remains an ordinary even block.
        balanced = (2*half//3)//4*4
        values.update(balanced+offset for offset in (-8,-4,0,4,8))
        power = 2
        while power < half:
            values.update((power, half-power))
            power *= 2
        return sorted(v for v in values if 2 <= v < half and ordinary_possible(v)
                      and (half-v)%2==0)

    def build(self, board, target):
        if not ordinary_possible(target) or target > self.search.maximum:
            return []
        expected = normalize((*board, Block(target)))
        if any(b.value > self.search.maximum for b in expected):
            return []
        key = identity({'board': [b.json() for b in board], 'append': target})
        if key in self.memory:
            return self.memory[key]
        cached = self.search.store.get(self.namespace, key)
        if cached is not None:
            self.memory[key] = cached
            return cached
        if self.nodes >= self.node_limit:
            self.truncated = True
            # Keep the direct contract as an unexpanded fallback. Otherwise
            # exhausting a deep first subtree would erase all later root
            # candidates, even an immediately available legal leaf.
            kind = 'match' if board and board[-1].value==target else 'single'
            direct = self._action(board, target, kind)
            return [direct[0]] if direct is not None and direct[1]==expected else []
        self.nodes += 1
        if self.search.cells-sum(b.span for b in board) < 5:
            self.memory[key] = []
            self.search.store.put(self.namespace, key, [])
            return []
        paths = []
        kind = 'match' if board and board[-1].value==target else 'single'
        direct = self._action(board, target, kind)
        if direct is not None and direct[1]==expected:
            paths.append(direct[0])
        from .planner import ordinary
        if not ordinary(target):
            from .route_synthesis import synthesize
            explicit,count,truncated=synthesize(self.search,board,target,max(0,self.node_limit-self.nodes))
            self.nodes+=count;self.truncated=self.truncated or truncated
            paths.extend(explicit)
        half = target//2
        if target%2==0 and ordinary_possible(half):
            # All final boards of build(board, value) are fixed by its append
            # contract. Thus only prefixes, not a Cartesian route expansion,
            # have to be recursively searched for each complement.
            first = self.build(board, half)
            middle = normalize((*board, Block(half)))
            if first:
                second = self.build(middle, half)
                paths.extend(self._join(a,b) for a in first for b in second)
                for value in self._complements(half):
                    second = self.build(middle, value)
                    before = normalize((*middle, Block(value)))
                    last = self._action(before, half-value, 'extend') if second else None
                    if last is not None and last[1]==expected:
                        paths.extend(self._join(a,b,last[0]) for a in first for b in second)
        result = self._keep(paths)
        self.memory[key] = result
        # An incomplete enumeration is useful locally but cannot be recorded
        # as complete and reused after a resource pause.
        if not self.truncated:
            self.search.store.put(self.namespace, key, result)
        return result

    def discover(self):
        initial=self.search.initial
        if not initial:
            paths=self.build(initial,self.search.target)
        elif initial == (Block(self.search.target//2),) and self.search.target%2==0:
            paths=self.build(initial,self.search.target//2)
        else:
            paths=[]  # General prefixes are handled by the exhaustive graph search.
        return paths, {'method': 'bounded-memoized-halves-and-complements',
                       'nodesThisRun': self.nodes, 'truncated': self.truncated,
                       'optimalityProven': False}
