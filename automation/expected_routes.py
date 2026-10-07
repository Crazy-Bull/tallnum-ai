"""One measured variant per standard five-cell contract; additive cost search.

Weights are (u+v)/p, not cubic difficulty or maximum target. The sum assumes
local independent retries and is NOT whole-game restart cost. Structural
search retains unknown residual contracts and does not certify execution.
"""
from collections import Counter
from fractions import Fraction
import argparse
import heapq
import json
import math
from pathlib import Path
import sqlite3

from .common import atomic_json, fingerprint
from .route_search import Block, RouteSearch, encoded, identity, template_key

VERSION = 'measured-additive-contract-search-1'
RULES = {'edge-recheck-v1', '91de4bf6f03efea924c3e277971227881760244572ef74d162d3df6098dcb06d'}


def standard(value):
    if type(value) is not int or value < 2 or value % 2 and value != 15:
        return False
    while value % 2 == 0:
        value //= 2
    return value in (1, 3, 5, 15)


def weight(stats):
    p, u, v = (stats.get(k) for k in ('p', 'u', 'v'))
    if (not stats.get('usable') or any(type(x) not in (int, float) or not math.isfinite(x)
                                     for x in (p, u, v))
            or not 0 < p <= 1 or u < 0 or v < 0
            or stats.get('nonterminationProbability', 0) != 0):
        raise ValueError('Weight requires usable finite p,u,v without nontermination')
    result = (Fraction(str(u)) + Fraction(str(v))) / Fraction(str(p))
    if result <= 0:
        raise ValueError('Expected drops must be positive')
    return result


def variant_alpha(policy):
    """Separate policy construction risk from its risk-zero evaluation."""
    declared=policy.get('variantAggressiveness')
    result=policy.get('petsc',{}).get('improvementResult')
    if result and Path(result).exists():
        evidence=json.loads(Path(result).read_text(encoding='utf-8'))
        actual=evidence.get('input_aggressiveness',evidence.get('aggressiveness'))
        if actual is not None:
            if declared is not None and float(declared)!=float(actual):
                raise ValueError('Variant aggressiveness disagrees with solver provenance')
            declared=actual
    if declared is None:
        if 'aggressive' in Path(policy.get('source','')).parts:
            raise ValueError('Aggressive policy has no construction-risk provenance')
        declared=policy.get('aggressiveness',0)
    if not math.isfinite(float(declared)) or float(declared)<0:
        raise ValueError('Invalid construction aggressiveness')
    return float(declared)


