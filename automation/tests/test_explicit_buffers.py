import tempfile
import unittest
from fractions import Fraction
from automation import game
from automation.route_search import RouteSearch,Block,identity
from automation.route_synthesis import synthesize
from automation.route_runtime import RouteExecutor
from automation.planner import ordinary


class ExplicitBufferTests(unittest.TestCase):
    def search(self,tmp,cap=200):
        return RouteSearch(tmp,{'policies':[]},target=640,max_value=1280,
                           local_template_bounds=True,max_leaf_target=cap,
                           leaf_targets=[*range(2,cap+1,2),15],progress=False)

    def test_nonstandard26_is_not_an_opaque_leaf(self):
        with tempfile.TemporaryDirectory() as tmp,self.search(tmp) as search:
            self.assertFalse(any(op['exit'] in ('single','match') and op['target']==26
                                 for op,_,_ in search.successors((Block(320),))))
            with self.assertRaises(ValueError):search.requirement(26,'single')
            paths,nodes,truncated=synthesize(search,(Block(320),),26)
            self.assertFalse(truncated);self.assertTrue(paths)
            path=paths[0];board=(Block(320),);cost=Fraction(0)
            for step in path['steps']:
                matches=[(op,after,weight) for op,after,weight in search.successors(board)
                         if identity(op)==identity({k:v for k,v in step.items() if k not in ('before','after')})]
                self.assertEqual(len(matches),1)
                op,after,weight=matches[0]
                self.assertEqual(step['before'],[b.json() for b in board])
                if op['kind']=='leaf' and op['exit'] in ('single','match'):self.assertTrue(ordinary(op['target']))
                cost+=weight;board=after
            self.assertEqual(board,(Block(320),Block(26)))
            self.assertEqual(str(cost),path['units'])
            self.assertGreater(cost,26**3)
            self.assertTrue(any(s.get('exit')=='buffer' and s['target']==170 for s in path['steps']))

    def test_current128_leaf_cap_cannot_hide_the26_construction(self):
        with tempfile.TemporaryDirectory() as tmp,self.search(tmp,128) as search:
            paths,nodes,truncated=synthesize(search,(Block(320),),26)
            self.assertFalse(truncated);self.assertFalse(paths)
            self.assertFalse(any(op.get('exit')=='buffer' for op,_,_ in search.successors((Block(320),Block(96),Block(2)))))

    def test_existing_nonstandard_anchor_can_match_with_an_explicit_buffer(self):
        with tempfile.TemporaryDirectory() as tmp,self.search(tmp,128) as search:
            paths,_,_=synthesize(search,(Block(320),Block(26)),26)
            self.assertTrue(paths)
            self.assertEqual(paths[0]['steps'],[{
                'kind':'leaf','target':26,'exit':'buffer','template':'5:26:buffer','purpose':'equal-buffer',
                'before':[[320,1,False],[26,1,False]],'after':[[320,1,False],[52,1,False]]}])

    def runtime_fixture(self,anchor,target,active,after_contract):
        model={'fpos':0,'blocks':[{'value':target,'span':2,'combo':True}]}
        class Worker:
            def __init__(self,item):pass
            def close(self):pass
            def query(self,*args):return {'status':'ok','success':True,'board':model,
                                          'ops':[{'kind':'group','l':0,'r':1,'board':model}]}
        route={'version':2,'kind':'stages','cells':7,'target':after_contract[0][0],
               'initialPrefix':[[anchor,1,False]],'steps':[
                   {'kind':'leaf','target':target,'exit':'buffer','policy':'p','cells':5,
                    'before':[[anchor,1,False]],'after':after_contract}]}
        state=game.new_game(7);state['tower']=[game.tile(state,v) for v in [anchor,*active]]
        runner=RouteExecutor(route,{'policies':[{'id':'p','target':target,'exit':'buffer','maxGoalCells':4,'states':1}]},Worker)
        return runner,state

    def test_buffer_group_then_edge_retains_actual_residual(self):
        runner,state=self.runtime_fixture(96,90,[80,10],[[96,1,False],[90,4,True,True]])
        runner.route['target']=18
        runner.route['steps'].append({'kind':'edge','before':[[96,1,False],[90,4,True,True]],'after':[[18,1,False]]})
        try:
            before=game.observation(state);action=runner.next_action(before)
            self.assertEqual(action,{'kind':'group','indices':[1,2]})
            state=game.apply(state,action);runner.accept(before,action,game.observation(state))
            state['tower'].append(game.tile(state,4))
            before=game.observation(state);action=runner.next_action(before)
            self.assertEqual(action,{'kind':'edge'})
            state=game.apply(state,action);runner.accept(before,action,game.observation(state))
            self.assertEqual(game.signature(state),[(18,1,'tile'),(4,1,'tile')])
            self.assertIsNone(runner.next_action(game.observation(state)))
        finally:runner.close()

    def test_equal_nonstandard_buffer_normalizes_into_ordinary_double(self):
        runner,state=self.runtime_fixture(14,14,[8,6],[[28,1,False]])
        try:
            before=game.observation(state);action=runner.next_action(before)
            self.assertEqual(action,{'kind':'group','indices':[1,2]})
            state=game.apply(state,action);runner.accept(before,action,game.observation(state))
            self.assertEqual(game.signature(state),[(28,1,'tile')])
            self.assertIsNone(runner.next_action(game.observation(state)))
        finally:runner.close()

    def test_composition_prices_single_and_buffer_before_free_edge(self):
        with tempfile.TemporaryDirectory() as tmp,self.search(tmp) as search:
            policies=[]
            for target,kind,p,u,v in ((96,'single',.8,8,2),(90,'buffer',.5,2,1)):
                req=search.requirement(target,kind)
                policies.append({**req,'id':kind,'policy':kind+'.bin','policySha256':'x','variantAggressiveness':0,
                                 'statistics':{'usable':True,'p':p,'u':u,'v':v},
                                 'petsc':{'verified':True,'exitEvaluationRounds':2},'exitSemantics':'success-board-v2'})
            search.catalog={'policies':policies}
            structure={'units':str(96**3+90**3),'steps':[
                {'kind':'leaf','target':96,'exit':'single','template':'5:96:single','before':[],'after':[[96,1,False]]},
                {'kind':'leaf','target':90,'exit':'buffer','template':'5:90:buffer','before':[[96,1,False]],'after':[[96,1,False],[90,4,True,True]]},
                {'kind':'edge','before':[[96,1,False],[90,4,True,True]],'after':[[18,1,False]]}]}
            routes=search.compose(structure)
            self.assertEqual(len(routes),1)
            self.assertAlmostEqual(routes[0]['metrics']['p'],.4)
            self.assertAlmostEqual(routes[0]['metrics']['expectedTotalDrops'],31)


if __name__=='__main__':unittest.main()
