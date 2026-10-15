import unittest
from unittest.mock import Mock
from automation import game
from automation.runtime import Executor, IncompatibleState
from automation.route_runtime import StageExecutor


class RealBoardAlternativeTests(unittest.TestCase):
    def fixture(self,post):
        executor=Executor.__new__(Executor)
        executor.route={'towerLimit':10}
        executor.failure_reason=None;executor.real_board_query=post
        executor.real_board_excluded={};executor.queue=[];executor.macro_board=None
        executor.finish_after_queue=False;executor.free_seen=set();executor.stage=0
        return executor,game.observation(game.new_game(7,10))

    def test_rejected_virtual_success_requeries_before_any_action(self):
        executor,obs=self.fixture(('state',0))
        executor._next_action=Mock(side_effect=[IncompatibleState('Missing ordinary exit'),{'kind':'drop'}])
        self.assertEqual(executor.next_action(obs),{'kind':'drop'})
        self.assertEqual(executor.real_board_excluded,{'state':[0]})
        self.assertEqual(executor._next_action.call_count,2)
        self.assertIsNone(executor.failure_reason)

    def test_legacy_model_divergence_keeps_its_error(self):
        executor,obs=self.fixture(None)
        executor._next_action=Mock(side_effect=IncompatibleState('Missing ordinary exit'))
        with self.assertRaisesRegex(IncompatibleState,'Missing ordinary exit'):
            executor.next_action(obs)

    def test_edge_cascade_cannot_execute_a_wrong_match_exit(self):
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):
                return {'status':'ok','success':True,'ops':[{'kind':'edge',
                    'board':{'fpos':0,'blocks':[{'value':64,'span':1,'combo':False}]}}]}
            def close(self):pass
        state=game.new_game(13,10)
        state['tower']=[game.tile(state,v) for v in (5120,64,320)]
        state['tower'].append(game.tile(state,320,kind='group',physicalCount=2))
        leaf={'kind':'leaf','target':64,'exit':'match','policy':'match','policyCells':5,
              'before':[[5120,1,False],[64,1,False]],'after':[[5120,1,False],[128,1,False]]}
        executor=StageExecutor({'kind':'stage','target':-1,'towerLimit':10,'children':[leaf]},
            {'policies':[{'id':'match','target':64,'exit':'match','cells':5,'maxValue':640}]},Worker)
        executor.fixed_ids={t['id'] for t in state['tower'][:2]}
        obs=game.observation(state)
        self.assertEqual(executor.next_action(obs),{'kind':'drop'})
        self.assertEqual(executor.failure_reason,'fixed-policy-exit-rejected')
        self.assertEqual(state['tower'][1]['value'],64)
        executor.close()


if __name__=='__main__':unittest.main()