def build_weights(catalog_files, *, alpha=0, maximum=65535, recalculate=False,
                  measurement_directory=None, progress=None, clean_exit=False):
    if not math.isfinite(alpha) or alpha < 0:
        raise ValueError('Aggressiveness must be nonnegative and finite')
    groups, excluded, sources = {}, [], []
    for file in map(Path, catalog_files):
        sources.append({'path': str(file.resolve()), 'sha256': fingerprint(file)})
        for policy in json.loads(file.read_text(encoding='utf-8')).get('policies', []):
            key = template_key(policy['target'], policy['exit'])
            if not standard(policy['target']) or policy['target'] > maximum:
                continue
            try:
                if policy.get('maxValue', policy['target']) < 48:
                    raise ValueError('Maximum intermediate value must be at least 48')
                actual_alpha=variant_alpha(policy)
                if actual_alpha!=alpha:
                    raise ValueError(f'Construction aggressiveness {actual_alpha} does not match requested {alpha}')
                policy={**policy,'variantAggressiveness':actual_alpha}
                weight(policy.get('statistics', {}))
                uncertified=(policy.get('ruleSha256') not in RULES
                             or policy['exit'] not in ('single','match','extend')
                             or not policy.get('petsc',{}).get('verified')
                             or policy.get('petsc',{}).get('exitEvaluationRounds',0)<2)
                if clean_exit:
                    uncertified |= (policy.get('exitSemantics')!='success-board-clean-v3'
                                    or policy.get('successNoExtraCombos') is not True)
                else:
                    uncertified |= policy.get('exitSemantics') not in ('success-board-v2','success-board-clean-v3')
                if uncertified:
                    raise ValueError('Uncertified exit/statistics')
                if policy.get('bases') is not None and not set(policy['bases']).issubset({1,3,5,15}):
                    raise ValueError('Policy allows nonstandard intermediate bases')
                if fingerprint(policy['policy']) != policy['policySha256']:
                    raise ValueError('Policy file identity mismatch')
                groups.setdefault(key, []).append((policy, file.parent))
            except (ValueError, KeyError, OSError) as error:
                excluded.append({'key': key, 'id': policy.get('id'), 'reason': str(error)})
    entries = {}
    for key, choices in sorted(groups.items()):
        # Choose ONE fixed variant with the exact requested construction risk.
        # Prefer the smallest bound, then least measured cost within that variant.
        policy, directory = min(choices, key=lambda item: (
            abs(float(item[0].get('variantAggressiveness', item[0].get('aggressiveness', 0)))-alpha),
            item[0].get('maxValue', item[0]['target']),
            weight(item[0]['statistics']), item[0]['id']))
        stats = policy['statistics']
        graph = directory/(policy['id']+'.graph.bin')
        graph_hash = None
        if recalculate:
            from .statistics import evaluate_file
            from . import statistics
            if progress:
                progress({'evaluating': key, 'policy': policy['id']})
            graph_hash = fingerprint(graph)
            measurement_key = identity({'graph': graph_hash, 'policy': policy['policySha256'],
                                        'evaluator': fingerprint(statistics.__file__)})
            cache_file = (Path(measurement_directory)/'moments'/(measurement_key+'.json')
                          if measurement_directory is not None else None)
            if cache_file and cache_file.exists():
                stats = json.loads(cache_file.read_text(encoding='utf-8'))['statistics']
            else:
                stats = evaluate_file(graph)
                weight(stats)
                if cache_file:
                    atomic_json(cache_file, {'identity': measurement_key, 'statistics': stats})
        value = weight(stats)
        entries[key] = {'target': policy['target'], 'exit': policy['exit'],
                        'policyId': policy['id'], 'policy': policy['policy'],
                        'policySha256': policy['policySha256'],
                        'alpha': policy.get('variantAggressiveness', policy.get('aggressiveness', 0)),
                        'maxValue': policy.get('maxValue', policy['target']),
                        'bases': policy.get('bases'), 'table': policy.get('table'),
                        'ruleSha256': policy['ruleSha256'],
                        'statistics': stats, 'p': stats['p'], 'c': stats['u']+stats['v'],
                        'weight': float(value), 'weightExact': str(value),
                        'statisticsSource': 'recomputed-fixed-policy-graph' if recalculate else 'certified-catalog-moments',
                        'graph': str(graph.resolve()), 'graphSha256': graph_hash}
    if not entries:
        raise ValueError('No certified usable standard-base five-cell statistics')
    return {'version': VERSION, 'metric': '(u+v)/p', 'requestedAlpha': alpha,
            'entries': entries, 'sources': sources, 'excluded': excluded,
            'approximation': 'sum of independent local retry costs; not whole-game restart expectation',
            'entryModel': 'uniform-first-36, iid-six-original-table; ten-cell unlock/queue distributions not modeled'}


def score_route(route, snapshot):
    steps = route.get('steps', [])
    counts = Counter(template_key(s['target'], s['exit']) for s in steps if s['kind'] == 'leaf')
    missing = sorted(set(counts)-snapshot['entries'].keys())
    subtotal = sum((Fraction(snapshot['entries'][key]['weightExact'])*count
                    for key,count in counts.items() if key in snapshot['entries']), Fraction(0))
    return {'leafCounts': dict(sorted(counts.items())), 'missing': missing,
            'complete': not missing, 'knownSubtotal': float(subtotal),
            'totalWeight': float(subtotal) if not missing else None,
            'totalWeightExact': str(subtotal) if not missing else None,
            'metric': snapshot['metric'], 'wholeGameExpectedDrops': None}


