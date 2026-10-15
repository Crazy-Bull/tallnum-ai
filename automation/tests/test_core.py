import json
import math
from pathlib import Path
import subprocess
import unittest

from automation.planner import Metrics, Planner
from automation.statistics import evaluate
from automation import game
from automation.runtime import Executor, IncompatibleState, RouteFailure
from automation.validation import summarize


def policy(target,kind,p=.8,s=10,f=3):
    return {'id':f'{target}-{kind}', 'target':target, 'exit':kind,
            'maxValue':max(48,2*target) if target<48 else target,
            'statistics':{'p':p,'u':p*s,'v':(1-p)*f,'usable':True}}


class MetricsTests(unittest.TestCase):
    def test_serial_failure_cost(self):
        # A: success 1/2 costs 2, failure costs 4; B: success 1/4
        # costs 3, failure costs 5. Enumerate all three terminating events.
        m=Metrics(.5,1,2).then(Metrics(.25,.75,3.75))
        self.assertAlmostEqual(m.p,.125)
        self.assertAlmostEqual(m.u,.125*5)
        self.assertAlmostEqual(m.v,.5*4+.5*.75*7)
        self.assertAlmostEqual(m.expected,42)

    def test_absorption_with_terminal_drop(self):
        # s0: 1/2 self, 1/3 success, 1/6 failure; pay one drop per visit.
        result=evaluate([0,1,2],[1,1,0],[[0,0,0,1,1,2],[0]*6,[0]*6],initial=[0])
        self.assertAlmostEqual(result['p'],2/3)
        self.assertAlmostEqual(result['successDrops'],3)
        self.assertAlmostEqual(result['failureDrops'],2)
        self.assertAlmostEqual(result['expectedTotalDrops'],4)

    def test_closed_class_not_finite_failure(self):
        result=evaluate([0,1],[1,0],[[0]*6,[0]*6],initial=[0])
        self.assertFalse(result['usable'])
        self.assertEqual(result['nonterminationProbability'],1)
        self.assertIsNone(result['expectedTotalDrops'])
        self.assertEqual(result['failureProbability'],0)

    def test_free_and_drop_success(self):
        r=evaluate([1,1],[0,1],[[0]*6,[0]*6],initial=[0,1])
        self.assertEqual(r['successDrops'],.5)
        self.assertIsNone(r['failureDrops'])


class PlannerTests(unittest.TestCase):
    def test_target768_and_one_triple(self):
        p=Planner({'policies':[]})
        plan=p.plan()
        self.assertEqual(plan['triples']['384'],{'a':128,'b':128})
        self.assertEqual(plan['target'],768)
        self.assertTrue(all(m['cells']==5 for m in plan['missing']))
        self.assertIn('5:128:extend',[m['key'] for m in plan['missing']])
        self.assertNotIn('5:384:extend',[m['key'] for m in plan['missing']])

    def test_small_threshold_and_single_exit(self):
        p=Planner({'policies':[policy(24,'single'),policy(24,'match')]})
        small=p.solve(7,24)
        self.assertTrue(small[0]['approximation'])
        self.assertEqual(small[0]['kind'],'leaf')
        at48=p.solve(7,48)
        self.assertEqual(at48[0]['kind'],'binary')
        self.assertEqual([x['target'] for x in at48[0]['children']],[24,24])

    def test_small_bound_requires_expanded_variant(self):
        p=Planner({'policies':[dict(policy(16,'single'),maxValue=16)]})
        p.solve(5,16)
        self.assertEqual(p.missing['5:16:single']['maxValue'],48)
        expanded={**policy(16,'single'),'maxValue':48}
        p=Planner({'policies':[expanded]})
        p.solve(5,16)
        self.assertFalse(p.missing)

    def test_small_route_does_not_shrink_intermediate_bound(self):
        variants=[]
        for kind in ('single','match','extend'):
            variants.extend([dict(policy(16,kind,p=1),id=f'{kind}-16',maxValue=16),
                             dict(policy(16,kind,p=.9),id=f'{kind}-48',maxValue=48)])
        route=Planner({'policies':variants}).solve(6,48,'match')[0]
        self.assertEqual([c['policy'] for c in route['children']],['single-48','match-48','extend-48'])

    def test_full_dp_with_synthetic_statistics(self):
        catalog={'policies':[]}
        for _ in range(4):
            plan=Planner(catalog).plan()
            for item in plan['missing']:
                catalog['policies'].append(policy(item['target'],item['exit']))
        plan=Planner(catalog).plan()
        self.assertEqual(plan['status'],'ready')
        root=plan['routes'][0]
        self.assertEqual(root['kind'],'binary')
        self.assertEqual([(c['cells'],c['target']) for c in root['children']],[(7,384),(6,384)])
        self.assertIsNotNone(root['metrics']['expectedTotalDrops'])

    def test_missing_cache_determinism(self):
        p=Planner({'policies':[]})
        self.assertEqual(p.triple(384),(128,128))
        self.assertEqual(p.triple(384),(128,128))
        self.assertEqual(len(p.triples),1)

    def test_unbalanced_statistics_cannot_change_triple(self):
        p=Planner({'policies':[policy(160,'match',1,1,0),policy(64,'extend',1,1,0)]})
        self.assertEqual(p.triple(384),(128,128))


