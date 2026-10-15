import tempfile
import unittest
from fractions import Fraction

from automation.binary_routes import BinaryPlanner, verify_tree, structural_snapshot
from automation.route_search import Block
from automation.tests.test_expected_routes import snapshot


class BinaryRouteTests(unittest.TestCase):
    def test_unlock_gate_checks_actual_template_and_fixed_total(self):
        data=snapshot({'5:60:single':1})
        with tempfile.TemporaryDirectory() as tmp:
            planner=BinaryPlanner(tmp,data,maximum=128,edge_depth=0,node_limit=1,
                                  minimum_total_for_template={'5:60:single':200})
            try:
                self.assertIsNone(planner.solve(('single',9,60,0),(Block(96),))['cost'])
                planner.nodes=0
                self.assertIsNotNone(planner.solve(('single',9,60,0),(Block(200),))['cost'])
            finally:planner.close()

    def test_opening_target_restriction_applies_to_five_cell_leaf(self):
        data=snapshot({'5:32:single':1})
        with tempfile.TemporaryDirectory() as tmp:
            planner=BinaryPlanner(tmp,data,maximum=64,edge_depth=0,node_limit=0,
                                  opening_targets={64})
            try:self.assertIsNone(planner.solve(('single',5,32,0))['cost'])
            finally:planner.close()

    def test_difficulty_beats_cheap_higher_policy(self):
        data=snapshot({'5:32:single':1,'5:16:single':100,'5:16:match':100})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=64,edge_depth=0,node_limit=0)
            try:
                result=p.plan(32,7)
                self.assertEqual(result['leafCounts'],{'5:16:match':1,'5:16:single':1})
                self.assertEqual(result['totalWeight'],200)
                self.assertTrue(result['idealConnectionsVerified'])
            finally:p.close()

    def test_equal_difficulty_prefers_fewer_calls_before_weight(self):
        data=snapshot({'5:16:single':100,'5:8:single':1,'5:8:match':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=64,edge_depth=0,node_limit=0)
            try:
                leaf=p.leaf(('single',5,16,0))
                more={**leaf,'profile':[x*2 for x in leaf['profile']],'cost':'1'}
                self.assertLess(p.score(leaf),p.score(more))
            finally:p.close()

    def test_cap_and_objective_invalidate_cache(self):
        data=snapshot({'5:32:single':1,'5:16:single':100,'5:16:match':100})
        with tempfile.TemporaryDirectory() as tmp:
            runs=[]
            for objective,cap,expected in [('weight',32,1),('difficulty',32,200),('weight',16,200)]:
                p=BinaryPlanner(tmp,data,maximum=64,edge_depth=0,node_limit=0,
                                objective=objective,maximum_leaf_target=cap)
                try:
                    self.assertEqual(p.plan(32,7)['totalWeight'],expected)
                    runs.append(p.run)
                finally:p.close()
            self.assertEqual(len(set(runs)),3)

    def test_repeated_queries_do_not_reuse_wrong_cell_budget(self):
        data=snapshot({'5:16:single':1,'5:16:match':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=128,edge_depth=0,node_limit=0)
            try:
                for cells,target in [(10,64),(7,32),(10,64)]:
                    result=p.plan(target,cells)
                    self.assertEqual(verify_tree(result['tree'],cells)['finalBoard'],[[target,1,False]])
            finally:p.close()

    def test_10240_automatically_avoids_80_and_verifies_full_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(),maximum=20480,node_limit=3000)
            try:
                result=p.plan(10240,10)
                trace=verify_tree(result['tree'],10)
                self.assertEqual(trace['finalBoard'],[[10240,1,False]])
                self.assertEqual(result['difficultyProfile'][0]['target'],64)
                self.assertTrue(all(int(k.split(':')[1])<=64 for k in result['leafCounts']))
                self.assertTrue(result['minimumPeakProvenInScope'])
                self.assertFalse(result['minimumDifficultyProvenInScope'])
                self.assertFalse(result['executionVerified'])
                self.assertTrue(result['missingPolicies'])
                self.assertIn([[5120,1,False],[3456,1,False],[1152,1,False],[384,1,False],[128,1,False]],
                              [s['before'] for s in trace['steps'] if s['kind']=='group'])
                self.assertTrue(any(s['kind']=='edge' for s in trace['steps']))
            finally:p.close()

    def test_nonstandard_goal_and_repeated_edge_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(64),maximum=1024,
                            maximum_leaf_target=64,node_limit=1000)
            try:
                result=p.plan(54,10)
                trace=verify_tree(result['tree'],10)
                self.assertEqual(trace['finalBoard'],[[54,1,False]])
                self.assertGreaterEqual(sum(s['kind']=='edge' for s in trace['steps']),5)
            finally:p.close()

    def test_boundary_can_be_reused_with_exactly_five_free_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,snapshot({'5:64:match':1,'5:64:extend':1}),
                            maximum=384,edge_depth=0,node_limit=0,maximum_leaf_target=64)
            try:
                entrance=(Block(192),Block(64))
                answer=p.solve(('extend',5,128,0,192,64),entrance)
                self.assertEqual(answer['rule'],'reuse-boundary')
                self.assertEqual(verify_tree(p.export(answer),7,entrance)['finalBoard'],[[384,1,False]])
            finally:p.close()

    def test_guided_search_includes_nonstandard_third_components(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(),maximum=20480)
            try:self.assertIn(1728,p.candidates(2,5118))
            finally:p.close()

    def test_seed_polishing_spends_spare_cells_to_remove_high_leaf(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(64),maximum=128,maximum_leaf_target=64)
            try:
                leaf=p.leaf(('single',6,64,0))
                improved=p.polish_seed(leaf)
                self.assertLess(p.score(improved),p.score(leaf))
                trace=verify_tree(improved,6)
                self.assertEqual(trace['finalBoard'],[[64,1,False]])
                self.assertLess(max(s['target'] for s in trace['steps'] if s['kind']=='leaf'),64)
            finally:p.close()

    def test_six_free_cells_replace_extend64_by_two32_leaves(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(64),maximum=2560,maximum_leaf_target=64)
            try:
                entrance=(Block(1280),Block(864),Block(208),Block(144))
                leaf=p.leaf(('extend',6,64,5,208,144))
                improved=p.polish_seed(leaf,entrance)
                trace=verify_tree(improved,10,entrance)
                self.assertEqual(trace['finalBoard'],[[1280,1,False],[864,1,False],[416,1,False]])
                self.assertEqual([s['target'] for s in trace['steps'] if s['kind']=='leaf'],[32,32])
            finally:p.close()

    def test_relaxed_peak_bound_matches_verified_small_route(self):
        from automation.peak_count_bound import RelaxedPeakBound
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(64),maximum=1024,
                            maximum_leaf_target=64,edge_depth=0,node_limit=5000,
                            split_mode='all',objective='peak-count')
            try:
                plan=p.plan(384,7)
                dp=RelaxedPeakBound(plan)
                self.assertEqual(dp.solve(('s',7,384,0)),2)
                self.assertEqual(dp.solve(('m',7,576,0)),4)
                self.assertEqual(dp.solve(('s',6,128,0)),1)
                self.assertEqual(dp.solve(('m',6,128,0)),0)
            finally:p.close()

    def test_unreachable_incumbent_does_not_crash_optimizer(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(64),maximum=1024,
                            maximum_leaf_target=64,edge_depth=0,node_limit=100,
                            objective='peak-count')
            try:
                task=('single',5,32,0)
                key=json.dumps([task,[]],separators=(',',':'))
                p.seeds[key]={'task':task,'cost':None,'complete':False}
                self.assertEqual(p.solve(task)['cost'],'1')
            finally:p.close()

    def test_peak_count_objective_ignores_lower_rank_ties(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(64),maximum=1024,
                            maximum_leaf_target=64,objective='peak-count')
            try:
                expensive=p.leaf(('single',5,64,0))
                cheaper=p.leaf(('single',5,60,0))
                self.assertLess(p.score(cheaper),p.score(expensive))
                self.assertEqual(p.score(cheaper),p.score(p.leaf(('single',5,2,0))))
            finally:p.close()

    def test_all_splits_proves_four64_calls_for_seven_free_cell576_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(64),maximum=20480,
                            maximum_leaf_target=64,edge_depth=0,node_limit=5000,
                            split_mode='all',objective='peak-count')
            try:
                p.cells=8;p.seed_mode=True
                task=('match',7,576,0);before=(Block(576),)
                seed=p.polish_seed(p.export(p.solve(task,before)),before)
                p.templates[__import__('json').dumps(task)]=seed
                p.reuse_seed(task,before)
                p.seeds=dict(p.memory);p.memory={};p.nodes=0;p.seed_mode=False
                answer=p.solve(task,before)
                self.assertTrue(answer['complete'])
                self.assertEqual(p.score(answer),(4,))
                self.assertEqual(verify_tree(p.export(answer),8,before)['finalBoard'],[[1152,1,False]])
            finally:p.close()

    def test_four_cell_templates_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'5.255 cells'):
                BinaryPlanner(tmp,snapshot({'4:32:single':1,'5:48:single':1}),maximum=1024)

    def test_seven_free_cell576_match_cannot_use_below64_in_grammar(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,structural_snapshot(60),maximum=20480,maximum_leaf_target=60)
            try:
                self.assertFalse(p.capacity_possible(('match',7,576,0)))
                self.assertIsNone(p.solve(('match',7,576,0),(Block(576),))['cost'])
            finally:p.close()

    def test_minimum_target_is_enforced_even_with_cheap_small_leaf(self):
        data=snapshot({'5:8:single':1,'5:32:single':10,'6:40:single':12})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=80,edge_depth=0,node_limit=100,minimum_leaf_target=24)
            try:
                self.assertIsNone(p.leaf(('single',6,8,0)))
                self.assertIsNone(p.solve(('single',6,8,0))['cost'])
                self.assertEqual(p.leaf(('single',6,40,0))['template'],'6:40:single')
            finally:p.close()
    def test_leaf_floor_does_not_exclude_smaller_edge_intermediate(self):
        data=snapshot({'5:48:single':1,'5:48:match':1,'5:60:single':1,'5:30:single':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=100,edge_depth=1,node_limit=0,minimum_leaf_target=24)
            try:
                result=p.export(p.solve(('single',7,18,1)))
                self.assertIsNotNone(result['cost'])
                checked=verify_tree(result,7)
                self.assertEqual(checked['finalBoard'],[[18,1,False]])
                self.assertTrue(all(s['target']>=24 for s in checked['steps'] if s['kind']=='leaf'))
            finally:p.close()

    def test_nonstandard_single_needs_seven_cells_without_buffer_primitive(self):
        data=snapshot({'5:384:single':1,'5:320:single':1,'5:60:single':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=400,edge_depth=1,node_limit=0)
            try:
                six=p.solve(('single',6,76,1))
                self.assertIsNone(six['cost'])
                self.assertTrue(six['complete'])
                self.assertEqual(p.nodes,0)
                seven=p.solve(('single',7,76,1))
                self.assertEqual(Fraction(seven['cost']),3)
                self.assertEqual(verify_tree(p.export(seven),10)['finalBoard'],[[76,1,False]])
            finally:p.close()

    def test_guided_midpoint_includes_neighboring_even_nonstandard_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,snapshot({'5:2:single':1}),maximum=20480)
            try:
                values=p.candidates(384,766)
                self.assertIn(574,values)
                self.assertIn(576,values)
                self.assertNotIn(575,values)
            finally:p.close()

    def test_boundary_reuse_keeps_both_workspaces(self):
        data=snapshot({'5:16:match':5,'5:16:extend':5,'5:32:single':100})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=96,edge_depth=0,node_limit=0)
            try:
                a=p.solve(('extend',6,32,0,48,16),(Block(48),Block(16)))
                tree=p.export(a)
                self.assertEqual(a['rule'],'reuse-boundary')
                self.assertEqual(Fraction(a['cost']),10)
                self.assertEqual([c['task'][1] for c in tree['children']],[6,6])
                self.assertEqual(verify_tree(tree,8,(Block(48),Block(16)))['finalBoard'],[[96,1,False]])
            finally:p.close()

    def test_buffer_can_exceed_ordinary_neighbor(self):
        data=snapshot({'5:24:single':1,'5:10:single':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=80,edge_depth=0,node_limit=0)
            try:
                a=p.solve(('buffer',6,3,0,(),32),(Block(32),))
                tree=p.export(a)
                result=verify_tree(tree,7,(Block(32),))
                self.assertEqual(a['groupTarget'],34)
                self.assertEqual(result['finalBoard'],[[32,1,False],[34,2,True]])
            finally:p.close()

    def test_odd_group_sum_is_legal_and_no_nested_group(self):
        data=snapshot({'5:15:single':1,'5:20:single':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=80,edge_depth=0,node_limit=0)
            try:
                a=p.solve(('group',6,35,0,(),32),(Block(32),))
                self.assertEqual(verify_tree(p.export(a),7,(Block(32),))['finalBoard'][-1],[35,2,True])
                b=p.solve(('group',5,35,0,(20,),32),(Block(32),Block(20,2,True)))
                self.assertIsNone(b['cost'])
            finally:p.close()

    def test_seed_compares_buffer_costs_instead_of_first_reachable_total(self):
        data=snapshot({'5:20:single':10,'5:24:single':2,'5:10:single':2})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=80,edge_depth=0,node_limit=0,objective='weight')
            try:
                p.seed_mode=True
                answer=p.solve(('buffer',6,3,0,(),32),(Block(32),))
                self.assertEqual(answer['groupTarget'],34)
                self.assertEqual(Fraction(answer['cost']),4)
                verify_tree(p.export(answer),7,(Block(32),))
            finally:p.close()

    def test_full_entrance_prevents_premature_merge_and_cache_collision(self):
        data=snapshot({'5:96:single':1,'5:2:single':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=100,edge_depth=0,node_limit=0)
            try:
                task=('group',6,98,0,(),96)
                bad=p.solve(task,(Block(96),))
                good=p.solve(task,(Block(64),))
                self.assertEqual(Fraction(bad['cost']),2)
                # 96 first would consume the protected 96. The buffer must
                # instead put 2 first; buffer ordering is deliberately exempt.
                self.assertEqual(p.export(bad)['children'][0]['task'][2],2)
                verify_tree(p.export(bad),7,(Block(96),))
                self.assertEqual(Fraction(good['cost']),2)
                self.assertEqual(p.export(good)['children'][0]['task'][2],96)
                self.assertEqual(verify_tree(p.export(good),7,(Block(64),))['finalBoard'][-1],[98,2,True])
            finally:p.close()

    def test_no_nonstandard_leaf_and_resume_weight_invalidation(self):
        data=snapshot({'5:14:single':1,'5:16:single':3,'5:16:match':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=64,edge_depth=0,node_limit=0)
            try:
                self.assertIsNone(p.leaf(('single',5,14,0)))
                result=p.plan(32,7)
                self.assertEqual(result['totalWeight'],4)
                run=p.run
            finally:p.close()
            q=BinaryPlanner(tmp,data,maximum=64,edge_depth=0,node_limit=0)
            try:
                repeated=q.plan(32,7)
                self.assertEqual(repeated['totalWeight'],4)
                self.assertEqual(repeated['nodesThisRun'],0)
            finally:q.close()
            data=snapshot({'5:16:single':6,'5:16:match':2})
            q=BinaryPlanner(tmp,data,maximum=64,edge_depth=0,node_limit=0)
            try:
                changed=q.plan(32,7)
                self.assertEqual(changed['totalWeight'],8)
                self.assertNotEqual(run,q.run)
            finally:q.close()

    def test_paused_search_does_not_claim_minimum(self):
        data=snapshot({'5:16:single':3,'5:16:match':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=64,edge_depth=0,node_limit=1)
            try:
                result=p.plan(64,7)
                self.assertEqual(result['status'],'paused')
                self.assertFalse(result['minimumAdditiveWeightProvenInScope'])
                self.assertFalse(result['globallyOptimal'])
            finally:p.close()

    def test_export_prices_the_current_children_not_stale_incumbent(self):
        data=snapshot({'5:16:single':3,'5:16:match':1})
        with tempfile.TemporaryDirectory() as tmp:
            p=BinaryPlanner(tmp,data,maximum=64,edge_depth=0,node_limit=0)
            try:
                answer=p.solve(('single',7,32,0))
                answer={**answer,'cost':'999'}
                self.assertEqual(Fraction(p.export(answer)['cost']),4)
            finally:p.close()


if __name__=='__main__':unittest.main()
