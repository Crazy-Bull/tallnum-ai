"""Bind structural contracts to probability-only, real-game connections."""
from copy import deepcopy
from collections import Counter
import argparse
import json
from pathlib import Path
import tempfile


def eligible(item):
    return (item.get('pendingValue') and item.get('disableStaticFallback')
            and item.get('cells', 5) >= 5 and item['target'] >= 24)


def configure_recovery(route, catalog, *, allowed_buffers=None):
    """Index buffers by the anchor they remove, never by their own target."""
    peak = max((s['target'] for s in route['steps']
                if s['kind'] == 'leaf' and s['policyCells'] == 5), default=0)
    anchors = {s['before'][-1][0] for s in route['steps']
               if s['kind'] == 'leaf' and s.get('before')}
    mapping = {}
    for anchor in sorted(anchors):
        choices = [p['id'] for p in catalog['policies']
                   if eligible(p) and p['exit'] == 'buffer'
                   and (p.get('cells', 5) != 5 or p['target'] <= peak)
                   and p['target'] != anchor and p['target'] // 10 == anchor // 10
                   and p.get('maxValue', 0) >= 48 and p.get('maxGoalCells', 5) <= 4
                   and (allowed_buffers is None or p['id'] in allowed_buffers)]
        if choices:
            mapping[str(anchor)] = sorted(choices)
    route.update(bufferRescuePolicies=mapping, singleBoundaryBufferRescue=True,
                 extendedBoundaryBufferRescue=True, realBoundaryRewind=True,
                 entryRecovery=True)
    return route


