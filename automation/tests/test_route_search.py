import contextlib
from fractions import Fraction
import heapq
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from automation import game
from automation.planner import Metrics
from automation.route_search import (Block, RouteSearch, Weights, SCALE, normalize,
                                     edge_board, representatives)
from automation.route_runtime import RouteExecutor
from automation.route_variants import manifest
from automation.validation import summarize


ROOT = Path(__file__).resolve().parents[2]


def view(state):
    return {'tower': [list(t) for t in game.signature(state)], 'queue': state['queue'],
            'rngState': state['rngState'], 'drops': state['drops'], 'actions': state['actions'],
            'gameOver': state['gameOver'], 'unlocked': state['unlocked']}


def exhaustive_minimum(search):
    # Independent uniform-cost traversal, without memo-budget/representative logic.
    heap, serial, distances = [(Fraction(0), 0, ())], 0, {(): Fraction(0)}
    while heap:
        cost, _, board = heapq.heappop(heap)
        if distances[board] != cost:
            continue
        if any(b.value==search.target and not b.group for b in board):
            return cost
        for _, after, added in search.successors(board):
            total = cost+added
            if after not in distances or total < distances[after]:
                distances[after] = total
                serial += 1
                heapq.heappush(heap, (total, serial, after))


class SearchTests(unittest.TestCase):
    def make(self, path, **kwargs):
        search = RouteSearch(path, {'policies': []}, **kwargs)
        self.addCleanup(search.close)
        return search

    def test_weights_use_actual_goal_and_count_repeats(self):
        w = Weights()
        self.assertEqual(w.units(96, 'single')/SCALE, 8)
        self.assertGreater(w.units(128, 'single'), 2*w.units(96, 'single'))
        self.assertEqual(w.units(96, 'single')+w.units(96, 'single'), Fraction(16*SCALE))
        self.assertEqual(Weights({'5:128:single': '15.5'}).units(128, 'single'), Fraction('15.5')*SCALE)
        for override in ({'5:2:single': 0}, {'5:2:single': -1}, {'bad': 2}, {'5:2:single': float('inf')}):
            with self.assertRaises((ValueError, OverflowError)):
                Weights(override)

    def test_minimum_matches_exhaustive_graph(self):
        for cells in (7, 10):
            with tempfile.TemporaryDirectory() as tmp:
                search = self.make(tmp, target=8, cells=cells, max_value=12,
                                   leaf_targets=[2, 4, 6, 8], candidate_limit=3)
                minimum = exhaustive_minimum(search)
                with contextlib.redirect_stdout(io.StringIO()):
                    plan = search.plan()
                self.assertEqual(Fraction(plan['minimumStructuralUnits']), minimum)
                self.assertTrue(plan['structuralMinimumProven'])
                self.assertFalse(plan['executableMinimumProven'])
                self.assertEqual(min(s['weightedDifficulty'] for s in plan['structures']), float(minimum/SCALE))
                search.close()

    def test_edge_route_creates_nonstandard_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            search = self.make(tmp, target=18, cells=10, max_value=100,
                               leaf_targets=[96], candidate_limit=3, node_limit=100)
            with contextlib.redirect_stdout(io.StringIO()):
                plan = search.plan()
            self.assertIn(plan['status'],('missing-policies','paused'))
            self.assertTrue(any(s['steps'][-1]['kind']=='edge' for s in plan['structures']))
            for structure in plan['structures']:
                self.assertIn([18, 1, False], structure['steps'][-1]['after'])
            self.assertGreater(Fraction(plan['lowestKnownStructuralUnits']), 0)
            self.assertFalse(plan['executableMinimumProven'])
            search.close()

    def test_group_physical_slots_and_edge_recheck(self):
        self.assertEqual(edge_board((Block(10), Block(15), Block(24))), (Block(2), Block(24)))
        self.assertEqual(edge_board((Block(240), Block(244), Block(40))), (Block(8),))
        with tempfile.TemporaryDirectory() as tmp:
            search = self.make(tmp, target=14, cells=7, max_value=80, leaf_targets=[2, 4, 6, 8])
            board = (Block(2), Block(4), Block(8))
            group = next(x for x in search.successors(board) if x[0].get('indices')==[0, 1, 2])
            self.assertEqual(group[1], (Block(14, 3, True),))
            self.assertFalse(any(op['kind']=='leaf' for op, _, _ in search.successors(group[1])))
            self.assertFalse(any(op['kind']=='group' for op, _, _ in search.successors(group[1])))
            search.close()

    def test_pause_resume_and_weight_cache_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = dict(target=8, cells=7, max_value=12, leaf_targets=[2, 4, 6, 8], candidate_limit=3)
            search = RouteSearch(tmp, {'policies': []}, node_limit=1, **config)
            plan = search.plan()
            search.close()
            self.assertEqual(plan['status'], 'paused')
            self.assertIsNone(plan['minimumStructuralUnits'])
            continued = RouteSearch(tmp, {'policies': []}, **config)
            complete = continued.plan()
            namespace = continued.namespace
            continued.close()
            repeated = RouteSearch(tmp, {'policies': []}, **config)
            again = repeated.plan()
            self.assertEqual(complete['structures'], again['structures'])
            self.assertEqual(again['search']['nodesThisRun'], 0)
            repeated.close()
            changed = RouteSearch(tmp, {'policies': []}, weights={'5:2:single': 10}, **config)
            self.assertNotEqual(namespace, changed.namespace)
            changed.close()

    def test_representatives_preserve_extremes_and_spread(self):
        front = [{'id': str(i), 'metrics': Metrics(i/100, i/100*i, (1-i/100)*i)} for i in range(1, 100)]
        result = representatives(front)
        self.assertEqual(len(result), 20)
        self.assertIn('1', {r['id'] for r in result})
        self.assertIn('99', {r['id'] for r in result})
        probabilities = sorted(r['metrics'].p for r in result)
        self.assertLess(max(b-a for a, b in zip(probabilities, probabilities[1:])), .1)
        dominated = {'id': 'dominated', 'metrics': Metrics(.1, 100, 100)}
        self.assertNotIn('dominated', {r['id'] for r in representatives(front+[dominated])})

    def test_variant_summary_and_cached_metrics_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            search = self.make(tmp, target=8, max_value=16, candidate_limit=3, leaf_targets=[8])
            req = search.requirement(8, 'single')
            policies = []
            for i, alpha in enumerate(req['aggressiveness']):
                policies.append({'id': f'p{i}', 'target': 8, 'exit': 'single', 'maxValue': 16,
                                 'bases': req['bases'], 'maxGoalCells': 1, 'policy': f'fake{i}.bin',
                                 'policySha256': str(i), 'variantAggressiveness': alpha,
                                 'exitSemantics': 'success-board-v2',
                                 'petsc': {'verified': True, 'exitEvaluationRounds': 2},
                                 'statistics': {'usable': True, 'p': .5+i*.1, 'u': 1+i, 'v': 1}})
            report = manifest(tmp, req, {'policies': policies})
            self.assertTrue(report['complete'])
            self.assertEqual(len(report['variants']), 1)
            self.assertTrue(list((Path(tmp)/'templates').glob('*/variants.json')))
            search.catalog = {'policies': policies}
            structure = {'units': '512', 'steps': [{'kind': 'leaf', 'target': 8, 'exit': 'single',
                          'template': '5:8:single', 'before': [], 'after': [[8, 1, False]]}]}
            first = search.compose(structure)
            policies[0]['statistics']['u'] = .1
            second = search.compose(structure)
            self.assertNotEqual(first, second)
            search.close()


