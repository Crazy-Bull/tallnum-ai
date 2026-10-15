import tempfile
import unittest

from automation.route_search import RouteSearch, template_alphas
from automation.route_variants import manifest


class SmallGoalAlphasTests(unittest.TestCase):
    def test_threshold_includes_all_exit_kinds(self):
        self.assertEqual(template_alphas(47), [0])
        self.assertEqual(template_alphas(48), [0, .001, .005, .01, .05])
        with tempfile.TemporaryDirectory() as tmp:
            with RouteSearch(tmp, {'policies': []}, target=640, local_template_bounds=True) as search:
                for kind in ('single', 'match', 'extend', 'buffer'):
                    self.assertEqual(search.requirement(32, kind)['aggressiveness'], [0])
                    self.assertEqual(len(search.requirement(48, kind)['aggressiveness']), 5)

    def test_stale_manifest_and_catalog_exclude_small_risk_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            with RouteSearch(tmp, {'policies': []}, target=640, local_template_bounds=True) as search:
                req = search.requirement(32, 'single')
                req['aggressiveness'] = [0, .001, .005, .01, .05]
                policies = [{**req, 'id': str(alpha), 'variantAggressiveness': alpha,
                             'policy': 'fake.bin', 'policySha256': 'fake',
                             'exitSemantics': 'success-board-v2',
                             'petsc': {'verified': True, 'exitEvaluationRounds': 2},
                             'statistics': {'usable': True, 'p': .9, 'u': 2, 'v': 1}}
                            for alpha in (0, .05)]
                search.catalog = {'policies': policies}
                report = manifest(tmp, req, search.catalog)
                self.assertTrue(report['complete'])
                self.assertEqual(report['requirement']['aggressiveness'], [0])
                self.assertEqual([p['id'] for p in report['variants']], ['0'])
                self.assertEqual([p['id'] for p in search.available(req)], ['0'])
