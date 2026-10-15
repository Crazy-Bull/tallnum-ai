import unittest
from unittest.mock import patch
from automation import game
from automation.route_runtime import RouteExecutor


class HandoffTests(unittest.TestCase):
    def test_revealed_preview_can_defer_binding_a_completed_goal(self):
        class Worker:
            def __init__(self,item):self.item=item
            def query(self,*args):
                if self.item['target']==12:return {'status':'dead'}
                return {'status':'ok','success':True,'post':1,'ops':[{'kind':'drop',
                    'board':{'fpos':0,'blocks':[{'value':6,'span':1,'combo':False}]}}]}
            def close(self):pass
        state=game.new_game(42,10)
        state['tower']=[game.tile(state,v) for v in (5120,18)]
        state['queue']=[6,6,8,10]
        before=[[5120,1,False],[18,1,False]];middle=before+[[6,1,False]]
        leaves=[{'kind':'leaf','target':6,'exit':'single','policy':'six','policyCells':5,'before':before,'after':middle},
                {'kind':'leaf','target':12,'exit':'single','policy':'twelve','policyCells':5,'before':middle,'after':middle+[[12,1,False]]}]
        policies=[{'id':name,'cells':5,'target':value,'exit':'single','maxValue':48,
                   'pendingValue':'test','realBoardAlternatives':True,'singleTidyExit':True,'successNoExtraCombos':True}
                  for name,value in [('six',6),('twelve',12)]]
        executor=RouteExecutor({'version':2,'kind':'stages','cells':10,'target':10240,'initialPrefix':before,
                                'steps':leaves,'checkNextLeafEntry':True},{'policies':policies},Worker)
        observation=game.observation(state);action=executor.next_action(observation)
        created=game.apply(state,action);executor.accept(observation,action,game.observation(created))
        self.assertEqual(game.signature(created),[(5120,1,'tile'),(18,1,'tile'),(6,1,'tile')])
        with patch('automation.runtime.os.path.getsize',return_value=0):
            deferred=executor.next_action(game.observation(created))
        self.assertEqual(deferred,{'kind':'drop'})
        consumed=game.apply(created,deferred)
        executor.accept(game.observation(created),deferred,game.observation(consumed))
        self.assertEqual(executor.stage,0)
        self.assertEqual(executor.fixed_ids,{t['id'] for t in state['tower']})
        self.assertEqual(game.signature(consumed),[(5120,1,'tile'),(18,1,'tile'),(12,1,'tile')])
        self.assertEqual(executor.handoff_events[-1]['reason'],'consume-preview-before-rebuilding-goal')
        self.assertIsNone(executor.inner)
        executor.close()

    def test_known_dead_successor_rejects_free_exit_before_execution(self):
        queried=[]
        class Worker:
            def __init__(self,item):self.item=item
            def query(self,board,fpos,queue,excluded=()):
                queried.append((self.item['target'],queue[:],list(excluded)))
                if self.item['target']==12:return {'status':'dead'}
                if 0 in excluded:return {'status':'ok','success':False,'post':10,'ops':[{'kind':'drop'}]}
                return {'status':'ok','success':True,'post':0,'ops':[
                    {'kind':'edge','board':{'fpos':0,'blocks':[{'value':6,'span':1,'combo':False}]}}]}
            def close(self):pass
        state=game.new_game(42,10)
        state['tower']=[game.tile(state,v) for v in (5120,18,30,34)]
        state['tower'][-1].update(kind='group',physicalCount=3)
        state['queue']=[6,8,15,10]
        before=[[5120,1,False],[18,1,False]]
        middle=before+[[6,1,False]]
        leaves=[{'kind':'leaf','target':6,'exit':'single','policy':'six','policyCells':5,'before':before,'after':middle},
                {'kind':'leaf','target':12,'exit':'single','policy':'twelve','policyCells':5,'before':middle,'after':middle+[[12,1,False]]}]
        policies=[{'id':name,'cells':5,'target':value,'exit':'single','maxValue':48,
                   'pendingValue':'test','realBoardAlternatives':True,'singleTidyExit':True,'successNoExtraCombos':True}
                  for name,value in [('six',6),('twelve',12)]]
        executor=RouteExecutor({'version':2,'kind':'stages','cells':10,'target':10240,'initialPrefix':before,
                                'steps':leaves,'checkNextLeafEntry':True},{'policies':policies},Worker)
        observation=game.observation(state)
        with patch('automation.runtime.os.path.getsize',return_value=0):
            action=executor.next_action(observation)
        self.assertEqual(action,{'kind':'drop'})
        self.assertEqual(queried,[(6,[6,8],[]),(12,[6,8],[]),(6,[6,8],[0])])
        self.assertIsNone(executor.failure_reason)
        self.assertEqual(executor.handoff_events[0]['reason'],'known-dead-next-entry')
        self.assertEqual(state['queue'],[6,8,15,10])
        self.assertEqual(game.signature(state),[(5120,1,'tile'),(18,1,'tile'),(30,1,'tile'),(34,3,'group')])
        executor.close()

    def test_hidden_preview_does_not_enter_successor_query(self):
        executor=RouteExecutor.__new__(RouteExecutor)
        executor.stage=0;executor.route={'steps':[{}, {'kind':'leaf'}]}
        self.assertTrue(executor._handoff_viable({'queue':[8,None]},[0]))


if __name__=='__main__':unittest.main()
