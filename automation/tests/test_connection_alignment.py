import unittest
from automation import game
from automation.route_runtime import RouteExecutor


class ConnectionAlignmentTests(unittest.TestCase):
    def fixture(self,residual=10):
        state=game.new_game(42,10)
        state['tower']=[game.tile(state,4096),game.tile(state,96),
                        game.tile(state,94,kind='group',physicalCount=3),game.tile(state,residual)]
        state['queue']=[8,4,15,6]
        step={'kind':'edge','before':[[4096,1,False],[96,1,False],[94,3,True]],
              'after':[[4096,1,False],[18,1,False]]}
        executor=RouteExecutor({'version':2,'kind':'stages','cells':10,'target':8192,'steps':[step]},
                               {'policies':[]})
        executor.fixed_ids={t['id'] for t in state['tower'][:3]}
        return state,executor

    def test_real_rotation_preserves_prefix_then_restores_exact_edge_exit(self):
        state,executor=self.fixture()
        before=game.observation(state)
        action=executor.next_action(before)
        self.assertEqual(action,{'kind':'down'})
        self.assertIsNone(executor.failure_reason)
        after=game.apply(state,action);executor.accept(before,action,game.observation(after))
        self.assertEqual(executor.stage,0)
        self.assertEqual(after['drops'],state['drops']+1)
        edge=executor.next_action(game.observation(after))
        self.assertEqual(edge,{'kind':'edge'})
        result=game.apply(after,edge);executor.accept(game.observation(after),edge,game.observation(result))
        self.assertEqual(executor.stage,1)
        executor._contract(game.observation(result),executor.route['steps'][0]['after'])
        self.assertEqual(len(executor.connection_events),1)

    def test_safe_edge_needs_no_rotation(self):
        state,executor=self.fixture(4)
        self.assertEqual(executor.next_action(game.observation(state)),{'kind':'edge'})
        self.assertFalse(executor.connection_events)

    def test_no_rotation_when_draw_would_fill_tower(self):
        state,executor=self.fixture()
        state['towerLimit']=6;executor.route['cells']=6
        self.assertEqual(executor.next_action(game.observation(state)),{'kind':'drop'})
        self.assertEqual(executor.failure_reason,'stage-exit-contract-mismatch')
        self.assertFalse(executor.connection_events)


if __name__=='__main__':unittest.main()
