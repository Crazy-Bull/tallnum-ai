import unittest
from automation import game
from automation.entry_recovery import recovery_action,RecoveryExecutor

class EntryRecoveryTests(unittest.TestCase):
    def test_extension_recovery_requires_real_sources_and_tidy_exit(self):
        from automation.entry_recovery import leaf_completion_ids
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,5120),game.tile(state,192),game.tile(state,4)]
        fixed={state['tower'][0]['id'],999}
        state['tower'][1]['_sources']=[999]
        step={'kind':'leaf','exit':'extend','after':[[5120,1,False],[192,1,False]]}
        policy={'successNoExtraCombos':True,'singleTidyExit':True}
        ids={t['id'] for t in state['tower'][:2]}
        self.assertEqual(leaf_completion_ids(state,fixed,step,policy),ids)
        state['tower'].append(game.tile(state,2))
        self.assertIsNone(leaf_completion_ids(state,fixed,step,policy))
        state['tower'].pop();state['tower'][2]['value']=10
        self.assertIsNone(leaf_completion_ids(state,fixed,step,policy))
        state['tower'].pop();state['tower'][1]['_sources']=[]
        self.assertIsNone(leaf_completion_ids(state,fixed,step,policy))

    def test_recovered_match_rejects_extra_group(self):
        from automation.entry_recovery import match_completion_ids
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,640),game.tile(state,128)]
        fixed={state['tower'][0]['id'],999}
        state['tower'][1]['_sources']=[999]
        group=game.tile(state,6);group.update(kind='group',physicalCount=2)
        state['tower'].append(group)
        step={'kind':'leaf','exit':'match','after':[[640,1,False],[128,1,False]]}
        self.assertIsNone(match_completion_ids(state,fixed,step))
        state['tower'].pop()
        self.assertEqual(match_completion_ids(state,fixed,step),{t['id'] for t in state['tower']})

    def test_recovered_single_connection_uses_sources_and_tidy_residual(self):
        from automation.entry_recovery import leaf_completion_ids
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,640),game.tile(state,128),game.tile(state,4)]
        fixed={state['tower'][0]['id'],999}
        state['tower'][1]['_sources']=[999]
        step={'kind':'leaf','exit':'single','target':64,'singleConnectionAfter':[[640,1,False],[128,1,False]]}
        self.assertEqual(leaf_completion_ids(state,fixed,step),{t['id'] for t in state['tower'][:2]})
        state['tower'].append(game.tile(state,2))
        self.assertIsNone(leaf_completion_ids(state,fixed,step))

    def test_recorded_recovery_budget_death_can_continue_with_real_spare_cells(self):
        from automation.runtime import RouteFailure
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):return {'status':'dead'}
            def close(self):pass
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (2560,64)]
        group=game.tile(state,21);group.update(kind='group',physicalCount=3)
        state['tower'] += [group,game.tile(state,4)];state['queue']=[6,4,10,8]
        leaf={'kind':'leaf','policy':'test','target':64,'exit':'match','policyCells':5,
              'before':[[2560,1,False],[64,1,False]],'after':[[2560,1,False],[128,1,False]]}
        executor=RecoveryExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                  'initialPrefix':leaf['before'],'steps':[leaf]},
                                 {'policies':[{'id':'test','target':64,'exit':'match','cells':5,'maxValue':64}]},Worker)
        executor.fixed_ids={t['id'] for t in state['tower'][:2]};executor.initial_bound=True
        executor.recovery_counts[0]=12
        action=executor._next(game.observation(state))
        self.assertIsNotNone(action)
        self.assertEqual(executor.recovery_counts[0],13)
        self.assertTrue(executor.fixed_ids<={t['id'] for t in game.predict(game.observation(state),action)['tower']})
        executor.recovery_counts[0]=48
        with self.assertRaises(RouteFailure):executor._next(game.observation(state))
        executor.close()

    def test_recovery_does_not_rotate_one_anchor_out_of_protected_segment(self):
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (1280,128,32)]
        group=game.tile(state,21);group.update(kind='group',physicalCount=2)
        state['tower'] += [group]+[game.tile(state,v) for v in (6,30,15)]
        state['queue']=[15,6,4,8]
        fixed={t['id'] for t in state['tower'][:3]};order=[t['id'] for t in state['tower'][:3]]
        obs=game.observation(state)
        unsafe=game.predict(obs,{'kind':'up'})
        self.assertTrue(fixed<={t['id'] for t in unsafe['tower']})
        positions=[i for i,t in enumerate(unsafe['tower']) if t['id'] in fixed]
        self.assertNotEqual(positions,list(range(positions[0],positions[-1]+1)))
        action=recovery_action(obs,fixed,32,48)
        if action is not None:
            after=game.predict(obs,action);positions=[i for i,t in enumerate(after['tower']) if t['id'] in fixed]
            self.assertEqual(positions,list(range(positions[0],positions[-1]+1)))
            self.assertEqual([after['tower'][i]['id'] for i in positions],order)
            self.assertNotEqual(action,{'kind':'up'})

    def test_nonterminal_policy_macro_can_finish_exact_real_match(self):
        from automation.opening128_40 import ContractExecutor
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):return {'status':'ok','success':False,'ops':[{'kind':'up'}]}
            def close(self):pass
        state=game.new_game(1,10)
        group=game.tile(state,32);group.update(kind='group',physicalCount=2)
        state['tower']=[group]+[game.tile(state,v) for v in (4,640,320,160,64,32)]
        state['queue']=[4,10,8,6]
        leaf={'kind':'leaf','policy':'test','target':32,'exit':'match','policyCells':5,'allowEarlyRealMatch':True,
              'before':[[v,1,False] for v in (640,320,160,64,32)],
              'after':[[v,1,False] for v in (640,320,160,128)]}
        executor=ContractExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                  'initialPrefix':leaf['before'],'completionContract':leaf['after'],'steps':[leaf]},
                                 {'policies':[{'id':'test','target':32,'exit':'match','cells':5,'maxValue':64}]},Worker)
        executor.fixed_ids={t['id'] for t in state['tower'][2:]};executor.initial_bound=True
        before=game.observation(state);action=executor.next_action(before)
        self.assertEqual(action,{'kind':'up'})
        self.assertIsNone(executor.failure_reason)
        after=game.apply(state,action);executor.accept(before,action,game.observation(after))
        self.assertIsNone(executor.next_action(game.observation(after)))
        self.assertEqual(executor.stage,1)
        executor.close()

    def test_entry_clears_group_before_any_worker_or_alignment_drop(self):
        class Worker:
            def __init__(self,item):raise AssertionError('Clear free EDGE before opening a policy worker')
        state=game.new_game(1,10)
        group=game.tile(state,10);group.update(kind='group',physicalCount=2)
        state['tower']=[group]+[game.tile(state,v) for v in (15,2560,512,160,64)]
        state['queue']=[6,2,8,4]
        leaf={'kind':'leaf','policy':'test','target':64,'exit':'match','policyCells':5,
              'before':[[v,1,False] for v in (2560,512,160,64)],
              'after':[[v,1,False] for v in (2560,512,160,128)]}
        executor=RecoveryExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                  'initialPrefix':leaf['before'],'steps':[leaf]},
                                 {'policies':[{'id':'test','target':64,'exit':'match','cells':5,'maxValue':64}]},Worker)
        executor.fixed_ids={t['id'] for t in state['tower'][2:]};executor.initial_bound=True
        before=game.observation(state);action=executor.next_action(before)
        self.assertEqual(action,{'kind':'edge'})
        after=game.apply(state,action);executor.accept(before,action,game.observation(after))
        self.assertEqual(before['queue'],game.observation(after)['queue'])
        self.assertEqual(state['drops'],after['drops'])
        self.assertEqual(game.signature(after),[(2,1,'tile'),(2560,1,'tile'),(512,1,'tile'),(160,1,'tile'),(64,1,'tile')])
        self.assertIsNone(executor.failure_reason)
        executor.close()

    def test_exact_match_cascade_can_complete_instead_of_abandoning_boundary(self):
        from unittest.mock import patch
        from automation.opening128_40 import ContractExecutor
        from automation.runtime import RouteFailure
        state=game.new_game(1,10)
        group=game.tile(state,32);group.update(kind='group',physicalCount=2)
        state['tower']=[group]+[game.tile(state,v) for v in (4,640,320,160,64,32)]
        state['queue']=[4,10,8,6]
        leaf={'kind':'leaf','policy':'test','target':32,'exit':'match','policyCells':5,
              'before':[[v,1,False] for v in (640,320,160,64,32)],
              'after':[[v,1,False] for v in (640,320,160,128)]}
        executor=RecoveryExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                  'initialPrefix':leaf['before'],'completionContract':leaf['after'],'steps':[leaf]},
                                 {'policies':[{'id':'test','target':32,'exit':'match','cells':5,'maxValue':64}]})
        executor.fixed_ids={t['id'] for t in state['tower'][2:]};executor.initial_bound=True
        before=game.observation(state)
        with patch.object(ContractExecutor,'_next',side_effect=RouteFailure('boundary-alignment-unavailable')):
            action=executor._next(before)
        self.assertEqual(action,{'kind':'up'})
        after=game.apply(state,action);executor.accept(before,action,game.observation(after))
        self.assertEqual(executor.stage,1)
        self.assertIsNone(executor.next_action(game.observation(after)))
        self.assertEqual(game.signature(after),[(4,1,'tile'),(640,1,'tile'),(320,1,'tile'),(160,1,'tile'),(128,1,'tile'),(4,1,'tile')])
        executor.close()

    def test_longer_known_preview_sequence_can_clear_more_residual_cells(self):
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (2,8,4,40)]
        group=game.tile(state,17);group.update(kind='group',physicalCount=2)
        state['tower'] += [group,game.tile(state,10)]
        state['queue']=[2,10,999,999]
        fixed={state['tower'][3]['id']};obs=game.observation(state)
        short={};long={}
        recovery_action(obs,fixed,40,48,width=6,depth=3,diagnostics=short)
        action=recovery_action(obs,fixed,40,48,diagnostics=long)
        self.assertGreater(long['bestScore'],short['bestScore'])
        self.assertEqual(action,{'kind':'up'})
        state['queue'][2:]=[15,6]
        self.assertEqual(recovery_action(game.observation(state),fixed,40,48),action)
        self.assertTrue(fixed<={t['id'] for t in game.predict(obs,action)['tower']})

    def test_protected_boundary_collision_uses_safe_alignment(self):
        from unittest.mock import patch
        from automation.opening128_40 import ContractExecutor
        from automation.runtime import RouteFailure
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (2560,512,160,64,32,30,15,10)]
        state['queue']=[6,4,8,2]
        fixed={t['id'] for t in state['tower'][:5]}
        obs=game.observation(state)
        self.assertFalse(fixed<={t['id'] for t in game.predict(obs,{'kind':'edge'})['tower']})
        leaf={'kind':'leaf','policy':'test','target':32,'exit':'match','policyCells':5,
              'before':[[v,1,False] for v in (2560,512,160,64,32)],
              'after':[[v,1,False] for v in (2560,512,160,64,64)]}
        executor=RecoveryExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                  'initialPrefix':leaf['before'],'steps':[leaf]},
                                 {'policies':[{'id':'test','target':32,'exit':'match','cells':5,'maxValue':48}]})
        executor.fixed_ids=fixed
        with patch.object(ContractExecutor,'_next',side_effect=RouteFailure('fixed-policy-action-would-merge-protected-segment')):
            action=executor._next(obs)
        self.assertIsNotNone(action)
        self.assertTrue(fixed<={t['id'] for t in game.predict(obs,action)['tower']})
        self.assertIsNone(executor.inner)
        self.assertEqual(executor.recovery_events[0]['reason'],'fixed-policy-action-would-merge-protected-segment')
        executor.close()

    def test_residual_group_can_be_removed_before_planned_group_without_losing_anchors(self):
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (640,320,160,128,32)]
        extra=game.tile(state,14);extra.update(kind='group',physicalCount=2)
        state['tower'] += [extra,game.tile(state,15)]
        step={'kind':'group','indices':[1,2,3,4],
              'before':[[v,1,False] for v in (640,320,160,128,32)],'after':[[1280,1,False]]}
        executor=RecoveryExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                   'initialPrefix':step['before'],'completionContract':step['after'],
                                   'steps':[step]},{'policies':[]})
        before=game.observation(state);action=executor.next_action(before)
        self.assertEqual(action,{'kind':'edge'})
        after=game.apply(state,action);executor.accept(before,action,game.observation(after))
        self.assertIsNone(executor.failure_reason)
        self.assertEqual(len(executor.fixed_ids),5)
        action=executor.next_action(game.observation(after))
        self.assertEqual(action,{'kind':'group','indices':[1,2,3,4]})
        done=game.apply(after,action);executor.accept(game.observation(after),action,game.observation(done))
        self.assertIsNone(executor.next_action(game.observation(done)))
        self.assertEqual(game.signature(done),[(1280,1,'tile'),(2,1,'tile')])
        executor.close()
    def test_six_cell_overflow_can_continue_alignment_in_spare_real_cells(self):
        class Worker:
            def __init__(self,item):pass
            def query(self,board,*args):
                if sum(t['physicalCount'] for t in board)>=6:
                    raise AssertionError('Overflow must be handled before querying')
                return {'status':'dead'}
            def close(self):pass
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (80,4,8,2,6,15,10)]
        state['queue']=[2,4,8,6]
        leaf={'kind':'leaf','policy':'test','target':40,'exit':'single','policyCells':6,
              'before':[[80,1,False]],'after':[[80,1,False],[40,1,False]]}
        executor=RecoveryExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                   'initialPrefix':[[80,1,False]],'completionContract':leaf['after'],
                                   'steps':[leaf]},
                                  {'policies':[{'id':'test','target':40,'exit':'single','cells':6,'maxValue':48}]},Worker)
        action=executor.next_action(game.observation(state))
        self.assertIsNone(executor.failure_reason)
        self.assertEqual(executor.recovery_events[0]['reason'],'6-cell-capacity')
        self.assertTrue(executor.fixed_ids<={t['id'] for t in game.predict(game.observation(state),action)['tower']})
        executor.close()
    def test_dead_macro_is_discarded_before_accepting_real_alignment_action(self):
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):return {'status':'dead'}
            def close(self):pass
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (80,4,8,2,6,15)]
        state['queue']=[2,4,8,6]
        leaf={'kind':'leaf','policy':'test','target':40,'exit':'single','policyCells':6,
              'before':[[80,1,False]],'after':[[80,1,False],[40,1,False]]}
        executor=RecoveryExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                   'initialPrefix':[[80,1,False]],'completionContract':leaf['after'],
                                   'steps':[leaf]},
                                  {'policies':[{'id':'test','target':40,'exit':'single','cells':6,'maxValue':48}]},Worker)
        before=game.observation(state);action=executor.next_action(before)
        self.assertIsNone(executor.failure_reason)
        self.assertIsNone(executor.inner)
        self.assertEqual(len(executor.recovery_events),1)
        after=game.apply(state,action)
        executor.accept(before,action,game.observation(after))
        self.assertTrue(executor.fixed_ids<={t['id'] for t in after['tower']})
        executor.close()
    def test_spare_real_cells_allow_alignment_without_touching_anchor(self):
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (8,24,40)]
        group=game.tile(state,19);group['kind']='group';group['physicalCount']=2
        state['tower']+=[group,game.tile(state,4)]
        state['queue']=[10,15,2,4]
        obs=game.observation(state);fixed={state['tower'][2]['id']}
        action=recovery_action(obs,fixed,40,48)
        self.assertIsNotNone(action)
        after=game.predict(obs,action)
        self.assertTrue(fixed<={t['id'] for t in after['tower']})
        self.assertFalse(after['gameOver'])
        self.assertEqual(len(obs['queue']),2)

    def test_never_uses_hidden_draws_and_cannot_play_a_full_board(self):
        state=game.new_game(2,10)
        state['tower']=[game.tile(state,v) for v in (2,4,8,6,15,10,2,4,8,6)]
        state['gameOver']=True
        self.assertIsNone(recovery_action(game.observation(state),set(),40,48))

    def test_oversized_free_bridge_reenters_original_six_cell_bound(self):
        queried=[]
        class Worker:
            def __init__(self,item):pass
            def query(self,board,*args):
                self_bound=max(t['value'] for t in board)
                if self_bound>48:raise AssertionError('Never query oversized intermediates')
                queried.append(board)
                return {'status':'ok','success':False,'ops':[{'kind':'drop'}]}
            def close(self):pass
        state=game.new_game(1,10)
        state['tower']=[game.tile(state,v) for v in (80,64,15,15,15,15,6)]
        state['queue']=[2,4,15,10]
        leaf={'kind':'leaf','policy':'test','target':40,'exit':'single','policyCells':6,
              'before':[[80,1,False]],'after':[[80,1,False],[40,1,False]]}
        executor=RecoveryExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                  'initialPrefix':leaf['before'],'completionContract':leaf['after'],'steps':[leaf]},
                                 {'policies':[{'id':'test','target':40,'exit':'single','cells':6,'maxValue':48}]},Worker)
        before=game.observation(state);action=executor.next_action(before)
        self.assertEqual(action,{'kind':'group','indices':[2,3,4,5]})
        self.assertTrue(executor.recovery_events[-1]['verifiedEntryPreferred'])
        self.assertTrue(queried)
        after=game.apply(state,action);executor.accept(before,action,game.observation(after))
        self.assertEqual(executor.next_action(game.observation(after)),{'kind':'edge'})
        reduced=game.apply(after,{'kind':'edge'})
        self.assertEqual(game.signature(reduced),[(80,1,'tile'),(12,1,'tile'),(6,1,'tile')])
        self.assertEqual(state['queue'],reduced['queue'])
        self.assertEqual(state['rngState'],reduced['rngState'])
        executor.close()

    def test_recovery_single_exit_completes_without_virtual_policy(self):
        class Worker:
            def __init__(self,item):pass
            def query(self,*args):return {'status':'dead'}
            def close(self):pass
        state=game.new_game(1,10);state['tower']=[game.tile(state,v) for v in (80,20,12,8)]
        state['queue']=[2,4,15,10]
        leaf={'kind':'leaf','policy':'test','target':40,'exit':'single','policyCells':6,
              'before':[[80,1,False]],'after':[[80,1,False],[40,1,False]]}
        executor=RecoveryExecutor({'version':2,'kind':'stages','target':-1,'cells':10,
                                  'initialPrefix':leaf['before'],'completionContract':leaf['after'],'steps':[leaf]},
                                 {'policies':[{'id':'test','target':40,'exit':'single','cells':6,'maxValue':48}]},Worker)
        before=game.observation(state);action=executor.next_action(before)
        self.assertEqual(action,{'kind':'group','indices':[2,3]})
        after=game.apply(state,action);executor.accept(before,action,game.observation(after))
        self.assertEqual(executor.stage,1)
        self.assertIsNone(executor.next_action(game.observation(after)))
        self.assertEqual(game.signature(after),[(80,1,'tile'),(40,1,'tile')])
        executor.close()
