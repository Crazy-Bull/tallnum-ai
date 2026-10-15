"""Exact peak/count search in a declared equal-merge/Group construction grammar.

Five-cell leaves are contracts, not deterministic stochastic policy outputs.
This grammar constructs A, then up to five ordinary components summing to A,
and merges A with their Group. It excludes EDGE and prefix rotations, so its
optimality certificate must not be described as global game optimality.
"""
from collections import Counter
import argparse
import json
from pathlib import Path

BIG = 1_000_000  # Every mass-conserving route here has <=32767 leaves.
INF = 10**30


def standard_targets(maximum):
    result = set()
    for base in (1, 3, 5, 15):
        value = base
        while value <= maximum:
            if value >= 2 and (value % 2 == 0 or value == 15):
                result.add(value)
            value *= 2
    return sorted(result)


def capacity_coefficients(slots):
    """Upper bound within this grammar, irrespective of allowed numeric bases."""
    result = [1] * (slots + 1)
    for s in range(slots - 1, -1, -1):
        result[s] = 2 * sum(result[s+1:min(slots+1, s+6)])
    return result


def solve(target, cells, peak, leaves):
    slots = cells - 5
    if slots < 0:
        raise ValueError('At least five cells required')
    leaves = sorted(set(v for v in leaves if 2 <= v <= peak))
    coefficients = capacity_coefficients(slots)
    costs, parents, partition_splits = {}, {}, {}
    for s in range(slots, -1, -1):
        bound = min(target, coefficients[s] * peak)
        dp = [INF] * (bound + 1)
        parent = {}
        for value in leaves:
            if value <= bound:
                dp[value] = BIG * (value == peak) + 1
                parent[value] = ('leaf', value)
        # Sparse min-plus convolutions of the deeper construction frontiers.
        parts = {0: 0}
        best_parts, best_k, splits = {}, {}, []
        for k in range(1, min(5, slots-s) + 1):
            sub = costs[s+k]
            values = [(v, c) for v, c in enumerate(sub) if c < INF]
            combined, split = {}, {}
            for subtotal, prior in parts.items():
                for value, cost in values:
                    total = subtotal + value
                    if total > bound // 2:
                        break
                    candidate = prior + cost
                    if candidate < combined.get(total, INF):
                        combined[total] = candidate
                        split[total] = value
            parts = combined
            splits.append(split)
            for value, cost in parts.items():
                if cost < best_parts.get(value, INF):
                    best_parts[value], best_k[value] = cost, k
        for value in range(4, bound+1, 2):
            half = value // 2
            candidate = dp[half] + best_parts.get(half, INF)
            if candidate < dp[value]:
                dp[value] = candidate
                parent[value] = ('merge', half, best_k[half])
        costs[s], parents[s], partition_splits[s] = dp, parent, splits
    if target >= len(costs[0]) or costs[0][target] == INF:
        return None

    def tree(value, s):
        op = parents[s][value]
        if op[0] == 'leaf':
            return {'kind': 'leaf', 'target': value, 'reservedPrefixCells': s}
        half, k = op[1:]
        remaining, component_values = half, []
        for index in range(k-1, -1, -1):
            v = partition_splits[s][index][remaining]
            component_values.append(v)
            remaining -= v
        component_values.reverse()
        assert remaining == 0
        return {'kind': 'equal-or-group', 'target': value,
                'first': tree(half, s),
                'components': [tree(v, s+i+1) for i, v in enumerate(component_values)]}

    route = tree(target, 0)
    count = Counter()

    def collect(node):
        if node['kind'] == 'leaf':
            count[node['target']] += 1
        else:
            collect(node['first'])
            for component in node['components']:
                collect(component)

    collect(route)
    return {'target': target, 'cells': cells, 'endgamePeak': max(count),
            'peakCalls': count[max(count)], 'totalCalls': sum(count.values()),
            'targetCounts': dict(sorted(count.items())), 'tree': route,
            'allowedLeafTargets': leaves, 'capacityCoefficients': coefficients,
            'optimalityScope': 'equal-or-Group grammar with five-cell leaf contracts; excludes EDGE and prefix rotations',
            'optimalityInFullGameProven': False, 'leafPoliciesVerified': False}


def search(target, cells=10, family='standard'):
    if not 2 <= target <= 65535 or cells not in (7, 10):
        raise ValueError('Require seven/ten cells and target 2..65535')
    if family not in ('standard', 'all-even'):
        raise ValueError('Unknown leaf family')
    coefficient = capacity_coefficients(cells-5)[0]
    lower = (target + coefficient-1)//coefficient
    allowed = (standard_targets(target) if family == 'standard' else
               sorted(set([*range(2, target+1, 2), *([15] if target >= 15 else [])])))
    rejected = []
    for peak in allowed:
        if peak < lower:
            continue
        result = solve(target, cells, peak, allowed)
        if result:
            result.update(family=family, grammarMinimumPeakProven=True,
                          grammarMinimumPeakCallsProven=True,
                          grammarPeakLowerBound=lower, excludedPeaks=rejected)
            return result
        rejected.append(peak)
    raise ValueError('No construction in this grammar')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=int)
    parser.add_argument('--cells', type=int, choices=(7, 10), default=10)
    parser.add_argument('--family', choices=('standard', 'all-even'), default='standard')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 2 <= args.target <= 65535:
        parser.error('Target must be 2..65535')
    result = search(args.target, args.cells, args.family)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k != 'tree'}, indent=2))
