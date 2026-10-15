import unittest
from automation import game
from automation.opening128_40 import build,ContractExecutor


def catalog():
    return {'policies':[{'id':str(t),'target':t,'exit':'single','cells':6,'maxValue':48,
                        'maxGoalCells':1,'bootstrapPetsc':{'verified':True,'rounds':2}}
                       for t in (32,40)]}


class OpeningRouteTests(unittest.TestCase):
    def test_three40_calls_merge_to80_then_make_two_cell120(self):
        route,_=build(catalog())
        self.assertEqual([s['exit'] for s in route['steps'][4:7]],['single','match','single'])
        self.assertEqual(route['steps'][7]['after'],[[128,1,False],[120,2,True]])
        for step in route['steps']:
            if step['kind']=='leaf':self.assertLessEqual(sum(b[1] for b in step['before'])+6,10)
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (128,80,40)]
        state['unlocked']=game.POOL[:]
        state=game.apply(state,{'kind':'group','indices':[1,2]})
        self.assertEqual(game.signature(state),[(128,1,'tile'),(120,2,'group')])
        state=game.apply(state,{'kind':'edge'})
        self.assertEqual(game.signature(state),[(24,1,'tile')])
        self.assertIn(10,state['unlocked'])

    def test_intermediate40_is_not_the_final_goal(self):
        route,policies=build(catalog())
        self.assertEqual(route['target'],-1)
        self.assertEqual(route['completionContract'],[[40,1,False]])
        self.assertEqual(route['steps'][-1]['before'],[])
        self.assertEqual(route['releaseAtStage'],9)

    def test_single32_adapter_checks_cascade64_plus64_into128(self):
        from automation.route_runtime import StageExecutor
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):
                goal={'fpos':0,'blocks':[{'value':32,'span':1,'combo':False}]}
                return {'status':'ok','success':True,'board':goal,'ops':[{'kind':'drop','board':goal}]}
            def close(self):pass
        route,policies=build(catalog())
        leaf=route['steps'][3]
        runner=StageExecutor({'kind':'stage','target':-1,'towerLimit':10,'children':[leaf]},policies,Worker)
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (64,32,16)]
        state['queue']=[16,4,2,8]
        runner.fixed_ids={t['id'] for t in state['tower'][:2]}
        before=game.observation(state);action=runner.next_action(before)
        after=game.apply(state,action);runner.accept(before,action,game.observation(after))
        self.assertEqual(game.signature(after),[(128,1,'tile')])
        self.assertIsNone(runner.next_action(game.observation(after)))
        self.assertEqual(runner.fixed_ids,{after['tower'][0]['id']})
        runner.close()

    def test_ending_requires_both_protected_blocks_and_retains_residual(self):
        route,policies=build(catalog(),protect24=True)
        executor=ContractExecutor(route,policies)
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (24,40,8)]
        executor.stage=len(route['steps'])
        executor.fixed_ids={t['id'] for t in state['tower'][:2]}
        self.assertIsNone(executor.next_action(game.observation(state)))
        self.assertEqual(game.signature(state),[(24,1,'tile'),(40,1,'tile'),(8,1,'tile')])
        executor.close()

    def test_active24_releases_protection_without_modifying_board(self):
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):raise AssertionError('Existing ordinary40 should complete the leaf')
            def close(self):pass
        route,policies=build(catalog())
        executor=ContractExecutor(route,policies,Worker)
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (24,40,8)]
        executor.stage=9
        executor.fixed_ids={state['tower'][0]['id']}
        original=game.signature(state)
        self.assertIsNone(executor.next_action(game.observation(state)))
        self.assertEqual(executor.stage,10)
        self.assertEqual(executor.fixed_ids,{state['tower'][1]['id']})
        self.assertEqual(game.signature(state),original)
        executor.close()
