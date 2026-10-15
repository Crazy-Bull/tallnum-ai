import json
from pathlib import Path
import unittest

from automation.probability_route_planner import plan_route, usable_policies, boundary_fits
from automation.binary_routes import BinaryPlanner, verify_tree, encode_memo, decode_memo


ROOT=Path(__file__).resolve().parents[2]
CATALOG=json.loads((ROOT/'desktop/peak13-assets/probability-catalog.json').read_text(encoding='utf-8'))
OUT=ROOT/'automation/runs/test-probability-route-planner'


class ProbabilityRoutePlannerTests(unittest.TestCase):
    def test_generic_planner_runs_execution_binding_before_reporting_counts(self):
        from unittest.mock import patch
        from automation.probability_route_execution import improve_execution
        folder=OUT/'automatic-execution-binding'
        with patch('automation.probability_route_planner.improve_execution',wraps=improve_execution) as binding:
            result=plan_route(80,6,CATALOG,folder,node_limit=1000)
        binding.assert_called_once()
        route=json.loads((folder/'route.json').read_text())
        self.assertEqual(result['steps'],len(route['steps']))
        self.assertEqual(result['executionContractVersion'],route['executionContractVersion'])

    def test_equal_peak_cost_uses_available_larger_workspace(self):
        snapshot={'entries':{'5:32:single':{'weightExact':'1','policyId':None},
                             '6:32:single':{'weightExact':'1','policyId':None},
                             '5:64:single':{'weightExact':'1','policyId':None}}}
        p=BinaryPlanner(OUT/'spare-capacity-tie-v4',snapshot,maximum=128,minimum_leaf_target=24,
                        maximum_leaf_target=64,objective='five-peak-count')
        try:
            self.assertEqual(p.leaf(('single',6,32,0))['template'],'6:32:single')
            self.assertEqual(p.leaf(('single',5,32,0))['template'],'5:32:single')
        finally:p.close()

    def test_compressed_dp_memo_preserves_values_and_reads_legacy_json(self):
        value={'task':['single',7,1408,5],'cost':'41','profile':[0,3],
               'children':['a','b'],'complete':False}
        self.assertEqual(decode_memo(bytes(encode_memo(value))),value)
        self.assertEqual(decode_memo(json.dumps(value)),value)

    def test_five_peak_objective_ignores_other_capacities(self):
        snapshot={'entries':{'5:64:single':{'weightExact':'1','policyId':None},
                             '6:48:single':{'weightExact':'1','policyId':None}}}
        p=BinaryPlanner(OUT/'score-five-peak',snapshot,maximum=128,minimum_leaf_target=24,
                        maximum_leaf_target=64,objective='five-peak-count')
        try:
            self.assertLess(p.score({'profile':[20,0],'cost':'20'}),p.score({'profile':[0,1],'cost':'1'}))
            self.assertLess(p.score({'profile':[10,1],'cost':'11'}),p.score({'profile':[0,2],'cost':'2'}))
        finally:p.close()

    def test_equivalent_boundary_uses_the_existing_runtime_contract(self):
        p=next(p for p in CATALOG['policies'] if p.get('warmStartOrdinary')==18)
        self.assertTrue(boundary_fits(p,[[6144,1,False]]))
        self.assertFalse(boundary_fits(p,[[48,1,False]]))
        self.assertFalse(boundary_fits(p,[]))

    def test_template_boundary_is_checked_on_the_full_board(self):
        leaf={'task':['single',5,30,5],'rule':'template-policy','template':'5:30:single',
              'declaredNonstandard':True,'children':[],'allowedBoundaries':[40,60,80]}
        from automation.route_search import Block
        self.assertEqual(verify_tree(leaf,10,(Block(60),))['finalBoard'],[[60,1,False],[30,1,False]])
        with self.assertRaises(ValueError):verify_tree(leaf,10,(Block(64),))

    def test_declared_nonstandard_base_multiples_are_dp_candidates(self):
        snapshot={'entries':{'5:32:single':{'weightExact':'1','policyId':None},
                             '6:44:single':{'weightExact':'1','policyId':None,'declaredNonstandard':True}}}
        p=BinaryPlanner(OUT/'nonstandard-dp-candidates',snapshot,maximum=2048,
                        minimum_leaf_target=24,maximum_leaf_target=44,objective='five-peak-count')
        try:
            self.assertIn(1408,p.candidates(1400,1420))
            self.assertIn(704,p.candidates(700,710))
        finally:p.close()

    def test_explicit_known_warm_contract_keeps_its_entry_requirement(self):
        result=plan_route(36,6,CATALOG,OUT/'explicit-warm-entry',
                          allowed_templates=['6:36:single'],node_limit=100)
        self.assertEqual(result['status'],'catalog-gap')
        self.assertFalse((OUT/'explicit-warm-entry/route.json').exists())

    def test_direct_catalog_leaf_for_five_and_255_cells(self):
        for cells in (5,255):
            with self.subTest(cells=cells):
                folder=OUT/f'{cells}-40'
                result=plan_route(40,cells,CATALOG,folder,node_limit=100)
                route=json.loads((folder/'route.json').read_text(encoding='utf-8'))
                self.assertEqual(result['status'],'candidate')
                self.assertEqual(route['steps'][-1]['after'],[[40,1,False]])
                self.assertEqual(result['leafCounts'],{f'{5 if cells==5 else 6}:40:single':1})
                self.assertFalse(result['randomExecutionVerified'])

    def test_equal_merge_uses_real_single_probability_table(self):
        folder=OUT/'6-80'
        result=plan_route(80,6,CATALOG,folder,node_limit=1000)
        route=json.loads((folder/'route.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['leafCounts'],{'6:40:single':1,'5:40:single':1})
        self.assertTrue(result['lexicographicOrderProvenInScope'])
        self.assertEqual(route['steps'][-1]['after'],[[80,1,False]])
        self.assertTrue(all(s['policy'] for s in route['steps']))
        self.assertEqual(route['steps'][-1]['singleConnectionAfter'],[[80,1,False]])

    def test_selected_templates_are_the_only_leaf_contracts(self):
        folder=OUT/'selected-6-80'
        result=plan_route(80,6,CATALOG,folder,allowed_templates=['5:40:single'],node_limit=1000)
        route=json.loads((folder/'route.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['scope']['allowedFiveCellTemplates'],['5:40:single'])
        self.assertEqual(result['leafCounts'],{'5:40:single':2})
        self.assertTrue(all(step['template']=='5:40:single' for step in route['steps'] if step['kind']=='leaf'))

    def test_structural_plan_without_catalog_reports_missing_table(self):
        folder=OUT/'selected-5-54'
        result=plan_route(54,5,None,folder,allowed_templates=['5:54:single'],node_limit=100)
        route=json.loads((folder/'structural-route.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'],'missing-probability-tables')
        self.assertEqual(result['missingProbabilityTables'],['5:54:single'])
        self.assertEqual(route['steps'][0]['policy'],None)
        self.assertFalse((folder/'route.json').exists())

    def test_six_cell_catalog_policy_binds_exact_specification(self):
        folder=OUT/'selected-6-40'
        result=plan_route(40,6,CATALOG,folder,allowed_templates=['6:40:single'],node_limit=100)
        route=json.loads((folder/'route.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['leafCounts'],{'6:40:single':1})
        self.assertEqual(result['highestTemplate'],'6:40:single')
        self.assertEqual(route['steps'][0]['policyCells'],6)
        self.assertIsNotNone(route['steps'][0]['policy'])

    def test_avoiding_five_cell_templates_has_priority_when_both_are_allowed(self):
        folder=OUT/'selected-mixed-40'
        result=plan_route(40,6,CATALOG,folder,
                          allowed_templates=['5:40:single','6:40:single'],node_limit=100)
        self.assertEqual(result['status'],'candidate')
        self.assertEqual(result['leafCounts'],{'6:40:single':1})

    def test_arbitrary_seven_cell_contract_remains_structural_without_table(self):
        folder=OUT/'selected-7-96'
        result=plan_route(96,7,None,folder,allowed_templates=['7:96:single'],node_limit=100)
        route=json.loads((folder/'structural-route.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'],'missing-probability-tables')
        self.assertEqual(result['missingProbabilityTables'],['7:96:single'])
        self.assertEqual(route['steps'][0]['policyCells'],7)
        self.assertFalse((folder/'route.json').exists())

    def test_seven_cell_contract_reserves_workspace_for_second_call(self):
        folder=OUT/'selected-8-192'
        result=plan_route(192,8,None,folder,allowed_templates=['7:96:single'],node_limit=1000)
        route=json.loads((folder/'structural-route.json').read_text(encoding='utf-8'))
        self.assertEqual(result['leafCounts'],{'7:96:single':2})
        self.assertEqual(route['steps'][-1]['after'],[[192,1,False]])
        self.assertTrue(all(step['policyCells']==7 for step in route['steps'] if step['kind']=='leaf'))

    def test_ten_cell_contract_is_accepted_as_structural_declaration(self):
        folder=OUT/'selected-10-10240'
        result=plan_route(10240,10,None,folder,
                          allowed_templates=['10:10240:single'],node_limit=100)
        self.assertEqual(result['missingProbabilityTables'],['10:10240:single'])
        self.assertEqual(result['leafCounts'],{'10:10240:single':1})

    def test_five_cell_target_above_64_is_allowed_in_generic_planner(self):
        folder=OUT/'selected-5-80'
        result=plan_route(80,5,None,folder,allowed_templates=['5:80:single'],node_limit=100)
        route=json.loads((folder/'structural-route.json').read_text(encoding='utf-8'))
        self.assertEqual(result['status'],'missing-probability-tables')
        self.assertEqual(result['missingProbabilityTables'],['5:80:single'])
        self.assertEqual(result['scope']['maximumFiveCellTarget'],80)
        self.assertEqual(route['steps'][0]['template'],'5:80:single')
        self.assertFalse((folder/'route.json').exists())

    def test_catalog_selection_does_not_filter_five_cell_80(self):
        declaration={'id':'example-five-80','cells':5,'target':80,'exit':'single',
                     'pendingValue':'pending-table.bin','disableStaticFallback':True}
        self.assertIn((5,80,'single'),usable_policies({'policies':[declaration]}))

    def test_invalid_allowed_template_is_rejected(self):
        for key in ('4:40:single','5:6:match','5:40:unknown','256:96:single'):
            with self.subTest(key=key),self.assertRaises(ValueError):
                plan_route(40,5,CATALOG,OUT/'invalid',allowed_templates=[key])

    def test_impossible_and_missing_catalog_are_explicit(self):
        for target,cells,status in ((2,1,'direct-draw-target'),
                                    (64,4,'impossible-under-template-rules'),
                                    (81,10,'impossible-ordinary-target'),
                                    (12360,10,'catalog-gap'),
                                    (54,7,'catalog-gap')):
            with self.subTest(target=target,cells=cells):
                folder=OUT/f'{cells}-{target}'
                result=plan_route(target,cells,CATALOG,folder,node_limit=1000)
                self.assertEqual(result['status'],status)
                if target==54:self.assertEqual(result['missingProbabilityTables'],['5:54:single'])
                if target==12360:self.assertEqual(result['missingProbabilityTables'],[])
                self.assertFalse((folder/'route.json').exists())


if __name__=='__main__':unittest.main()
