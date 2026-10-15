import unittest
from automation.route_variants import matching

class MatchEdgeGuardIdentityTests(unittest.TestCase):
    def test_unguarded_match_cannot_satisfy_guarded_requirement(self):
        base=dict(target=32,exit='match',maxValue=64,bases=[1,3,5,15],maxGoalCells=5,successNoExtraCombos=True)
        self.assertFalse(matching(base,{**base,'matchEdgeGuard':True}))
        self.assertTrue(matching({**base,'matchEdgeGuard':True},{**base,'matchEdgeGuard':True}))
        self.assertTrue(matching(base,base))

    def test_guarded_match_cannot_satisfy_legacy_requirement(self):
        base=dict(target=48,exit='match',maxValue=48,bases=[1,3,5,15],maxGoalCells=5)
        self.assertFalse(matching({**base,'matchEdgeGuard':True},base))

if __name__=='__main__':unittest.main()