class RuntimeTests(unittest.TestCase):
    def test_opening_preserves_virtual_gap_after_matching_macro(self):
        e=self.executor({'status':'dead'})
        e.fixed_ids=set()
        s=game.new_game(2)
        before=game.observation(s)
        after=game.apply(s,{'kind':'down'})
        obs=game.observation(after)
        e.macro_board={'fpos':1,'blocks':[{'value':t['value'],'span':t['physicalCount'],'combo':t['kind']=='group'} for t in obs['tower']]}
        e.accept(before,{'kind':'down'},obs)
        self.assertEqual(e._project(obs)[1],1)
        e.accept(before,{'kind':'down'},obs,legacy_opening=True)
        self.assertEqual(e._project(obs)[1],0)
        e.close()

    def test_single_goal_cannot_use_a_multi_cell_policy(self):
        leaf={'id':'leaf','kind':'leaf','policy':'p','target':24,'cells':5,'exit':'single'}
        with self.assertRaisesRegex(IncompatibleState,'one-cell goal'):
            Executor(leaf,{'policies':[{'id':'p','target':24,'exit':'single','maxGoalCells':5}]})

    def test_combination24_does_not_finish_the_single24_stage(self):
        e=self.executor({'status':'dead'})
        e.leaves[0]['exit']='single'
        s=game.new_game(2)
        s['tower']=[game.tile(s,24,kind='group',physicalCount=2,members=[])]
        self.assertEqual(e.next_action(game.observation(s)),{'kind':'drop'})
        self.assertEqual(e.stage,0)
        self.assertEqual(e.fixed_ids,set())
        e.close()

    def executor(self, reply):
        class Worker:
            def __init__(self, item): pass
            def query(self, *args): return reply
            def close(self): pass
        leaf={'id':'leaf','kind':'leaf','policy':'p','target':24,'cells':5,'exit':'match'}
        root={'id':'route','kind':'binary','target':48,'children':[leaf]}
        return Executor(root,{'policies':[{'id':'p','states':1}]},Worker)

    def test_dead_policy_drops_until_actual_game_over(self):
        e=self.executor({'status':'dead'})
        state=game.new_game(13)
        e.fixed_ids={state['tower'][0]['id']}
        for _ in range(100):
            before=game.observation(state)
            if state['gameOver']:
                with self.assertRaisesRegex(RouteFailure,'fixed-policy-dead'):
                    e.next_action(before)
                break
            action=e.next_action(before)
            self.assertEqual(action,{'kind':'drop'})
            state=game.apply(state,action)
            e.accept(before,action,game.observation(state))
        self.assertTrue(state['gameOver'])
        self.assertGreater(state['drops'],0)
        e.reset()
        self.assertIsNone(e.failure_reason)
        e.close()

    def test_failure_statistics_include_final_drops(self):
        from unittest.mock import patch
        from automation.validation import validate
        e=self.executor({'status':'dead'})
        expected=game.new_game(100000)
        while not expected['gameOver']:
            expected=game.apply(expected,{'kind':'drop'})
        with patch('automation.validation.Executor',return_value=e):
            result=validate(e.route,{},attempts=1,progress=False)
        self.assertEqual(result['records'][0]['outcome'],'failure')
        self.assertEqual(result['failureDrops'],expected['drops'])
        self.assertEqual(result['unfinished'],0)

    def test_virtual_384_boundary_keeps_real_768_and_finishes_divergence(self):
        from automation.runtime import VirtualBoundaryExecutor
        board={'fpos':0,'blocks':[{'value':128,'span':2,'combo':True}]}
        class Worker:
            def __init__(self,item): pass
            def query(self,*args):
                return {'status':'ok','success':True,'board':board,
                        'ops':[{'kind':'group','l':0,'r':1,'board':board}]}
            def close(self): pass
        leaves=[{'kind':'leaf','policy':'p','target':128,'exit':kind} for kind in ('single','match','extend')]
        right={'kind':'ternary','target':384,'children':leaves}
        route={'kind':'binary','target':768,'children':[right,right]}
        state=game.new_game(13)
        state['tower']=[game.tile(state,v) for v in [768,256,32,96]]
        before=game.observation(state)
        e=VirtualBoundaryExecutor(route,{'policies':[{'id':'p','states':1}]},before,Worker)
        e.inner.stage=2
        e.inner.fixed_ids={t['id'] for t in before['tower'][:2]}
        self.assertEqual(e.shadow['tower'][0]['value'],384)
        action=e.next_action(before)
        self.assertEqual(action,{'kind':'group','indices':[1,2,3]})
        state=game.apply(state,action)
        e.accept(before,action,game.observation(state))
        self.assertEqual(game.signature(state),[(768,1,'tile'),(384,3,'group')])
        self.assertEqual(e.failure_reason,'virtual-target-completed')
        self.assertEqual(e.shadow['tower'][0]['value'],768)
        for _ in range(100):
            if state['gameOver']: break
            before=game.observation(state)
            action=e.next_action(before)
            self.assertEqual(action,{'kind':'drop'})
            state=game.apply(state,action)
            e.accept(before,action,game.observation(state))
        self.assertTrue(state['gameOver'])
        with self.assertRaises(RouteFailure): e.next_action(game.observation(state))
        e.close()

    def test_below_boundary_alignment_costs_one_drop(self):
        e=self.executor({'status':'error','error':'out-of-model-board'})
        s=game.new_game(3)
        s['tower']=[game.tile(s,v) for v in [2,24]]
        e.fixed_ids={s['tower'][1]['id']}
        obs=game.observation(s)
        action=e.next_action(obs)
        self.assertEqual(action,{'kind':'up'})
        after=game.apply(s,action)
        e.accept(obs,action,game.observation(after))
        self.assertEqual(after['drops'],1)
        e.close()

    def test_edge_difference_discards_macro_tail(self):
        board=lambda values:{'fpos':0,'blocks':[{'value':v,'span':1,'combo':False} for v in values]}
        e=self.executor({'status':'ok','success':False,'board':board([4,8]),
                         'ops':[{'kind':'edge','board':board([4])},{'kind':'drop','board':board([4,8])}]})
        s=game.new_game(4)
        s['tower']=[game.tile(s,24),game.tile(s,10),game.tile(s,12,kind='group',physicalCount=2,members=[]),game.tile(s,20)]
        e.fixed_ids={s['tower'][0]['id']}
        obs=game.observation(s)
        action=e.next_action(obs)
        self.assertEqual(action,{'kind':'edge'})
        self.assertEqual(e.queue,[])
        self.assertIsNone(e.macro_board)
        after=game.apply(s,action)
        e.accept(obs,action,game.observation(after))
        self.assertEqual(game.signature(after),[(24,1,'tile'),(2,1,'tile'),(20,1,'tile')])
        e.close()

    def test_edge_rechecks_merged_physical_value(self):
        for values, expected in [([10, 15, 24], [2, 24]),
                                 ([240, 244, 40], [8])]:
            with self.subTest(values=values):
                state=game.new_game(4)
                state['tower']=[game.tile(state,v) for v in values]
                after=game.apply(state,{'kind':'edge'})
                self.assertEqual([tile['value'] for tile in after['tower']],expected)

    def test_group_that_normalizes_to_ordinary_gets_separate_extension(self):
        board={'fpos':0,'blocks':[{'value':16,'span':1,'combo':False}]}
        reply={'status':'ok','success':True,'board':board,
               'ops':[{'kind':'group','l':0,'r':1,'board':board}]}
        e=self.executor(reply)
        e.route['target']=96
        e.leaves[0].update(target=16,exit='extend')
        s=game.new_game(9)
        s['tower']=[game.tile(s,v) for v in [48,32,2,6,8]]
        e.fixed_ids={t['id'] for t in s['tower'][:2]}
        first=e.next_action(game.observation(s))
        self.assertEqual(first,{'kind':'group','indices':[2,3]})
        self.assertEqual(e.queue,[{'kind':'group','indices':[1,2]}])
        after=game.apply(s,first)
        e.accept(game.observation(s),first,game.observation(after))
        second=e.next_action(game.observation(after))
        final=game.apply(after,second)
        e.accept(game.observation(after),second,game.observation(final))
        self.assertIsNone(e.next_action(game.observation(final)))
        self.assertEqual(game.signature(final),[(96,1,'tile')])
        e.close()

    def test_completed_ordinary_extension_bypasses_dictionary(self):
        e=self.executor({'status':'error','error':'out-of-model-board'})
        e.route['target']=96
        e.leaves[0].update(target=16,exit='extend')
        s=game.new_game(9)
        s['tower']=[game.tile(s,v) for v in [48,32,16,8]]
        e.fixed_ids={t['id'] for t in s['tower'][:2]}
        action=e.next_action(game.observation(s))
        self.assertEqual(action,{'kind':'group','indices':[1,2]})
        after=game.apply(s,action)
        e.accept(game.observation(s),action,game.observation(after))
        self.assertIsNone(e.next_action(game.observation(after)))
        self.assertEqual(game.signature(after),[(96,1,'tile'),(8,1,'tile')])
        e.close()

    def test_alignment_can_complete_match(self):
        e=self.executor({'status':'error','error':'out-of-model-board'})
        e.route['target']=96
        e.leaves[0].update(target=16,exit='match')
        s=game.new_game(9)
        s['queue'][:2]=[8,10]
        s['tower']=[game.tile(s,v) for v in [8,48,16]]
        e.fixed_ids={t['id'] for t in s['tower'][1:]}
        action=e.next_action(game.observation(s))
        self.assertEqual(action,{'kind':'up'})
        self.assertIsNone(e.failure_reason)
        after=game.apply(s,action)
        self.assertEqual(game.signature(after),[(48,1,'tile'),(32,1,'tile')])
        e.accept(game.observation(s),action,game.observation(after))
        self.assertEqual(e.stage,1)
        self.assertEqual(e.fixed_ids,{t['id'] for t in after['tower']})
        e.close()


