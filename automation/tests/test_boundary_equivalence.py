import unittest
from automation import game
from automation.route_runtime import RouteExecutor
from automation.runtime import IncompatibleState


class BoundaryEquivalenceTests(unittest.TestCase):
    def run_entry(self,anchor,minimum=70):
        seen=[]
        class Worker:
            def __init__(self,item):pass
            def close(self):pass
            def query(self,active,*args):
                seen.append([t['value'] for t in active])
                return {'status':'ok','success':True,'score':1,'post':0,'ops':[
                    {'kind':'group','l':1,'r':2,'board':{'fpos':0,
                     'blocks':[{'value':32,'span':1,'combo':False}]}}]}
        prefix=[[anchor,1,False]]
        policy={'id':'p','cells':5,'target':32,'exit':'single','maxValue':64,
                'singleProtectedValue':80,'singleProtectedHead':8,
                'equivalentProtectedMinimum':minimum,'singleEdgeGuard':True,
                'successNoExtraCombos':True,'singleTidyExit':True}
        route={'version':2,'kind':'stages','cells':10,'target':32,'initialPrefix':prefix,
               'minimumTemplateTarget':24,'steps':[{'kind':'leaf','policy':'p',
               'target':32,'exit':'single','policyCells':5,'template':'5:32:single',
               'before':prefix,'after':prefix+[[32,1,False]]}]}
        state=game.new_game(42,10)
        state['tower']=[game.tile(state,v) for v in (anchor,16,6,10)]
        executor=RouteExecutor(route,{'policies':[policy]},Worker)
        try:
            action=executor.next_action(game.observation(state))
            after=game.apply(state,action)
            executor.accept(game.observation(state),action,game.observation(after))
            self.assertEqual(seen,[[16,6,10]])
            self.assertEqual(game.signature(after),[(anchor,1,'tile'),(32,1,'tile')])
            self.assertEqual(after['rngState'],state['rngState'])
            self.assertEqual(after['queue'],state['queue'])
        finally:executor.close()

    def test_large_anchor_transfer_preserves_the_real_protected_block(self):
        self.run_entry(240)

    def test_in_model_decimal_head_cannot_be_transferred(self):
        with self.assertRaises(IncompatibleState):self.run_entry(64)

    def test_insufficient_declared_bound_cannot_bypass_the_guard(self):
        with self.assertRaises(IncompatibleState):self.run_entry(240,50)
