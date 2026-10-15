import json
from pathlib import Path
import unittest

from automation.probability_route_execution import configure_recovery, improve_execution
from automation.probability_route_planner import boundary_fits, usable_policies, validate_bound_route


ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / 'desktop/peak13-assets/probability-catalog.json').read_text())


class ProbabilityRouteExecutionTests(unittest.TestCase):
    def route(self):
        return json.loads((ROOT / 'automation/tests/fixtures/generic-plans/five-peak-dp-v20/10-10240/'
                          'validation-100/executed-route.json').read_text())

    def test_buffers_are_distinct_same_head_and_keyed_by_anchor(self):
        route = configure_recovery(self.route(), CATALOG)
        policies = {p['id']: p for p in CATALOG['policies']}
        self.assertIn('32', route['bufferRescuePolicies'])
        self.assertEqual([policies[i]['target'] for i in route['bufferRescuePolicies']['32']], [30])
        self.assertEqual([policies[i]['target'] for i in route['bufferRescuePolicies']['64']], [60])
        for anchor, ids in route['bufferRescuePolicies'].items():
            for ident in ids:
                self.assertNotEqual(int(anchor), policies[ident]['target'])
                self.assertEqual(int(anchor) // 10, policies[ident]['target'] // 10)
                self.assertLessEqual(policies[ident]['target'], 64)
        self.assertTrue(route['singleBoundaryBufferRescue'])
        self.assertTrue(route['extendedBoundaryBufferRescue'])
        self.assertTrue(route['realBoundaryRewind'])

    def test_explicit_exclusion_preserves_an_empty_rescue_mapping(self):
        route = configure_recovery(self.route(), CATALOG, allowed_buffers=set())
        self.assertEqual(route['bufferRescuePolicies'], {})

    def test_upgrade_checks_capacity_and_allowed_contracts_and_retains_peak(self):
        source = self.route()
        selected = set(usable_policies(CATALOG))
        route = improve_execution(source, CATALOG, selected, boundary_fits)
        validate_bound_route(route, CATALOG, selected)
        leaves = [s for s in route['steps'] if s['kind'] == 'leaf']
        self.assertEqual(sum(s['policyCells'] == 5 and s['target'] == 64 for s in leaves), 14)
        self.assertEqual(max(s['target'] for s in leaves if s['policyCells'] == 5), 64)
        self.assertTrue(any(s['policyCells'] == 6 and s['target'] == 48 for s in leaves))
        for s in leaves:
            self.assertLessEqual(sum(b[1] for b in s['before']) + s['policyCells'], 10)
        self.assertEqual([s.get('target') for s in route['steps'][:7]], [32, 32, 32, 32, 40, 40, 40])
        self.assertEqual(route['steps'][8]['after'], [[24, 1, False]])
        self.assertEqual(route['steps'][9]['before'], [])
        self.assertEqual(route['steps'][9]['after'], source['steps'][0]['after'])
        self.assertEqual(route['releaseAtStage'], 9)
        self.assertEqual(route['steps'][-1]['after'], [[10240, 1, False]])
        self.assertEqual(source, self.route())

    def test_no_upgrade_or_opening_adds_an_excluded_template(self):
        source = self.route()
        selected = {(s['policyCells'], s['target'], s['exit']) for s in source['steps']
                    if s['kind'] == 'leaf' and s['policyCells'] == 5}
        route = improve_execution(source, CATALOG, selected, boundary_fits)
        self.assertEqual(route['steps'], source['steps'])
        self.assertNotIn('releaseAtStage', route)

    def test_single_connection_is_verified_after_match_upgrade(self):
        route = improve_execution(self.route(), CATALOG, set(usable_policies(CATALOG)),
                                  boundary_fits, opening=False)
        stage = next(s for s in route['steps'] if s.get('before') == [[160, 1, False], [32, 1, False]])
        self.assertEqual(stage['template'], '6:32:single')
        self.assertEqual(stage['singleConnectionAfter'], stage['after'])

    def test_three_recorded_candidates_keep_the_required_structural_limits(self):
        routes = {}
        for target in (8192, 10240, 12288):
            source = json.loads((ROOT / f'automation/tests/fixtures/generic-plans/five-peak-dp-release/10-{target}/route.json').read_text())
            route = improve_execution(source, CATALOG, set(usable_policies(CATALOG)), boundary_fits)
            validate_bound_route(route, CATALOG, set(usable_policies(CATALOG)))
            routes[target] = route
        leaves = [s for s in routes[10240]['steps'] if s['kind'] == 'leaf' and s['policyCells'] == 5]
        self.assertEqual(max(s['target'] for s in leaves), 64)
        self.assertLessEqual(sum(s['target'] == 64 for s in leaves), 14)
        self.assertEqual(max(s['target'] for s in routes[12288]['steps']
                             if s['kind'] == 'leaf' and s['policyCells'] == 5), 80)
        self.assertLessEqual(len(routes[8192]['steps']), len(routes[10240]['steps']))

    def test_local_dp_removes_spare_space_64_and_stalled_60_counter_contracts(self):
        source = json.loads((ROOT / 'automation/tests/fixtures/generic-plans/five-peak-dp-release/10-12288/route.json').read_text())
        selected = set(usable_policies(CATALOG))
        route = improve_execution(source, CATALOG, selected, boundary_fits)
        validate_bound_route(route, CATALOG, selected)
        self.assertLessEqual(sum(s['kind']=='leaf' and s['policyCells']==5 and s['target']==64
                                 for s in route['steps']), 12)
        self.assertEqual(sum(s['kind']=='leaf' and s['policyCells']==5 and s['target']==80
                             for s in route['steps']), 10)
        self.assertFalse(any(s['kind']=='leaf' and s['target']==60 and s['before']==
                            [[6144,1,False],[4096,1,False],[704,1,False],[120,1,False],[60,1,False]]
                             for s in route['steps']))
        self.assertTrue(any(a['after']==[[6144,1,False],[4096,1,False],[704,1,False],[240,1,False]]
                            for a in route['executionExpansions']))
        self.assertEqual(route['startupContract'],'128-three-six40-edge24-six48-probability-only')
        self.assertEqual(route['steps'][9]['target'],48)
        self.assertEqual(route['steps'][9]['after'],source['steps'][0]['after'])

    def test_48_startup_requires_all_selected_producers(self):
        source=json.loads((ROOT/'automation/tests/fixtures/generic-plans/five-peak-dp-release/10-12288/route.json').read_text())
        selected=set(usable_policies(CATALOG))-{(6,40,'single')}
        route=improve_execution(source,CATALOG,selected,boundary_fits)
        self.assertNotIn('startupContract',route)
        self.assertFalse(any(s['kind']=='leaf' and s['template']=='6:40:single' for s in route['steps']))

    def test_8192_keeps_the_exact_measured_route(self):
        source=json.loads((ROOT/'automation/tests/fixtures/generic-plans/five-peak-dp-release/10-8192/route.json').read_text())
        route=improve_execution(source,CATALOG,set(usable_policies(CATALOG)),boundary_fits)
        configure_recovery(route,CATALOG)
        self.assertEqual(route,json.loads((ROOT/'automation/tests/fixtures/generic-plans/execution-fix-v6/10-8192/route.json').read_text()))

    def test_10240_keeps_the_exact_previously_measured_route(self):
        from automation.common import fingerprint
        from tempfile import TemporaryDirectory
        from automation.common import atomic_json
        source = json.loads((ROOT / 'automation/tests/fixtures/generic-plans/five-peak-dp-release/10-10240/route.json').read_text())
        route = improve_execution(source, CATALOG, set(usable_policies(CATALOG)), boundary_fits)
        configure_recovery(route, CATALOG)
        temporary_root = ROOT/'automation/runs/test-probability-route-planner'
        temporary_root.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=temporary_root) as tmp:
            path=Path(tmp)/'route.json'
            atomic_json(path, route)
            self.assertEqual(fingerprint(path), fingerprint(ROOT/'automation/tests/fixtures/generic-plans/execution-fix-v1/10-10240/route.json'))


if __name__ == '__main__':
    unittest.main()
