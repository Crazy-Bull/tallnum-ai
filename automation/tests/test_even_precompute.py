from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from automation.even_precompute import EvenPrecomputer
from automation.route_search import Block


class EvenPrecomputeTests(unittest.TestCase):
    def test_arithmetic_dp_is_a_lower_bound_not_a_physical_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvenPrecomputer(tmp,cells=6)
            self.assertEqual(planner.bounds['costs'][54],272)
            self.assertEqual(planner.bounds['recipes'][54]['ordinary'],272)
            self.assertEqual(planner.bounds['recipes'][54]['group'],270)
            self.assertFalse(planner.bounds['recipes'][54]['groupConstructionVerified'])
            result = planner.lookup(54)
            self.assertEqual(result['status'],'unknown')
            self.assertEqual(result['peakLowerBound'],272)
            self.assertFalse(result['minimumPeakProven'])
            self.assertEqual(planner.lookup(65534)['status'],'unreachable-in-scope')

    def test_exhaustion_classifies_every_target_without_false_unreachability(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvenPrecomputer(tmp,cells=1,max_value=16)
            complete = planner.precompute(max_target=16,node_limit=0)
            self.assertEqual(complete['status'],'exhausted')
            self.assertEqual(complete['provenTargets'],5)
            self.assertEqual(complete['unreachableInScopeTargets'],3)
            for target in (2,4,6,8,10):
                r = planner.lookup(target)
                self.assertEqual(r['peak'],target)
                self.assertTrue(r['minimumPeakProven'])
            self.assertEqual(planner.lookup(12)['status'],'unreachable-in-scope')
            waiting = EvenPrecomputer(tmp,cells=2,max_value=16)
            partial = waiting.precompute(max_target=16,node_limit=1)
            self.assertEqual(partial['status'],'paused')
            self.assertEqual(partial['unreachableInScopeTargets'],partial['arithmeticExcludedTargets'])
            self.assertEqual(waiting.lookup(8)['status'],'minimum-peak-proven')

    def test_full_route_peak_beats_shorter_path_with_larger_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvenPrecomputer(tmp,cells=3,max_value=32)
            def moves(board,last,repeats,maximum):
                targets = {():[2,20],(Block(2),):[4],(Block(4),):[8],(Block(20),):[8]}
                for value in targets.get(board,[]):
                    yield {'kind':'test','input':value},(Block(value),),None,0,1
            with patch.object(planner.engine,'successors',side_effect=moves):
                planner.precompute(max_target=8,node_limit=0)
            result = planner.lookup(8)
            self.assertEqual(result['peak'],8)
            self.assertEqual(result['actions'],3)
            self.assertEqual([s['action']['input'] for s in result['path']],[2,4,8])
            self.assertFalse(result['shortestActionCountProven'])

    def test_54_edge_group_exit_and_initial_peak_are_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvenPrecomputer(tmp,cells=6,initial=[272,240,30],max_value=279)
            planner.precompute(max_target=54,node_limit=2000)
            result = planner.lookup(54)
            self.assertTrue(result['minimumPeakProven'])
            self.assertEqual(result['peak'],272)
            self.assertEqual([s['action']['kind'] for s in result['path']],['group','edge'])
            group = planner.lookup(270,kind='group',span=2)
            self.assertEqual(group['peak'],272)
            self.assertTrue(group['minimumPeakProven'])
            self.assertNotEqual(group['status'],planner.lookup(270)['status'])

    def test_goal_range_extension_and_restart_share_a_single_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvenPrecomputer(tmp,cells=1,max_value=16)
            first = planner.precompute(max_target=10,node_limit=0)
            restarted = EvenPrecomputer(tmp,cells=1,max_value=16)
            second = restarted.precompute(max_target=16,node_limit=0)
            self.assertEqual(first['cacheId'],second['cacheId'])
            self.assertEqual(second['nodesThisRun'],0)
            changed = EvenPrecomputer(tmp,cells=2,max_value=16)
            self.assertNotEqual(changed.run_id,planner.run_id)

    def test_export_has_an_entry_for_every_even_and_unknown_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp)/'index.json'
            planner = EvenPrecomputer(tmp,cells=2,max_value=16)
            planner.precompute(max_target=16,node_limit=1,export=export)
            data = json.loads(export.read_text())
            self.assertEqual([r['target'] for r in data['ordinary']],list(range(2,17,2)))
            self.assertEqual(data['ordinary'][-1]['status'],'unknown')
            self.assertIsNone(data['ordinary'][-1]['peak'])
            self.assertFalse(data['summary']['stochasticPolicyVerified'])
            self.assertIsNone(planner.lookup(2)['fiveCellTemplateCounts'])

    def test_interrupt_saves_frontier_and_invalid_scope_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner = EvenPrecomputer(tmp,cells=3,max_value=32)
            def stop(update):
                raise KeyboardInterrupt
            result = planner.precompute(max_target=32,node_limit=200,progress=stop)
            self.assertTrue(result['interrupted'])
            resumed = planner.precompute(max_target=32,node_limit=1)
            self.assertEqual(resumed['statesExpanded'],result['statesExpanded']+1)
            for target in (0,15,65535,True):
                with self.assertRaises(ValueError):planner.precompute(max_target=target)
            with self.assertRaises(ValueError):planner.lookup(27)
            with self.assertRaises(ValueError):planner.lookup(30,kind='group',span=1)


if __name__=='__main__':
    unittest.main()
