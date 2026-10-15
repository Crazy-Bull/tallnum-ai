import unittest
from automation import game
from automation.route_runtime import RouteExecutor


class BoundaryRewindTests(unittest.TestCase):
    def fixture(self):
        state=game.new_game(42,10)
        state['tower']=[game.tile(state,v) for v in (5120,68,18,16,20,2,4)]
        state['tower'].insert(0,game.tile(state,19,kind='group',physicalCount=2))
        prefix=[[5120,1,False],[68,1,False]]
        stage={'kind':'leaf','target':6,'exit':'single','policyCells':5,
               'before':prefix+[[18,1,False]],'after':prefix+[[18,1,False],[6,1,False]]}
        route={'version':2,'kind':'stages','target':10240,'cells':10,
               'singleBoundaryBufferRescue':True,'realBoundaryRewind':True,
               'bufferRescuePolicies':{'18':['unused']},
               'steps':[{'kind':'edge','before':prefix,'after':stage['before']},stage]}
        executor=RouteExecutor(route,{'policies':[]})
        executor.stage=1
        executor.fixed_ids={t['id'] for t in state['tower'][1:4]}
        return state,executor

    def test_recorded_entry_rewinds_anchor_without_draw_or_rng_change(self):
        state,executor=self.fixture()
        keep={t['id'] for t in state['tower'][1:3]}
        executor.inner=object()
        before=game.observation(state)
        self.assertTrue(executor._start_buffer_rescue(before,'five-cell-capacity'))
        self.assertIsNone(executor.inner)
        action=executor._next_buffer_rescue(before)
        self.assertEqual(action,{'kind':'edge'})
        after=game.apply(state,action)
        executor.accept(before,action,game.observation(after))
        self.assertEqual(executor.stage,0)
        self.assertEqual(executor.fixed_ids,keep)
        self.assertEqual(after['queue'],state['queue'])
        self.assertEqual(after['rngState'],state['rngState'])
        self.assertEqual(after['drops'],state['drops'])
        self.assertEqual(executor.buffer_rescue_events[0]['outcome'],'recovered')

    def test_rewind_rejects_edge_that_also_damages_earlier_anchor(self):
        state,executor=self.fixture()
        state['tower'][1]['value']=14
        state['tower'][2]['value']=16
        executor.route['steps'][0]['before'][0][0]=14
        executor.route['steps'][1]['before'][0][0]=14
        executor.route['steps'][0]['before'][1][0]=16
        executor.route['steps'][1]['before'][1][0]=16
        before=game.observation(state)
        self.assertFalse(executor._start_buffer_rescue(before,'five-cell-capacity'))
        self.assertIsNone(executor.buffer_rescue)

    def test_free_rewind_does_not_require_a_buffer_policy(self):
        state,executor=self.fixture()
        executor.route['bufferRescuePolicies']={}
        self.assertTrue(executor._start_buffer_rescue(game.observation(state),'five-cell-capacity'))
        self.assertEqual(executor.buffer_rescue['policy'],'real-boundary-edge')

    def test_extension_rewind_uses_real_anchor_instead_of_goal(self):
        state,executor=self.fixture()
        executor.route['extendedBoundaryBufferRescue']=True
        executor.route['steps'][1].update(exit='extend',target=64)
        self.assertTrue(executor._start_buffer_rescue(game.observation(state),'fixed-policy-dead'))
        self.assertEqual(executor.buffer_rescue['anchor'],state['tower'][3]['id'])

    def test_match_rewinds_ready_group_without_a_buffer_or_draw(self):
        state,executor=self.fixture()
        values=(6144,1024,480,384,48)
        state['tower']=[game.tile(state,6)]+[game.tile(state,v) for v in values]
        state['tower'] += [game.tile(state,45,kind='group',physicalCount=2),game.tile(state,2)]
        prefix=[[v,1,False] for v in values[:-1]]
        executor.route['steps'][0]['before']=prefix
        executor.route['steps'][1].update(target=48,exit='match',before=prefix+[[48,1,False]])
        executor.route['bufferRescuePolicies']={}
        executor.fixed_ids={t['id'] for t in state['tower'][1:6]}
        before=game.observation(state)
        self.assertTrue(executor._start_buffer_rescue(before,'fixed-policy-dead'))
        action=executor._next_buffer_rescue(before)
        after=game.apply(state,action)
        executor.accept(before,action,game.observation(after))
        self.assertEqual(executor.stage,0)
        self.assertEqual(after['rngState'],state['rngState'])
        self.assertEqual(after['queue'],state['queue'])
        self.assertEqual(len(executor.fixed_ids),4)


if __name__=='__main__':unittest.main()
