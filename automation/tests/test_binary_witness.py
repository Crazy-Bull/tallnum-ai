import tempfile
import unittest

from automation.binary_routes import BinaryPlanner
from automation.binary_witness import witness
from automation.tests.test_expected_routes import snapshot


class BinaryWitnessTests(unittest.TestCase):
    def test_real_opening_reaches_ten_with_permanent_pool_unlocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            planner=BinaryPlanner(tmp,snapshot({'5:10:single':5}),maximum=20,
                                  edge_depth=0,node_limit=0)
            try:plan=planner.plan(10,10)
            finally:planner.close()
        result=witness(plan)
        self.assertTrue(result['realOpeningAndUnlocksVerified'])
        self.assertFalse(result['stochasticPolicyVerified'])
        self.assertEqual(result['bootstrapTarget'],10)
        self.assertEqual(result['trace'][-1]['after'],[(10,1,'tile')])
        self.assertEqual(result['trace'][-1]['unlocked'],[2,4,8,6,10,15])
        self.assertLess(result['maximumPhysicalCells'],10)


if __name__=='__main__':unittest.main()