def search(directory, snapshot, *, target, cells=7, node_limit=10000, max_value=None, progress=None):
    if cells not in (7, 10) or type(target) is not int or not 2 <= target <= 65535:
        raise ValueError('Require seven/ten cells and ordinary target 2..65535')
    if type(node_limit) is not int or node_limit < 0:
        raise ValueError('Node limit must be nonnegative; zero is unlimited')
    entries = snapshot['entries']
    if not entries:
        raise ValueError('No measured weights')
    weights = {key: Fraction(entry['weightExact']) for key,entry in entries.items()}
    for key, entry in entries.items():
        if not standard(entry['target']) or weights[key] <= 0 or weights[key] != weight(entry['statistics']):
            raise ValueError('Inconsistent or nonstandard weight entry: '+key)
        if 'policy' in entry and fingerprint(entry['policy']) != entry.get('policySha256'):
            raise ValueError('Selected policy changed; rebuild measured weights: '+key)
    ratio = min(weights[k]/entry['target'] for k,entry in entries.items())
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    maximum = min(65535,max(48,2*target)) if max_value is None else max_value
    model = RouteSearch(directory/'contract-model', {'policies': []}, target=target, cells=cells,
                        max_value=maximum,
                        leaf_targets=sorted(set(e['target'] for e in entries.values() if e['target'] <= maximum)),
                        progress=False)
    config = {'version': VERSION, 'implementation': fingerprint(__file__), 'weights': entries,
              'target': target, 'cells': cells, 'rules': model.config, 'initialPrefix': []}
    run = identity(config)
    db = sqlite3.connect(directory/'expected-search.sqlite3')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS state (run TEXT, board TEXT, cost TEXT, parent TEXT, action TEXT, settled INTEGER, PRIMARY KEY(run,board))')
    db.execute('CREATE TABLE IF NOT EXISTS run (id TEXT PRIMARY KEY, goal TEXT, complete INTEGER)')
    root = encoded([])
    db.execute('INSERT OR IGNORE INTO state VALUES (?,?,?,NULL,NULL,0)', (run,root,'0'))
    db.execute('INSERT OR IGNORE INTO run VALUES (?,NULL,0)', (run,))
    db.commit()

    def decode(key):
        return tuple(Block(*b) for b in json.loads(key))

    def heuristic(board):
        return max(0, target-sum(b.value for b in board))*ratio

    def goal(board):
        return any(not b.group and b.value == target for b in board)

    nodes, complete, goal_key = 0, False, None
    try:
        goal_key, done = db.execute('SELECT goal,complete FROM run WHERE id=?',(run,)).fetchone()
        complete = bool(done)
        heap = [(Fraction(cost)+heuristic(decode(key)), Fraction(cost), key)
                for key,cost in db.execute('SELECT board,cost FROM state WHERE run=? AND settled=0',(run,))]
        heapq.heapify(heap)
        while heap and not complete and (not node_limit or nodes < node_limit):
            _, cost, key = heapq.heappop(heap)
            stored, settled = db.execute('SELECT cost,settled FROM state WHERE run=? AND board=?',(run,key)).fetchone()
            if settled or Fraction(stored) != cost:
                continue
            board = decode(key)
            if goal(board):
                goal_key, complete = key, True
                break
            db.execute('UPDATE state SET settled=1 WHERE run=? AND board=?',(run,key))
            for op, after, ignored in model.successors(board):
                if op['kind'] == 'leaf':
                    if op['template'] not in weights:
                        continue  # Missing costs are UNKNOWN, never zero/cubic.
                    charge = weights[op['template']]
                    op = {**op, 'policy': entries[op['template']]['policyId'],
                          'expectedWeight': float(charge)}
                else:
                    charge = Fraction(0)  # Group/EDGE have no drop in these rules.
                next_cost, next_key = cost+charge, encoded([b.json() for b in after])
                old = db.execute('SELECT cost FROM state WHERE run=? AND board=?',(run,next_key)).fetchone()
                if old is not None and Fraction(old[0]) <= next_cost:
                    continue
                step = {**op, 'before': [b.json() for b in board], 'after': [b.json() for b in after]}
                db.execute('INSERT OR REPLACE INTO state VALUES (?,?,?,?,?,0)',
                           (run,next_key,str(next_cost),key,encoded(step)))
                heapq.heappush(heap,(next_cost+heuristic(after),next_cost,next_key))
                if goal(after) and (goal_key is None or next_cost < Fraction(db.execute(
                        'SELECT cost FROM state WHERE run=? AND board=?',(run,goal_key)).fetchone()[0])):
                    goal_key = next_key
            nodes += 1
            db.execute('UPDATE run SET goal=? WHERE id=?',(goal_key,run))
            db.commit()  # A completed subproblem survives an interrupted run.
            if progress and nodes % 1000 == 0:
                progress({'nodesThisRun': nodes, 'frontier': len(heap)})
        if not heap:
            complete = True
        db.execute('UPDATE run SET goal=?,complete=? WHERE id=?',(goal_key,int(complete),run))
        db.commit()
        steps, cursor = [], goal_key
        while cursor is not None and cursor != root:
            parent, action = db.execute('SELECT parent,action FROM state WHERE run=? AND board=?',(run,cursor)).fetchone()
            steps.append(json.loads(action))
            cursor = parent
        steps.reverse()
        result = {'version': VERSION, 'target': target, 'cells': cells, 'runIdentity': run,
                  'status': ('minimum-in-scope' if goal_key else 'no-route-with-measured-contracts') if complete else 'paused',
                  'steps': steps, 'score': score_route({'steps':steps},snapshot) if goal_key else None,
                  'nodesThisRun': nodes, 'statesStored': db.execute('SELECT COUNT(*) FROM state WHERE run=?',(run,)).fetchone()[0],
                  'minimumAdditiveWeightProvenInScope': complete and goal_key is not None,
                  'globallyOptimal': False, 'executionVerified': False, 'wholeGameExpectedDrops': None,
                  'scope': 'ordered protected-prefix macro graph using ONLY listed measured standard-base single/match/extend contracts, Group and EDGE; active residual unknown',
                  'weightsIdentity': identity(snapshot), 'weights': entries,
                  'approximation': snapshot['approximation']}
        atomic_json(directory/'expected-plan.json',result)
        return result
    finally:
        db.commit()
        db.close()
        model.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('prepare','weights','plan','score'))
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,nargs='+')
    parser.add_argument('--weights',type=Path)
    parser.add_argument('--alpha',type=float,default=0)
    parser.add_argument('--max-target',type=int,default=65535)
    parser.add_argument('--recalculate',action='store_true')
    parser.add_argument('--target',type=int)
    parser.add_argument('--cells',type=int,choices=(7,10),default=7)
    parser.add_argument('--node-limit',type=int,default=10000)
    parser.add_argument('--route',type=Path)
    parser.add_argument('--targets',type=int,nargs='+')
    parser.add_argument('--exits',choices=('single','match','extend'),nargs='+',default=['single','match','extend'])
    parser.add_argument('--rounds',type=int,default=5000)
    args = parser.parse_args()
    args.directory.mkdir(parents=True,exist_ok=True)
    weights_file = args.weights or args.directory/'expected-weights.json'
    report_progress = lambda x: print(json.dumps(x),flush=True)
    if args.command == 'prepare':
        if not args.targets or any(not standard(v) or v > 65535 for v in args.targets):
            parser.error('--targets must contain only standard-base targets in 2..65535')
        if args.alpha != 0:
            parser.error('prepare computes one unpenalized baseline variant (alpha=0)')
        if not 1 <= args.rounds <= 1000000:
            parser.error('--rounds must be 1..1000000')
        from .library import prepare_missing, load_catalog
        from .certify import certify_baselines
        catalog_file = args.directory/'catalog.json'
        existing = load_catalog(args.directory, certified_only=True, clean_only=True,include_shared=True)
        requirements = [{'key': template_key(v,kind), 'cells': 5, 'target': v, 'exit': kind,
                         'maxValue': max(48,2*v) if v < 48 else v, 'maxGoalCells': {'single':1, 'match':5, 'extend':4}[kind],
                         'bases': [1,3,5,15], 'aggressiveness': [0]}
                        for v in sorted(set(args.targets)) for kind in args.exits
                        if not any(p['target']==v and p['exit']==kind and p.get('maxValue',v)==(max(48,2*v) if v < 48 else v)
                                   and p.get('variantAggressiveness',p.get('aggressiveness',0)) == 0
                                   for p in existing['policies'])]
        prepare_missing(args.directory,requirements,args.rounds)
        certify_baselines(args.directory)
        catalogs = [*(args.catalog or []),catalog_file]
        from .library import SHARED_CLEAN_LIBRARY
        shared=SHARED_CLEAN_LIBRARY/'catalog.json'
        if shared.exists() and shared.resolve() not in [Path(x).resolve() for x in catalogs]:
            catalogs.append(shared)
        result = build_weights(catalogs,alpha=0,maximum=args.max_target,clean_exit=True,
                               recalculate=args.recalculate,measurement_directory=args.directory,
                               progress=report_progress)
        required_keys = {template_key(v,kind) for v in args.targets for kind in args.exits}
        missing = sorted(required_keys-result['entries'].keys())
        atomic_json(weights_file,result)
        if missing:
            raise RuntimeError('Requested contracts remain without finite certified statistics: '+', '.join(missing))
        print(json.dumps({key:entry['weight'] for key,entry in result['entries'].items()},indent=2))
    elif args.command == 'weights':
        if not args.catalog:
            parser.error('--catalog is required')
        catalogs=list(args.catalog)
        from .library import SHARED_CLEAN_LIBRARY
        shared=SHARED_CLEAN_LIBRARY/'catalog.json'
        if shared.exists() and shared.resolve() not in [Path(x).resolve() for x in catalogs]:catalogs.append(shared)
        result = build_weights(catalogs,alpha=args.alpha,maximum=args.max_target,clean_exit=True,
                               recalculate=args.recalculate,measurement_directory=args.directory,
                               progress=report_progress)
        atomic_json(weights_file,result)
        print(json.dumps({key:entry['weight'] for key,entry in result['entries'].items()},indent=2))
    else:
        snapshot = json.loads(weights_file.read_text(encoding='utf-8'))
        if args.command == 'plan':
            if args.target is None:
                parser.error('--target is required')
            result = search(args.directory,snapshot,target=args.target,cells=args.cells,
                            node_limit=args.node_limit,progress=report_progress)
            print(json.dumps({k:v for k,v in result.items() if k not in ('steps','weights')},indent=2))
        else:
            if not args.route:
                parser.error('--route is required')
            data = json.loads(args.route.read_text(encoding='utf-8'))
            routes = data.get('routes', data.get('structures', [data]))
            result = [{'routeIndex': i, **score_route(r,snapshot)} for i,r in enumerate(routes)]
            result.sort(key=lambda x:(not x['complete'],x['totalWeight'] or 0,x['routeIndex']))
            atomic_json(args.directory/'expected-scores.json',result)
            print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
