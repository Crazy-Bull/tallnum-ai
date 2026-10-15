import unittest
from copy import deepcopy
from automation import game
from automation.route_runtime import RouteExecutor


class PhysicalExtensionTests(unittest.TestCase):
    def test_internal_match_first_forms_ordinary_extension_value(self):
        reply={'status':'ok','success':True,'post':0,'score':1,'ops':[
            {'kind':'group','l':1,'r':2,'board':{'fpos':0,'blocks':[{'value':64,'span':1,'combo':False}]}}]}
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):return deepcopy(reply)
            def close(self):pass
        state=game.new_game(42,10)
        state['tower']=[game.tile(state,v) for v in (5120,96,32,32,16,16)]
        before=[[5120,1,False],[96,1,False],[32,1,False]]
        after=[[5120,1,False],[192,1,False]]
        step={'kind':'leaf','policy':'p','policyCells':5,'target':64,'exit':'extend','before':before,'after':after}
        policy={'id':'p','target':64,'exit':'extend','cells':5,'maxValue':64,
                'extensionExit':True,'singleTidyExit':True,'successNoExtraCombos':True}
        executor=RouteExecutor({'version':2,'kind':'stages','target':192,'cells':10,
                                'initialPrefix':before,'steps':[step]},{'policies':[policy]},Worker)
        executor.bind_initial(game.observation(state))
        for expected in ({'kind':'group','indices':[4,5]},{'kind':'group','indices':[2,3]}):
            observation=game.observation(state)
            action=executor.next_action(observation)
            self.assertEqual(action,expected)
            result=game.apply(state,action)
            executor.accept(observation,action,game.observation(result))
            state=result
        self.assertEqual(game.signature(state),[(5120,1,'tile'),(192,1,'tile')])
        self.assertIsNone(executor.next_action(game.observation(state)))
        executor.close()

    def test_lower32_extension_connects64_and_merges_existing96(self):
        reply={'status':'ok','success':True,'post':0,'score':1,'ops':[
            {'kind':'group','l':0,'r':1,'board':{'fpos':0,'blocks':[{'value':32,'span':1,'combo':False}]}}]}
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):return deepcopy(reply)
            def close(self):pass
        state=game.new_game(42,10)
        state['tower']=[game.tile(state,v) for v in (5120,96,64,24,8)]
        before=[[5120,1,False],[96,1,False],[64,1,False]]
        after=[[5120,1,False],[192,1,False]]
        leaf={'kind':'leaf','policy':'test','policyCells':5,'target':32,'exit':'extend','before':before,'after':after}
        policy={'id':'test','target':32,'exit':'extend','cells':5,'maxValue':64,
                'extensionExit':True,'singleTidyExit':True,'successNoExtraCombos':True}
        executor=RouteExecutor({'version':2,'kind':'stages','target':192,'cells':10,
                                'initialPrefix':before,'steps':[leaf]}, {'policies':[policy]},Worker)
        observation=game.observation(state);executor.bind_initial(observation)
        action=executor.next_action(observation)
        self.assertEqual(action,{'kind':'group','indices':[2,3,4]})
        result=game.apply(state,action);executor.accept(observation,action,game.observation(result))
        self.assertEqual(game.signature(result),[(5120,1,'tile'),(192,1,'tile')])
        self.assertEqual(state['queue'],result['queue'])
        self.assertEqual(state['rngState'],result['rngState'])
        self.assertIsNone(executor.next_action(game.observation(result)))
        executor.close()

    def test_proxy_goal_compiles_one_group_with_real_anchor(self):
        reply={'status':'ok','success':True,'post':0,'score':1,'ops':[
            {'kind':'group','l':0,'r':1,'board':{'fpos':0,'blocks':[{'value':64,'span':1,'combo':False}]}}]}
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):return deepcopy(reply)
            def close(self):pass
        state=game.new_game(42,10)
        state['tower']=[game.tile(state,v) for v in (5120,96,32,48,16)]
        before=[[5120,1,False],[96,1,False],[32,1,False]]
        after=[[5120,1,False],[192,1,False]]
        leaf={'kind':'leaf','policy':'test','policyCells':5,'target':64,'exit':'extend','before':before,'after':after}
        policy={'id':'test','target':64,'exit':'extend','cells':5,'maxValue':64,
                'extensionExit':True,'singleTidyExit':True,'successNoExtraCombos':True}
        executor=RouteExecutor({'version':2,'kind':'stages','target':192,'cells':10,
                                'initialPrefix':before,'steps':[leaf]}, {'policies':[policy]},Worker)
        executor.bind_initial(game.observation(state))
        observation=game.observation(state);action=executor.next_action(observation)
        self.assertEqual(action,{'kind':'group','indices':[2,3,4]})
        result=game.apply(state,action);executor.accept(observation,action,game.observation(result))
        self.assertEqual(game.signature(result),[(5120,1,'tile'),(192,1,'tile')])
        self.assertIsNone(executor.next_action(game.observation(result)))
        self.assertEqual(executor.inner.stage,1)
        executor.close()


if __name__=='__main__':unittest.main()
