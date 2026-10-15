"""Desktop planning pipeline: legal incumbent, peak-count optimization, lower bound."""
import argparse
import json
from pathlib import Path
from .binary_routes import BinaryPlanner, structural_snapshot, verify_tree
from .peak_count_routes import focus
from .peak_count_bound import RelaxedPeakBound, INF
from .common import atomic_json


def execution_risks(steps, cells):
    if cells != 10:return []
    risks=[]
    for index, step in enumerate(steps,1):
        if step['kind']!='leaf':continue
        # The real ten-cell pool unlocks 15 only after a 200-point board.
        # A five-cell 60 single has zero starting value under the prior pool.
        if step.get('template')=='5:60:single':
            total=sum(block[0] for block in step['before'])
            if total<200:
                risks.append({'step':index,'template':step['template'],'fixedTotal':total,
                              'unlockThreshold':200})
    return risks


def event(message, **data):
    print(json.dumps({'event': 'progress', 'message': message, **data}, ensure_ascii=True), flush=True)


def plan_route(target, cells, directory, *, ceiling=None, maximum=None, depth=5,
               nodes=3000, focus_nodes=10000):
    if type(target) is not int or not 2 <= target <= 65535 or cells not in (7, 10):
        raise ValueError('目标须为 2–65535 的整数，塔容量须为七格或十格')
    if target % 2 and target != 15:
        raise ValueError('除 15 外，奇数不能作为普通单块目标')
    if not 0 <= depth <= 8 or not 1 <= nodes <= 1000000 or not 1 <= focus_nodes <= 1000000:
        raise ValueError('搜索预算或 EDGE 深度无效')
    maximum = maximum or min(65535, max(1024, 10 * target))
    if not target <= maximum <= 65535:
        raise ValueError('中间数上限不得小于目标')
    if ceiling is not None and (not standard_ceiling(ceiling) or ceiling < 24 or ceiling > maximum):
        raise ValueError('定式上限须为至少 24 且不超过中间数上限的标准目标')
    directory = Path(directory)
    # Remove the previous display result before a new run can be observed.
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'integer-result.json').unlink(missing_ok=True)
    event('正在构造合法路线')
    planner = BinaryPlanner(directory / 'search', structural_snapshot(ceiling or maximum),
                            maximum=maximum, minimum_leaf_target=24, maximum_leaf_target=ceiling, edge_depth=depth,
                            node_limit=nodes, progress=lambda d: event('正在搜索路线', **d))
    try:
        candidate = planner.plan(target, cells)
    finally:
        planner.close()
    if candidate['tree']['cost'] is None:
        result = {'target': target, 'cells': cells, 'status': 'incomplete' if candidate['status'] == 'paused' else 'no-route',
                  'ceiling': ceiling, 'upperBound': None, 'lowerBound': None,
                  'countProven': False, 'peakProven': False, 'leafCalls': 0, 'profile': [], 'steps': [],
                  'scope': {'maximum': maximum, 'edgeDepth': depth, 'minimumTemplateTarget':24}, 'randomExecutionVerified': False,
                  'executionRisks': []}
    else:
        event('正在减少最高阶定式调用')
        candidate = focus(candidate, directory / 'focused', node_limit=focus_nodes,
                          maximum_task=target, split_mode='all')
        trace = verify_tree(candidate['tree'], cells)
        event('正在核对最少次数下界')
        dp = RelaxedPeakBound(candidate)
        lower = dp.solve(('s', cells, target, depth))
        upper = sum(count for key, count in candidate['leafCounts'].items()
                    if int(key.split(':')[1]) == dp.ceiling)
        lower = None if lower == INF else lower
        previous = previous_ceiling(dp.ceiling)
        peak_proven = previous < 24 or target > 2 * previous * 3 ** (cells - 6)
        if not peak_proven:
            event('正在核对更低定式上限')
            smaller = RelaxedPeakBound(candidate, ceiling=previous)
            peak_proven = smaller.solve(('s', cells, target, depth)) == INF
        candidate['minimumPeakCountProvenInScope'] = lower == upper
        candidate['peakCountCertificate'] = {'lowerBound': lower, 'upperBound': upper,
                                             'gapClosed': lower == upper, 'states': dp.nodes,
                                             'maximum': maximum, 'edgeDepth': depth}
        atomic_json(directory / 'binary-plan.json', candidate)
        atomic_json(directory / 'ideal-connection-trace.json', trace)
        result = {'target': target, 'cells': cells, 'status': 'proven' if lower == upper else 'candidate',
                  'ceiling': dp.ceiling, 'upperBound': upper, 'lowerBound': lower,
                  'countProven': lower == upper, 'peakProven': peak_proven,
                  'leafCalls': candidate['leafCalls'], 'profile': candidate['difficultyProfile'],
                  'steps': trace['steps'], 'proofStates': dp.nodes,
                  'scope': {'maximum': maximum, 'edgeDepth': depth, 'minimumTemplateTarget':24}, 'randomExecutionVerified': False,
                  'executionRisks': execution_risks(trace['steps'],cells)}
    atomic_json(directory / 'integer-result.json', result)
    event('规划完成', status=result['status'])
    return result


def standard_ceiling(value):
    from .expected_routes import standard
    return type(value) is int and value >= 2 and standard(value)


def previous_ceiling(value):
    return max((v for v in range(2, value) if standard_ceiling(v)), default=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', type=int)
    parser.add_argument('--cells', type=int, choices=(7, 10), default=10)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--ceiling', type=int)
    parser.add_argument('--maximum', type=int)
    parser.add_argument('--edge-depth', type=int, default=5)
    parser.add_argument('--node-limit', type=int, default=3000)
    parser.add_argument('--focus-nodes', type=int, default=10000)
    args = parser.parse_args()
    try:
        plan_route(args.target, args.cells, args.directory, ceiling=args.ceiling, maximum=args.maximum,
                   depth=args.edge_depth, nodes=args.node_limit, focus_nodes=args.focus_nodes)
    except Exception as exc:
        print(json.dumps({'event': 'error', 'message': str(exc)}, ensure_ascii=True), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
