import itertools
import unittest
from automation.planner import Metrics
from automation.optimize_route_variants import select_sequence


class RouteVariantSelectionTests(unittest.TestCase):
    def test_matches_exhaustive_whole_route_restart_cost(self):
        choices=[[(str(i)+':'+str(j),Metrics(p,c*p,c*(1-p)))
                  for j,(p,c) in enumerate(group)]
                 for i,group in enumerate([[(.99,8),(.6,2)],[(.9,4),(.4,1)],[(.8,5),(.5,2)]])]
        selected,_=select_sequence(choices)
        def score(combination):
            m=Metrics(1,0,0)
            for _,n in combination:m=m.then(n)
            return m.expected
        self.assertAlmostEqual(selected['metrics'].expected,min(map(score,itertools.product(*choices))))

    def test_whole_route_can_prefer_less_aggressive_than_local_retry_minimum(self):
        # The downstream choice must account for replaying the expensive prefix.
        choices=[[('prefix',Metrics(1,100,0))],
                 [('safe',Metrics(.99,9.9,.1)),('fast',Metrics(.1,.1,.9))]]
        selected,_=select_sequence(choices)
        self.assertEqual(selected['policies'],['prefix','safe'])

    def test_repeated_contracts_can_use_different_variants(self):
        variants=[('safe',Metrics(.99,9.9,.1)),('fast',Metrics(.1,.1,.9))]
        selected,_=select_sequence([variants,variants])
        self.assertEqual(selected['policies'],['fast','safe'])

    def test_missing_stage_is_an_error(self):
        with self.assertRaises(ValueError):select_sequence([[]])
