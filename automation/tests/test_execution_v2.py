import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from automation import game
from automation.execution import create_executor, continuation_executor
from automation.route_search import RouteSearch, Block
from automation.route_baseline import legacy_structure
from automation.resume import restore_executor
from automation.runtime import IncompatibleState, RouteFailure


class ExecutionV2Tests(unittest.TestCase):
    def test_local_bounds_and_baseline_obey_space_and_leaf_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=RouteSearch(tmp,{'policies':[]},target=640,max_value=1280,
                          local_template_bounds=True,max_leaf_target=128,
                          leaf_targets=[*range(2,129,2),15])
            try:
                self.assertEqual(s.requirement(40,'single')['maxValue'],80)
                self.assertEqual(s.requirement(96,'match')['maxValue'],96)
                with self.assertRaises(ValueError):s.requirement(14,'single')
                self.assertEqual(s.requirement(14,'buffer')['bases'],[1,3,5,15])
                b=legacy_structure(s)
                self.assertTrue(b['baseline'])
                self.assertEqual(b['steps'][-1]['after'],[[640,1,False]])
                for step in b['steps']:
                    self.assertLessEqual(sum(x[1] for x in step['before']),2)
                    self.assertLessEqual(step['target'],128)
            finally:s.close()

    def route(self):
        return {'id':'test-v2','version':2,'kind':'stages','cells':7,'target':4,
                'initialPrefix':[[2,1,False]],'steps':[{'kind':'edge','before':[[2,1,False]],'after':[[4,1,False]]}]}

    def test_initial_prefix_cannot_bind_to_a_group_or_wrong_value(self):
        route=self.route();state=game.new_game(1);obs=game.observation(state)
        obs['tower'][0]['value']=8
        with self.assertRaises(IncompatibleState):create_executor(route,{}).bind_initial(obs)
        obs['tower'][0]['value']=2;obs['tower'][0]['kind']='group'
        with self.assertRaises(IncompatibleState):create_executor(route,{}).bind_initial(obs)

    def test_virtual_projection_never_changes_real_observation(self):
        route={'id':'full','version':2,'kind':'stages','cells':7,'target':4,'steps':[],
               'continuation':self.route()}
        state=game.new_game(1);state['tower'][0]['value']=4;state['tower'][1]['value']=6;obs=game.observation(state)
        runner=continuation_executor(route,{},obs)
        self.assertEqual(obs['tower'][0]['value'],4)
        self.assertEqual(runner.shadow['tower'][0]['value'],2)
        self.assertEqual(runner.inner.fixed_ids,{obs['tower'][0]['id']})
        with patch.object(runner.inner,'next_action',return_value=None):
            self.assertEqual(runner.next_action(obs),{'kind':'drop'})
        after=game.observation(game.apply(state,{'kind':'drop'}));runner.accept(obs,{'kind':'drop'},after)
        self.assertEqual(after['tower'][0]['value'],4)
        runner.close()

    def test_terminal_virtual_merge_can_diverge_from_the_real_board(self):
        route={'id':'full','version':2,'kind':'stages','cells':7,'target':4,'steps':[],
               'continuation':self.route()}
        state=game.new_game(1);state['tower'][0]['value']=4;state['tower'][1]['value']=2
        state['queue']=[6,10,15,8];before=game.observation(state)
        runner=continuation_executor(route,{},before)
        after=game.observation(game.apply(state,{'kind':'drop'}))
        runner.accept(before,{'kind':'drop'},after)
        self.assertEqual(runner.failure_reason,'virtual-target-completed')
        self.assertEqual([t['value'] for t in after['tower']],[4,2,6])
        self.assertEqual(runner.next_action(after),{'kind':'drop'})
        runner.close()

    def test_virtual_continuation_aligns_real_target_using_a_real_rotation_drop(self):
        route={'id':'full','version':2,'kind':'stages','cells':7,'target':4,'steps':[],
               'continuation':self.route()}
        state=game.new_game(1);state['tower'][0]['value']=6;state['tower'][1]['value']=4
        state['queue']=[10,15,8,6];before=game.observation(state)
        runner=continuation_executor(route,{},before)
        action=runner.next_action(before)
        self.assertEqual(action,{'kind':'down'})
        after=game.observation(game.apply(state,action));runner.accept(before,action,after)
        self.assertEqual(after['tower'][0]['value'],4)
        self.assertEqual(after['drops'],before['drops']+1)
        self.assertFalse(runner.aligning)
        self.assertEqual(runner.shadow['tower'][0]['value'],2)
        self.assertEqual(runner.inner.fixed_ids,{after['tower'][0]['id']})
        runner.close()

    def test_virtual_continuation_recovers_real_edge_collision_instead_of_suicide(self):
        single={'kind':'leaf','target':32,'exit':'single','policy':'s','policyCells':6,
                'before':[[320,1,False]],'after':[[320,1,False],[32,1,False]]}
        match={'kind':'leaf','target':32,'exit':'match','policy':'m','policyCells':5,
               'before':single['after'],'after':[[320,1,False],[64,1,False]]}
        continuation={'version':2,'kind':'stages','cells':7,'target':640,
                      'initialPrefix':[[320,1,False]],'steps':[single,match]}
        route={'version':2,'kind':'stages','cells':7,'target':640,'steps':[],
               'continuation':continuation}
        class Worker:
            def __init__(self,item):self.item=item
            def close(self):pass
            def query(self,board,fpos,queue):
                if self.item['id']=='s':return {'status':'ok','success':False,'ops':[{'kind':'drop'}]}
                return {'status':'ok','success':True,'ops':[
                    {'kind':'group','l':1,'r':2},{'kind':'edge'}, {'kind':'group','l':0,'r':1}]}
        catalog={'policies':[{'id':'s','target':32,'exit':'single','cells':6,'maxGoalCells':1},
                             {'id':'m','target':32,'exit':'match','cells':5}]}
        state=game.new_game(1);state['tower']=[game.tile(state,v) for v in (640,32,30,8,6,15)]
        state['queue']=[2,2,4,6];before=game.observation(state)
        runner=continuation_executor(route,catalog,before,Worker)
        runner.inner.stage=1;runner.inner.fixed_ids={t['id'] for t in before['tower'][:2]}
        action=runner.next_action(before)
        self.assertEqual(action,{'kind':'edge'})
        state=game.apply(state,action);after=game.observation(state);runner.accept(before,action,after)
        self.assertEqual(game.signature(after),[(v,1,'tile') for v in (640,6,8,6,15)])
        self.assertEqual(runner.inner.stage,0)
        self.assertIsNone(runner.failure_reason)
        action=runner.next_action(after)
        self.assertEqual(action,{'kind':'drop'})
        newer=game.observation(game.apply(state,action));runner.accept(after,action,newer)
        self.assertIsNone(runner.failure_reason)
        self.assertEqual(newer['tower'][0]['value'],640)
        runner.close()

    def test_virtual_edge_recovery_never_sacrifices_real_anchor(self):
        route={'version':2,'kind':'stages','cells':7,'target':640,'steps':[],
               'continuation':{'version':2,'kind':'stages','cells':7,'target':640,
                               'initialPrefix':[[320,1,False]],'steps':[]}}
        state=game.new_game(1);state['tower']=[game.tile(state,v) for v in (640,648,2)]
        before=game.observation(state);runner=continuation_executor(route,{},before)
        self.assertIsNone(runner._recover_edge(before))
        self.assertEqual(before['tower'][0]['value'],640)
        runner.close()

    def test_continuation_baseline_finishes_the_half_boundary(self):
        from automation.route_discovery import CandidateDiscovery
        with tempfile.TemporaryDirectory() as tmp:
            search=RouteSearch(tmp,{'policies':[]},target=640,max_value=1280,
                               initial_prefix=[[320,1,False]],local_template_bounds=True,
                               max_leaf_target=128,leaf_targets=[*range(2,129,2),15])
            try:
                baseline=legacy_structure(search)
                self.assertEqual(baseline['steps'][0]['before'],[[320,1,False]])
                self.assertEqual(baseline['steps'][-1]['after'],[[640,1,False]])
                discovery=CandidateDiscovery(search)
                with patch.object(discovery,'build',return_value=[]) as build:
                    discovery.discover()
                    build.assert_called_once_with((Block(320),),320)
            finally:search.close()

    def test_only_one_controller_can_hold_the_browser_lease(self):
        from automation.controller_lock import controller_lease
        with controller_lease('unit-test'):
            with self.assertRaises(RuntimeError):
                with controller_lease('unit-test'):pass
        with controller_lease('unit-test'):pass

    def test_storage_cleanup_preserves_registered_sources_and_live_work(self):
        from automation.route_storage import prune_completed
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'aggressive'/'done';work.mkdir(parents=True)
            source=work/'07_petsc_actual.policy.bin';source.write_bytes(b'keep')
            (work/'02_petsc_aggressive.policy.bin').write_bytes(b'old')
            (work/'07_petsc_actual.values.bin').write_bytes(b'old')
            (work/'exit_probability_02.result.json').write_text('{}')
            active=root/'aggressive'/'active';active.mkdir()
            active_file=active/'02_petsc_aggressive.policy.bin';active_file.write_bytes(b'keep')
            item={'source':str(source)}
            with patch('automation.route_storage.load_catalog',return_value={'policies':[item]}):
                self.assertEqual(prune_completed(root),6)
                self.assertEqual(prune_completed(root),0)
            self.assertTrue(source.exists());self.assertTrue(active_file.exists())

    def test_zero_probability_certified_variant_is_complete_but_unusable(self):
        from automation.route_variants import manifest
        requirement={'target':14,'exit':'single','maxValue':48,'bases':list(range(1,49,2)),
                     'maxGoalCells':1,'aggressiveness':[0]}
        policy={**requirement,'aggressiveness':0,'id':'p','policy':'p.bin','policySha256':'x',
                'statistics':{'p':0,'u':0,'v':2,'usable':True},
                'petsc':{'verified':True,'exitEvaluationRounds':2},'exitSemantics':'success-board-v2'}
        with tempfile.TemporaryDirectory() as tmp:
            report=manifest(tmp,requirement,{'policies':[policy]})
            self.assertTrue(report['complete'])
            self.assertFalse(report['variants'][0]['usable'])

    def test_workflow_never_hands_off_an_unverified_route(self):
        from automation.route_workflow import run
        plan={'status':'ready-for-simulation','structures':[], 'missing':[],
              'requirements':[],'routes':[{'id':'r','steps':[]}]}
        validation={'verified':False,'results':[]}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'route-request.json').write_text(json.dumps({'target':640}))
            with patch('automation.route_workflow.route_command',side_effect=[plan,plan,validation]),patch('automation.route_workflow.event'),patch('automation.browser.play') as browser:
                with self.assertRaisesRegex(RuntimeError,'independent 100-game holdout'):
                    run(root,play=True,previous=root/'old')
                browser.assert_not_called()
            self.assertEqual(json.loads((root/'workflow.json').read_text())['stage'],'failed')

    def test_resume_rejects_another_route_identity(self):
        state=game.new_game(1);before=game.observation(state);after=game.observation(game.apply(state,{'kind':'drop'}))
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'actions.jsonl';f.write_text(json.dumps({'routeId':'different','before':before,'after':after,'action':{'kind':'drop'}})+'\n')
            with self.assertRaises(IncompatibleState):restore_executor(self.route(),{},f,after)


if __name__=='__main__':unittest.main()
