import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from automation.integer_planner import plan_route

class IntegerPlannerTests(unittest.TestCase):
    def test_nonstandard_target_and_lowest_ceiling_proof(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            result=plan_route(18,7,tmp,maximum=1024,ceiling=64,nodes=3000,focus_nodes=3000)
            self.assertEqual(result['status'],'proven')
            self.assertEqual(result['upperBound'],result['lowerBound'])
            self.assertTrue(result['peakProven'])
            self.assertTrue(all(s.get('policyCells',5)==5 for s in result['steps']))
            self.assertTrue(all(s['target']>=24 for s in result['steps'] if s['kind']=='leaf'))
            self.assertEqual(result['scope']['minimumTemplateTarget'],24)
            self.assertEqual(result['steps'][-1]['after'],[[18,1,False]])
            self.assertFalse(result['randomExecutionVerified'])
            self.assertEqual(json.loads((Path(tmp)/'integer-result.json').read_text())['target'],18)
            plan=json.loads((Path(tmp)/'binary-plan.json').read_text())
            self.assertEqual(plan['config']['minimumLeafTarget'],24)
            from automation.peak_count_bound import RelaxedPeakBound,INF
            bound=RelaxedPeakBound(plan)
            self.assertEqual(bound.leaf(6),INF)
            self.assertEqual(bound.leaf(16),INF)

    def test_budget_exhaustion_is_not_no_route(self):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            (Path(tmp)/'integer-result.json').write_text('{"stale":true}')
            result=plan_route(10240,10,tmp,maximum=20480,nodes=1,focus_nodes=1)
            self.assertEqual(result['status'],'incomplete')
            self.assertFalse(result['countProven'])
            self.assertIsNone(result['upperBound'])
            self.assertNotIn('stale',json.loads((Path(tmp)/'integer-result.json').read_text()))

    def test_invalid_target_and_ceiling_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for target in (1,3,65536):
                with self.assertRaises(ValueError):plan_route(target,10,tmp)
            with self.assertRaises(ValueError):plan_route(54,7,tmp,ceiling=34)
            with self.assertRaises(ValueError):plan_route(54,7,tmp,ceiling=16)

if __name__=='__main__':unittest.main()
