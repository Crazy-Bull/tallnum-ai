import tempfile
import unittest
from automation.binary_routes import BinaryPlanner,verify_tree


class DeclaredNonstandardTests(unittest.TestCase):
    def test_nonstandard_leaf_requires_explicit_declaration(self):
        entry={'weightExact':'1','policyId':'generated-34','declaredNonstandard':True}
        with tempfile.TemporaryDirectory() as tmp:
            planner=BinaryPlanner(tmp,{'entries':{'5:34:single':entry}},maximum=176,
                                  minimum_leaf_target=24,maximum_leaf_target=64,node_limit=1)
            try:
                result=planner.solve(('single',5,34,0))
                self.assertIsNotNone(result['cost'])
                leaf=planner.export(result)
                self.assertEqual(verify_tree(leaf,7)['finalBoard'],[[34,1,False]])
                planner.snapshot['entries']['5:34:single']={**entry,'declaredNonstandard':False}
                self.assertIsNone(planner.leaf(('single',5,34,0)))
            finally:planner.close()

    def test_declaration_does_not_bypass_capacity_or_target_floor(self):
        entry={'weightExact':'1','policyId':'generated-34','declaredNonstandard':True}
        with tempfile.TemporaryDirectory() as tmp:
            planner=BinaryPlanner(tmp,{'entries':{'5:34:single':entry}},maximum=176,
                                  minimum_leaf_target=24,maximum_leaf_target=64)
            try:
                self.assertIsNone(planner.leaf(('single',4,34,0)))
                self.assertIsNone(planner.leaf(('single',5,18,0)))
            finally:planner.close()


if __name__=='__main__':unittest.main()
