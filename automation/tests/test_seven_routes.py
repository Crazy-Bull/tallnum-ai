"""Seven-cell program contracts; no large game search or ten-cell search."""
from fractions import Fraction
import heapq
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from automation.route_search import RouteSearch, SCALE, Block
from automation.route_discovery import CandidateDiscovery
from automation.seven_routes import SevenCellPlanner, search_seven, main


ROOT = Path(__file__).resolve().parents[2]


def minimum_by_uniform_cost(search):
    heap, distances, serial = [(Fraction(0), 0, ())], {(): Fraction(0)}, 0
    while heap:
        cost, _, board = heapq.heappop(heap)
        if cost != distances[board]:
            continue
        if any(not b.group and b.value==search.target for b in board):
            return cost
        for _, after, added in search.successors(board):
            total = cost+added
            if after not in distances or total < distances[after]:
                distances[after] = total
                serial += 1
                heapq.heappush(heap, (total, serial, after))


def catalog_for(target, maximum=16):
    return {'policies': [{'id': f'{target}-single', 'target': target, 'exit': 'single',
                         'maxValue': maximum, 'maxGoalCells': 1,
                         'bases': list(range(1, maximum+1, 2)), 'policy': 'supplied-policy.bin',
                         'policySha256': 'test', 'exitSemantics': 'success-board-v2',
                         'petsc': {'verified': True, 'exitEvaluationRounds': 2},
                         'statistics': {'usable': True, 'p': .8, 'u': 8, 'v': 1}}]}