def expand_spare_workspace(route, catalog, selected, boundary_fits):
    """Solve small equivalent contracts in spare cells; never add a peak call."""
    from .binary_routes import BinaryPlanner, verify_tree
    from .expected_routes import standard
    from .route_search import Block, normalize
    policies = {}
    for p in catalog['policies']:
        key = (p.get('cells', 5), p['target'], p['exit'])
        if key in selected and eligible(p) and p.get('successNoExtraCombos'):
            policies.setdefault(key, []).append(p)
    peak = max((s['target'] for s in route['steps']
                if s['kind'] == 'leaf' and s['policyCells'] == 5), default=0)
    strict_targets = [p['target'] for p in catalog['policies'] if eligible(p)
                      and p.get('cells', 5) >= 6 and p.get('singleTidyExit')
                      and (p['cells'], p['target'], p['exit']) in selected]
    if not strict_targets:
        return route
    floor = max(strict_targets)
    audit = []
    steps = []
    # Scoped caches share the arithmetic subproblems. Full entrance checks
    # remain compulsory for every reuse and every emitted leaf binding.
    with tempfile.TemporaryDirectory(prefix='tallnum-execution-dp-') as work:
        planners = {}
        def replacement(first, goal, expected):
            before = first['before']
            available = route['cells'] - sum(b[1] for b in before)
            if available < 6:
                return None
            cutoff = min(peak, first['target'])
            if cutoff not in planners:
                entries = {}
                for (capacity, target, kind), variants in policies.items():
                    if capacity == 5 and target >= cutoff:
                        continue
                    item = min(variants, key=lambda p: (bool(p.get('singleProtectedValue')), p['id']))
                    entry = {'target': target, 'exit': kind, 'policyId': None,
                             'weightExact': '1' if capacity >= 6 and item.get('singleTidyExit') else '5',
                             'declaredNonstandard': not standard(target), 'structuralOnly': True}
                    if item.get('singleProtectedValue') is not None:
                        minimum = item.get('equivalentProtectedMinimum')
                        if (minimum is not None and minimum >= 10 * (item['maxValue'] // 10 + 1)
                                and item['singleProtectedValue'] >= minimum):
                            entry['equivalentBoundaryMinimum'] = minimum
                        else:
                            entry['allowedBoundaries'] = sorted(p['singleProtectedValue'] for p in variants)
                    if item.get('warmStartOrdinary'):
                        entry['warmStartOrdinary'] = item['warmStartOrdinary']
                    entries[f'{capacity}:{target}:{kind}'] = entry
                    if kind == 'single' and not item.get('warmStartOrdinary'):
                        entries.setdefault(f'{capacity}:{target}:match', {**entry, 'aliasExit': 'single'})
                if not entries:
                    return None
                planner = BinaryPlanner(Path(work)/str(cutoff), {'entries': entries},
                                        maximum=2048, edge_depth=3, node_limit=1200,
                                        minimum_leaf_target=24,
                                        maximum_leaf_target=max(int(k.split(':')[1]) for k in entries),
                                        objective='weight')
                planner.cells = route['cells']; planner.seed_mode = True
                planners[cutoff] = planner
            p = planners[cutoff]
            p.nodes = 0; p.paused = False
            entrance = tuple(Block(b[0], b[1], b[2]) for b in before)
            kind = 'match' if before and before[-1] == [goal, 1, False] else 'single'
            answer = p.solve((kind, available, goal, 3), entrance)
            if answer.get('cost') is None:
                return None
            try:
                trace = verify_tree(p.export(answer), route['cells'], entrance)
            except ValueError:
                return None
            if trace['finalBoard'] != expected or len(trace['steps']) > 8:
                return None
            bound = []
            for s in trace['steps']:
                if s['kind'] == 'leaf':
                    spec = p.snapshot['entries'][s['template']]
                    alias = spec.get('aliasExit') == 'single'
                    key = (s['policyCells'], s['target'], 'single' if alias else s['exit'])
                    choices = [item for item in policies.get(key, [])
                               if boundary_fits(item, s['before'])
                               and item.get('warmStartOrdinary') == s.get('warmStartOrdinary')]
                    if not choices:
                        return None
                    item = min(choices, key=lambda p: p['id'])
                    s['policy'] = item['id']
                    if alias:
                        s.update(exit='single', template=f'{key[0]}:{key[1]}:single',
                                 singleConnectionAfter=deepcopy(s['after']))
                    if s.get('singleConnectionAfter') is not None:
                        s['connection'] = 'ordinary-single-then-real-automatic-equal-merge'
                bound.append(s)
            return bound
        try:
            index = 0
            while index < len(route['steps']):
                s = route['steps'][index]
                count = 1; goal = s.get('target', 0); expected = s['after']; result = None
                if (s['kind'] == 'leaf' and s['policyCells'] == 5 and goal > floor and standard(goal)
                        and s['exit'] in ('single', 'match') and not s.get('warmStartOrdinary')
                        and route['cells'] - sum(b[1] for b in s['before']) >= 6):
                    if s['exit'] == 'single' and index + 1 < len(route['steps']):
                        following = route['steps'][index + 1]
                        combined = [b.json() for b in normalize(tuple(Block(b[0], b[1], b[2])
                                    for b in s['before']) + (Block(2*goal),))]
                        if (following['kind'] == 'leaf' and following.get('target') == goal
                                and following.get('policyCells') == 5
                                and following.get('exit') in ('single', 'match')
                                and following['before'] == s['after']
                                and s['after'] == s['before'] + [[goal, 1, False]]
                                and following['after'] == combined):
                            result = replacement(s, 2*goal, following['after'])
                            if result is not None:
                                count = 2; expected = following['after']
                    if result is None and goal < peak:
                        result = replacement(s, goal, expected)
                    if result is not None:
                        audit.append({'fromStage': index, 'removedStages': count,
                                      'replacementStages': len(result), 'before': s['before'], 'after': expected})
                steps.extend(result if result is not None else [s])
                index += count
        finally:
            for p in planners.values():
                p.close()
    if route.get('releaseAtStage') is not None and audit:
        old = route['releaseAtStage']
        route['releaseAtStage'] = old + sum(a['replacementStages']-a['removedStages']
                                          for a in audit if a['fromStage'] < old)
    route['steps'] = steps
    if audit:
        for change in route.get('executionRebindings', []):
            old = change['stage']
            change['stage'] = old + sum(a['replacementStages']-a['removedStages']
                                       for a in audit if a['fromStage'] < old)
        route['executionExpansions'] = audit
    return route


def improve_execution(route, catalog, selected, boundary_fits, *, opening=True):
    """Keep leaf targets/exits; use spare capacity only with an exact contract."""
    route = deepcopy(route)
    peak = max((s['target'] for s in route['steps']
                if s['kind'] == 'leaf' and s['policyCells'] == 5), default=0)
    changes = []
    for index, step in enumerate(route['steps']):
        if (step['kind'] != 'leaf' or step['policyCells'] != 5
                or step['target'] >= peak or step['exit'] not in ('single', 'match')
                or step.get('warmStartOrdinary')):
            continue
        if step['exit'] == 'match' and (not step['before'] or
                step['before'][-1] != [step['target'], 1, False]):
            continue
        available = route['cells'] - sum(b[1] for b in step['before'])
        variants = [p for p in catalog['policies'] if eligible(p)
                    and (p.get('cells', 5), p['target'], p['exit']) in selected
                    and 6 <= p.get('cells', 5) <= available
                    and p['target'] == step['target'] and p['exit'] == 'single'
                    and p.get('singleTidyExit') and p.get('successNoExtraCombos')
                    and not p.get('warmStartOrdinary') and boundary_fits(p, step['before'])]
        if not variants:
            continue
        item = min(variants, key=lambda p: (p['cells'], p['id']))
        changes.append({'stage': index, 'from': step['policy'], 'to': item['id']})
        if step['exit'] == 'match':
            step.update(singleConnectionAfter=deepcopy(step['after']),
                        connection='ordinary-single-then-real-automatic-equal-merge')
        step.update(exit='single', policy=item['id'], policyCells=item['cells'],
                    template=f"{item['cells']}:{item['target']}:single", availableCells=available)
    route['executionRebindings'] = changes
    route=expand_spare_workspace(route,catalog,selected,boundary_fits)
    # The validated 128/three-40/EDGE opening ends at the same first40
    # contract. Release only protection at stage9; the actual24 stays alive.
    first = route['steps'][0] if route['steps'] else None
    if (opening and route['cells'] == 10 and route['target'] > 128 and first and first['kind'] == 'leaf'
            and first['target'] == 40 and first['exit'] == 'single'
            and first['before'] == [] and first['after'] == [[40, 1, False]]
            and not first.get('warmStartOrdinary')):
        producers = {}
        for target in (32, 40):
            variants = [p for p in catalog['policies'] if eligible(p)
                        and (6, target, 'single') in selected and p.get('cells') == 6
                        and p['target'] == target and p['exit'] == 'single'
                        and p.get('singleTidyExit') and p.get('successNoExtraCombos')
                        and p.get('singleProtectedValue') is None and not p.get('warmStartOrdinary')]
            if variants:
                producers[target] = min(variants, key=lambda p: p['id'])
        if len(producers) == 2:
            b = lambda *values: [[v, 1, False] for v in values]
            prefix = []
            def leaf(target, before, after, match=False):
                s = {'kind': 'leaf', 'target': target, 'exit': 'single', 'policyCells': 6,
                     'template': f'6:{target}:single', 'policy': producers[target]['id'],
                     'before': before, 'after': after}
                if match:
                    s.update(singleConnectionAfter=deepcopy(after),
                             connection='ordinary-single-then-real-automatic-equal-merge')
                prefix.append(s)
            leaf(32, b(), b(32))
            leaf(32, b(32), b(64), True)
            leaf(32, b(64), b(64, 32))
            leaf(32, b(64, 32), b(128), True)
            leaf(40, b(128), b(128, 40))
            leaf(40, b(128, 40), b(128, 80), True)
            leaf(40, b(128, 80), b(128, 80, 40))
            prefix.append({'kind': 'group', 'indices': [1, 2], 'before': b(128, 80, 40),
                           'after': [[128, 1, False], [120, 2, True]]})
            prefix.append({'kind': 'edge', 'before': [[128, 1, False], [120, 2, True]], 'after': b(24)})
            leaf(40, b(), b(40))
            route.update(steps=prefix + route['steps'][1:], releaseAtStage=9,
                         openingSteps=10, browserOpeningContract=True,
                         completionContract=[[route['target'], 1, False]],
                         startupContract='128-three-six40-edge24-six40-probability-only')
            for change in changes:
                change['stage'] += 9
    route['executionContractVersion'] = 2 if route.get('executionExpansions') else 1
    return route


def main():
    """Rebind an existing DP candidate without repeating its arithmetic search."""
    from .common import atomic_json, fingerprint
    from .probability_route_planner import boundary_fits, usable_policies, validate_bound_route
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists() and any(args.out.iterdir()):
        raise ValueError('Use a new output directory to preserve existing results')
    source = json.loads(args.route.read_text(encoding='utf-8'))
    catalog = json.loads(args.catalog.read_text(encoding='utf-8'))
    selected = set(usable_policies(catalog))
    route = improve_execution(source, catalog, selected, boundary_fits)
    configure_recovery(route, catalog)
    validate_bound_route(route, catalog, selected)
    counts = Counter(s['template'] for s in route['steps'] if s['kind'] == 'leaf')
    peak = max((int(k.split(':')[1]) for k in counts if k.startswith('5:')), default=0)
    report = {'status': 'candidate', 'target': route['target'], 'cells': route['cells'],
              'sourceRouteSha256': fingerprint(args.route), 'catalogSha256': fingerprint(args.catalog),
              'executionSourceSha256': fingerprint(__file__),
              'maximumFiveCellTarget': peak,
              'highestFiveCellCalls': sum(v for k, v in counts.items() if k.startswith(f'5:{peak}:')),
              'five64Calls': sum(v for k, v in counts.items() if k.startswith('5:64:')),
              'steps': len(route['steps']), 'leafCounts': dict(counts),
              'idealExitVerified': True, 'randomExecutionVerified': False,
              'lexicographicOrderProvenInScope': False,
              'reason': 'Rebound existing DP arithmetic contracts; real-game tests required'}
    args.out.mkdir(parents=True, exist_ok=True)
    atomic_json(args.out / 'route.json', route)
    atomic_json(args.out / 'planning-report.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