class GameParityTests(unittest.TestCase):
    def test_seven_and_ten_cells_every_step(self):
        output = subprocess.check_output(['node', str(ROOT/'automation/tests/parity_routes.mjs')], text=True, encoding='utf-8', input='')
        for case in json.loads(output):
            state = game.new_game(case['seed'], case['cells'])
            self.assertEqual(view(state), case['trace'][0])
            for index, action in enumerate(case['actions']):
                state = game.apply(state, action)
                self.assertEqual(view(state), case['trace'][index+1], (case['cells'], case['seed'], index))

    def test_unlock_thresholds_rotation_edge_and_group(self):
        fixtures = []
        for values, action in (([24, 6], {'kind': 'drop'}), ([48, 48], {'kind': 'drop'}),
                               ([96, 96], {'kind': 'drop'}), ([96, 4, 96], {'kind': 'up'}),
                               ([72, 78], {'kind': 'edge'}), ([32, 24, 8], {'kind': 'group', 'indices': [1, 2]})):
            state = game.new_game(123, 10)
            state['tower'] = [game.tile(state, v) for v in values]
            state['queue'] = [8, 4, 8, 2]
            fixtures.append({'state': state, 'actions': [action, {'kind': 'drop'}]})
        expected = json.loads(subprocess.check_output(['node', str(ROOT/'automation/tests/parity_routes.mjs')],
                  text=True, encoding='utf-8', input=json.dumps(fixtures)))
        for fixture, trace in zip(fixtures, expected):
            state = fixture['state']
            for action, snapshot in zip(fixture['actions'], trace):
                state = game.apply(state, action)
                self.assertEqual(view(state), snapshot)
        for seed in range(10):
            self.assertEqual(game.new_game(seed, 10)['unlocked'], [2, 4, 8])


