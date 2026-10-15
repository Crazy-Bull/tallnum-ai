import unittest
from automation import game
from automation.full10240 import bind40
from automation.route_runtime import RouteExecutor

class HandoffTests(unittest.TestCase):
    def test_real_residuals_and_rng_are_preserved(self):
        state=game.new_game(11,10)
        state['tower']=[game.tile(state,v) for v in (24,40,8)]
        original=repr(state)
        executor=RouteExecutor({'version':2,'kind':'stages','target':10240,'cells':10,
                               'initialPrefix':[[40,1,False]],'steps':[]},{'policies':[]})
        bind40(executor,game.observation(state))
        self.assertEqual(executor.fixed_ids,{state['tower'][1]['id']})
        self.assertEqual(repr(state),original)
        executor.close()