class SevenProgramTests(unittest.TestCase):
    def test_six_cell_macro_workspace_cannot_append_a_third_protected_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            for cells in (6,7):
                with RouteSearch(tmp,{'policies':[]},target=54,cells=cells,
                                 max_value=279,leaf_targets=[30,60,96],progress=False) as search:
                    board = (Block(96),Block(30))
                    additions = [op for op,_,_ in search.successors(board)
                                 if op['kind']=='leaf' and op['target']==60]
                    self.assertEqual(bool(additions),cells==7)

    def test_high_tier_ranking_outweighs_repeated_lower_stages(self):
        def path(target, repeats):
            return {'steps': [{'kind': 'leaf', 'target': target,
                              'template': f'5:{target}:single', 'exit': 'single'}]*repeats,
                    'units': str(target**3*repeats)}
        with tempfile.TemporaryDirectory() as tmp:
            with RouteSearch(tmp, {'policies': []}, target=640, candidate_limit=3) as search:
                low = path(128, 10)
                high = path(160, 1)
                self.assertGreater(Fraction(low['units']), Fraction(high['units']))
                ranked = search._structures([high, low])
                self.assertEqual(ranked[0], low)
                # Even when conservative pruning fills all slots, retain the
                # cost endpoint needed by the separate cubic-cost proof.
                ranked = search._structures([high, low, path(64,100), path(96,100)])
                self.assertEqual(len(ranked), 3)
                self.assertIn(high, ranked)

    def test_complement_discovery_uses_low_stages_and_legal_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            with RouteSearch(tmp, {'policies': []}, target=80, max_value=160,
                             leaf_targets=[10,16,32,40,80], progress=False) as search:
                paths, info = CandidateDiscovery(search, 300).discover()
                self.assertFalse(info['optimalityProven'])
                best = paths[0]
                self.assertLessEqual(max(s['target'] for s in best['steps']), 16)
                self.assertTrue(any(s['exit']=='extend' for s in best['steps']))
                board = ()
                for step in best['steps']:
                    self.assertEqual([b.json() for b in board], step['before'])
                    legal = [(after,cost) for op,after,cost in search.successors(board)
                             if op['kind']==step['kind'] and op.get('target')==step.get('target')
                             and op.get('exit')==step.get('exit')]
                    after, _ = next((a,c) for a,c in legal if [b.json() for b in a]==step['after'])
                    self.assertGreaterEqual(7-sum(b.span for b in board),5)
                    board = after
                self.assertEqual(board, (Block(80),))

    def test_api_defaults_to_seven_and_has_no_implicit_plan_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = io.StringIO()
            with patch('sys.stdout', output):
                result = search_seven(8, tmp, max_value=16, leaf_targets=[8], candidate_limit=3)
            self.assertEqual(output.getvalue(), '')
            self.assertEqual(result['cells'], 7)
            self.assertEqual(result['target'], 8)
            self.assertEqual(result['entryPoint'], 'seven-cell-reusable-program')
            self.assertEqual(result['status'], 'missing-policies')
            self.assertFalse((Path(tmp)/'route-plan.json').exists())
            self.assertTrue((Path(tmp)/'routes.sqlite3').exists())

    def test_arbitrary_goals_match_independent_shortest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = SevenCellPlanner(tmp, max_value=16, leaf_targets=[2, 4, 6, 8], candidate_limit=3)
            for goal in (6, 8, 12, 16):
                with RouteSearch(tmp, {'policies': []}, target=goal, cells=7,
                                 max_value=16, leaf_targets=[2, 4, 6, 8], candidate_limit=3,
                                 progress=False) as raw:
                    expected = minimum_by_uniform_cost(raw)
                result = planner.search(goal)
                self.assertEqual(Fraction(result['minimumStructuralUnits']), expected)
                self.assertEqual(result['cells'], 7)
                self.assertFalse(result['executableMinimumProven'])

    def test_seven_cell_nonstandard_bases_use_edge(self):
        with tempfile.TemporaryDirectory() as tmp:
            for goal, maximum, leaves in ((14, 120, [18,36,96]), (18, 100, [96])):
                result = search_seven(goal, tmp, max_value=maximum, leaf_targets=leaves, candidate_limit=3,node_limit=100)
                self.assertTrue(result['structures'])
                self.assertTrue(any(s['steps'][-1]['kind']=='edge' for s in result['structures']))
                for structure in result['structures']:
                    self.assertIn([goal, 1, False], structure['steps'][-1]['after'])
                    for step in structure['steps']:
                        if step['kind']=='leaf':
                            self.assertGreaterEqual(7-sum(b[1] for b in step['before']), 5)

    def test_resume_and_batch_never_load_saved_ten_cell_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            request = Path(tmp)/'route-request.json'
            request.write_text('{"cells":10,"target":768}', encoding='utf-8')
            planner = SevenCellPlanner(tmp, max_value=16, leaf_targets=[2, 4, 6, 8], candidate_limit=3)
            partial = planner.search(16, node_limit=1)
            self.assertEqual(partial['status'], 'paused')
            self.assertLessEqual(partial['search']['nodesThisRun'], 1)
            self.assertFalse(partial['structuralMinimumProven'])
            complete = planner.search(16)
            repeated = planner.search(16)
            self.assertEqual(complete['structures'], repeated['structures'])
            self.assertEqual(repeated['search']['nodesThisRun'], 0)
            results = planner.search_many([8, 12, 8])
            self.assertEqual(list(results), [8, 12])
            self.assertTrue(all(r['cells']==7 for r in results.values()))
            self.assertEqual(json.loads(request.read_text())['cells'], 10)

    def test_invalid_inputs_do_not_start_a_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'untouched'
            planner = SevenCellPlanner(path)
            for goals in ([8, 0], [8, True], [8, 65536], [8, 3.5]):
                with self.assertRaises(ValueError):
                    planner.search_many(goals)
            self.assertFalse(path.exists())
            excluded = search_seven(9, tmp, candidate_limit=3)
            self.assertFalse(excluded['structures'])
            self.assertEqual(excluded['search']['reason'], 'ordinary-odd-target-excluded-by-rules')

    def test_catalog_reload_picks_up_new_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = SevenCellPlanner(tmp, max_value=16, leaf_targets=[8], candidate_limit=3)
            self.assertFalse(planner.search(8)['routes'])
            catalog = catalog_for(8)
            catalog['policies'][0]['ruleSha256'] = 'edge-recheck-v1'
            file = Path(tmp)/'catalog.json'
            file.write_text(json.dumps(catalog), encoding='utf-8')
            result = planner.search(8)
            self.assertEqual(result['status'], 'ready-for-simulation')
            catalog['policies'][0]['statistics']['u'] = 4
            file.write_text(json.dumps(catalog), encoding='utf-8')
            updated = planner.search(8)
            self.assertNotEqual(result['routes'][0]['metrics'], updated['routes'][0]['metrics'])

    def test_weight_changes_reuse_statistics_but_refresh_difficulty(self):
        with tempfile.TemporaryDirectory() as tmp:
            options = dict(catalog=catalog_for(8), max_value=16, leaf_targets=[8], candidate_limit=3)
            original = search_seven(8, tmp, **options)
            changed = search_seven(8, tmp, weights={'5:8:single': 2}, **options)
            self.assertEqual(original['routes'][0]['metrics'], changed['routes'][0]['metrics'])
            self.assertEqual(changed['routes'][0]['weightedDifficulty'], 2)
            self.assertEqual(Fraction(changed['routes'][0]['structuralUnits']), 2*SCALE)
            self.assertGreater(changed['search']['cacheHits'], 0)

    def test_cli_emits_one_json_object_and_optionally_exports(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = ['--directory', tmp, '--target', '8', '--max-value', '16',
                    '--leaf-targets', '8', '--candidate-limit', '3']
            process = subprocess.run(['python', '-m', 'automation.seven_routes', *args], cwd=ROOT,
                                     text=True, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout)['cells'], 7)
            export = Path(tmp)/'explicit.json'
            with patch('sys.stdout', io.StringIO()) as output:
                result = main([*args, '--output', str(export)])
            self.assertEqual(output.getvalue(), '')
            self.assertEqual(json.loads(export.read_text(encoding='utf-8')), result)

    def test_deep_budget_search_has_no_python_recursion_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            with RouteSearch(tmp, {'policies': []}, target=8, cells=7, max_value=16,
                             leaf_targets=[2], candidate_limit=3, progress=False) as search:
                # A cost-positive cycle is legal for the bounded search. The
                # independent budget still decreases, but depth exceeds the
                # interpreter's usual recursion limit of ~1000.
                with patch.object(search, 'successors', side_effect=lambda board: iter([
                        ({'kind': 'leaf', 'target': 2, 'exit': 'single', 'template': '5:2:single'}, board, Fraction(8))])):
                    result = search._visit((), Fraction(8*1500))
                self.assertTrue(result['complete'])
                self.assertFalse(result['paths'])
                self.assertGreater(search.nodes, 1000)


if __name__ == '__main__':
    unittest.main()
