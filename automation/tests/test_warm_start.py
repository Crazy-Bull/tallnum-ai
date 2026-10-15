from copy import deepcopy
import unittest
from automation import game
from automation.route_runtime import RouteExecutor


class WarmStartTests(unittest.TestCase):
    def test_release_preserves_block_rng_and_finishes_the_larger_goal(self):
        reply={'status':'ok','success':True,'post':0,'score':1,'ops':[
            {'kind':'group','l':1,'r':2,'board':{'fpos':0,'blocks':[{'value':36,'span':1,'combo':False}]}}]}
        seen=[]
        class Worker:
            def __init__(self,item):pass
            def query(self,active,gap,queue,*args):
                seen.append([t['value'] for t in active])
                return deepcopy(reply)
            def close(self):pass
        state=game.new_game(42,10)
        state['tower']=[game.tile(state,v) for v in (5120,18,8,10)]
        before=[[5120,1,False],[18,1,False]]
        prefix=[[5120,1,False]]
        route={'version':2,'kind':'stages','cells':10,'target':36,'initialPrefix':before,
               'minimumTemplateTarget':24,'steps':[
                   {'kind':'release','before':before,'after':prefix,'releaseIndices':[1],'warmStartOrdinary':18},
                   {'kind':'leaf','policy':'p','target':36,'policyCells':6,'template':'6:36:single',
                    'exit':'single','before':prefix,'after':prefix+[[36,1,False]],'warmStartOrdinary':18}]}
        policy={'id':'p','target':36,'exit':'single','cells':6,'maxValue':48,'singleTidyExit':True,
                'successNoExtraCombos':True,'warmStartOrdinary':18}
        executor=RouteExecutor(route,{'policies':[policy]},Worker)
        executor.bind_initial(game.observation(state))
        action=executor.next_action(game.observation(state))
        self.assertEqual(seen,[[18,8,10]])
        self.assertEqual(action,{'kind':'group','indices':[2,3]})
        after=game.apply(state,action)
        executor.accept(game.observation(state),action,game.observation(after))
        self.assertEqual(game.signature(after),[(5120,1,'tile'),(36,1,'tile')])
        self.assertEqual(state['queue'],after['queue'])
        self.assertEqual(state['rngState'],after['rngState'])
        self.assertEqual(state['drops'],after['drops'])
        self.assertIsNone(executor.next_action(game.observation(after)))
        executor.close()