class GameTests(unittest.TestCase):
    def test_observation_has_no_future_or_rng(self):
        obs=game.observation(game.new_game(1))
        self.assertEqual(len(obs['queue']),2)
        self.assertNotIn('seed',obs)
        self.assertNotIn('rngState',obs)
        self.assertNotIn('lastRandomValue',obs)

    def test_extension384(self):
        s=game.new_game(1)
        s['tower']=[game.tile(s,v) for v in [384,256,32,96]]
        Executor._check_extension(game.observation(s),[1,2,3])
        out=game.apply(s,{'kind':'group','indices':[1,2,3]})
        self.assertEqual(game.signature(out),[(768,1,'tile')])
        self.assertEqual(out['drops'],0)
        s['tower'][0]['value']=240
        with self.assertRaises(IncompatibleState):
            Executor._check_extension(game.observation(s),[1,2,3])

    def test_rotate_still_drops_after_merge(self):
        s=game.new_game(2)
        s['tower']=[game.tile(s,v) for v in [2,4,2]]
        out=game.apply(s,{'kind':'down'})
        self.assertEqual(out['drops'],1)
        self.assertEqual(len(out['queue']),4)

    def test_censored_samples_do_not_look_like_failures(self):
        r=summarize([{'outcome':'success','drops':5},{'outcome':'limit','drops':100}])
        self.assertIsNone(r['expectedTotalDrops'])
        self.assertFalse(r['valid'])

    def test_seeded_parity_with_pinned_website(self):
        root=Path(__file__).resolve().parents[2]
        script=root/'automation/tests/parity.mjs'
        output=subprocess.check_output(['node',str(script)],text=True,encoding='utf-8')
        cases=json.loads(output)
        for case in cases:
            s=game.new_game(case['seed'])
            for action in case['actions']:
                s=game.apply(s,action)
            actual={'tower':game.signature(s),'queue':s['queue'],'rngState':s['rngState'],
                    'drops':s['drops'],'actions':s['actions'],'gameOver':s['gameOver']}
            expected=case['result']
            actual['tower']=[list(t) for t in actual['tower']]
            self.assertEqual(actual,expected)


if __name__=='__main__':
    unittest.main()
