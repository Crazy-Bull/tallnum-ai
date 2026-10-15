from copy import deepcopy
import unittest

from automation import game
from automation.bootstrap10240 import actions, search_action, OpeningController


class BootstrapTests(unittest.TestCase):
    def test_actual_unlocks_and_known_queue_are_preserved(self):
        state = game.new_game(123,10)
        state['tower'] = [game.tile(state,v) for v in (64,32)]
        state['queue'] = [4,8,15,15]
        state['unlocked'] = [2,4,8,6]
        predicted = game.predict(game.observation(state), {'kind':'drop'})
        self.assertIn(10,predicted['unlocked'])
        self.assertEqual(predicted['queue'],[8,None])
        self.assertEqual(game.signature(state),[(64,1,'tile'),(32,1,'tile')])

    def test_hidden_queue_and_rng_do_not_change_decision(self):
        state = game.new_game(1,10)
        other = deepcopy(state)
        other['queue'][2:] = [15,15]
        other['rngState'] = 123456
        self.assertEqual(search_action(game.observation(state)), search_action(game.observation(other)))

    def test_safe_search_does_not_continue_full_tower(self):
        state = game.new_game(1,10)
        state['tower'] = [game.tile(state,v) for v in (2,4,8,6,2,4,8,6,2)]
        action = search_action(game.observation(state))
        if any(not game.predict(game.observation(state),a)['gameOver'] for a in actions(game.observation(state))):
            self.assertFalse(game.predict(game.observation(state),action)['gameOver'])

    def test_six_proposal_failure_falls_back_and_requires_real_join(self):
        class Worker:
            def __init__(self,item):pass
            def close(self):pass
            def query(self,*args):return {'status':'dead'}
        policies = [{'id':str(t),'cells':6,'target':t,'exit':'single','maxValue':48,'maxGoalCells':1}
                    for t in (32,40,48)]
        next_item = {'id':'next','cells':5,'maxValue':48}
        continuation = {'steps':[{'kind':'leaf','policy':'next'}]}
        controller = OpeningController({'policies':policies},continuation,{'policies':[next_item]},Worker)
        state = game.new_game(1,10)
        self.assertIsNotNone(controller.next_action(game.observation(state)))
        self.assertEqual(controller.counts['search'],1)
        state['tower'] = [game.tile(state,v) for v in (320,64)]
        state['unlocked'] = game.POOL[:]
        self.assertFalse(controller.can_join(game.observation(state)))
        state['tower'][1]['value'] = 8
        self.assertTrue(controller.can_join(game.observation(state)))
        controller.close()