class RuntimeTests(unittest.TestCase):
    def test_edge_contract_executes_with_residual_retained(self):
        state = game.new_game(1, 10)
        state['tower'] = [game.tile(state, v) for v in [72, 78, 4]]
        route = {'version': 2, 'kind': 'stages', 'cells': 10, 'target': 14, 'steps': [
            {'kind': 'edge', 'before': [[72, 1, False], [78, 1, False]], 'after': [[14, 1, False]]}]}
        executor = RouteExecutor(route, {'policies': []})
        executor.fixed_ids = {t['id'] for t in state['tower'][:2]}
        before = game.observation(state)
        action = executor.next_action(before)
        self.assertEqual(action, {'kind': 'edge'})
        state = game.apply(state, action)
        executor.accept(before, action, game.observation(state))
        self.assertEqual(game.signature(state), [(14, 1, 'tile'), (4, 1, 'tile')])
        self.assertIsNone(executor.next_action(game.observation(state)))

    def test_wrong_exit_abandons_and_counts_finishing_drops(self):
        state = game.new_game(1, 10)
        route = {'version': 2, 'kind': 'stages', 'cells': 10, 'target': 14, 'steps': [
            {'kind': 'edge', 'before': [[72, 1, False], [78, 1, False]], 'after': [[14, 1, False]]}]}
        executor = RouteExecutor(route, {'policies': []})
        self.assertEqual(executor.next_action(game.observation(state)), {'kind': 'drop'})
        self.assertEqual(executor.failure_reason, 'stage-exit-contract-mismatch')
        state['tower'] = [game.tile(state, v) for v in [14, 4, 8, 6, 10, 15, 2, 4, 8, 6]]
        state['gameOver'] = True
        self.assertIsNone(executor.next_action(game.observation(state)))
        result = summarize([{'outcome': 'success', 'drops': 2}, {'outcome': 'failure', 'drops': 18}])
        self.assertEqual(result['expectedTotalDrops'], 20)


@unittest.skipUnless((ROOT/'desktop/native/tallnum_automation_routes.exe').exists()
                    and (ROOT/'automation/runs/route-v2-native/catalog.json').exists(),
                    'build routes bridge and run the small native variant fixture first')
class NativeRouteTests(unittest.TestCase):
    def test_identical_policies_keep_all_aggressiveness_records(self):
        from automation.library import load_catalog, PolicyWorker
        catalog = load_catalog(ROOT/'automation/runs/route-v2-native', certified_only=True)
        policies = [p for p in catalog['policies'] if p['target']==2 and p['exit']=='single']
        alphas = {float(p.get('variantAggressiveness', p.get('aggressiveness', 0))) for p in policies}
        self.assertTrue({0, .001, .005, .01, .05} <= alphas)
        self.assertGreaterEqual(len({p['id'] for p in policies}), 5)
        worker = PolicyWorker(policies[0])
        try:
            reply = worker.query([], 0, [2, 4])
            self.assertEqual(reply['status'], 'ok')
            self.assertTrue(reply['success'])
            self.assertEqual(reply['board']['blocks'][0]['value'], 2)
        finally:
            worker.close()

    @unittest.skipUnless((ROOT/'desktop/native/tallnum_reachable_routes.exe').exists(), 'build routes generator first')
    def test_all_bases_does_not_need_a_large_command_argument(self):
        from automation.library import table_header
        with tempfile.TemporaryDirectory() as tmp:
            table = Path(tmp)/'all.bin'
            process = subprocess.run([str(ROOT/'desktop/native/tallnum_reachable_routes.exe'),
                       '--cells', '1', '--target', '2', '--bases', 'all', '--max-value', '65535',
                       '--output', str(table)], text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            header = table_header(table)
            self.assertEqual(len(header['bases']), 32768)
            self.assertEqual(header['bases'][-1], 65535)


if __name__ == '__main__':
    unittest.main()
