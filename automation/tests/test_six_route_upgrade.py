import tempfile
import unittest
from automation.binary_routes import BinaryPlanner,verify_tree
from automation.route_search import Block
from automation.tests.test_expected_routes import snapshot
from automation.upgrade640 import upgrade_tree
from automation import game
from automation.runtime import Executor
from automation.route_runtime import StageExecutor


class SixRouteUpgradeTests(unittest.TestCase):
    def test_runtime_does_not_apply_five_cell_cutoff_to_six_policy(self):
        queries=[]
        class Worker:
            def __init__(self,item):pass
            def query(self,board,fpos,queue):queries.append(len(board));return {'status':'dead'}
            def close(self):pass
        state=game.new_game(1,7)
        state['tower']=[game.tile(state,v) for v in (2,4,6,8,10)]
        for cells in (6,5):
            item={'id':'p','target':32,'exit':'single','cells':cells,'maxGoalCells':1}
            leaf={'kind':'leaf','policy':'p','target':32,'exit':'single','policyCells':cells}
            e=Executor({'target':640,'towerLimit':7,'kind':'stage','children':[leaf]}, {'policies':[item]},Worker)
            e.next_action(game.observation(state))
            self.assertEqual(e.failure_reason,'fixed-policy-dead' if cells==6 else 'five-cell-capacity')
            e.close()
        self.assertEqual(queries,[5])

    def test_single_policy_can_finish_real_equal_anchor_match(self):
        class Worker:
            def __init__(self,item):pass
            def query(self,board,fpos,queue):
                goal={'fpos':0,'blocks':[{'value':40,'span':1,'combo':False}]}
                return {'status':'ok','success':True,'board':goal,'ops':[{'kind':'drop','board':goal}]}
            def close(self):pass
        state=game.new_game(1,7)
        state['tower']=[game.tile(state,v) for v in (40,20,10)]
        state['queue']=[10,2,4,6]
        item={'id':'p','target':40,'exit':'match','cells':6,'maxGoalCells':1}
        leaf={'kind':'leaf','policy':'p','target':40,'exit':'match','policyCells':6}
        e=StageExecutor({'target':-1,'towerLimit':7,'kind':'stage','children':[leaf]}, {'policies':[item]},Worker)
        e.fixed_ids={state['tower'][0]['id']}
        before=game.observation(state);action=e.next_action(before)
        after=game.apply(state,action);e.accept(before,action,game.observation(after))
        self.assertEqual(game.signature(after),[(80,1,'tile')])
        self.assertIsNone(e.next_action(game.observation(after)))
        e.close()

    def test_six_policy_requires_six_free_cells(self):
        data=snapshot({'5:32:single':20,'6:32:single':10})
        with tempfile.TemporaryDirectory() as tmp:
            planner=BinaryPlanner(tmp,data,objective="weight",maximum=48)
            try:
                five=planner.leaf(('single',5,32,0))
                six=planner.leaf(('single',6,32,0))
                self.assertEqual(five['template'],'5:32:single')
                self.assertEqual(six['template'],'6:32:single')
                self.assertEqual(verify_tree(six,7,entrance=(Block(80),))['finalBoard'],[[80,1,False],[32,1,False]])
                with self.assertRaises(ValueError):verify_tree(six,7,entrance=(Block(80),Block(16)))
            finally:planner.close()

    def test_ordinary_match_adapter_has_equal_anchor(self):
        tree={'task':['match',6,40,0],'rule':'six-cell-policy','template':'6:40:match','children':[],'cost':'12'}
        self.assertEqual(verify_tree(tree,7,entrance=(Block(40),))['finalBoard'],[[80,1,False]])
        with self.assertRaises(ValueError):verify_tree(tree,7,entrance=(Block(32),))

    def test_replacement_preserves_small_workspace_and_structure(self):
        tree={'task':['single',7,64,0],'rule':'double','cost':'30','children':[
            {'task':['single',7,32,0],'rule':'five-cell-policy','template':'5:32:single','cost':'20','children':[]},
            {'task':['match',5,32,0],'rule':'five-cell-policy','template':'5:32:match','cost':'10','children':[]}]}
        upgraded,changes=upgrade_tree(tree,snapshot({'6:32:single':8,'6:32:match':7}))
        self.assertEqual(len(changes),1)
        self.assertEqual(upgraded['cost'],'18')
        self.assertEqual(upgraded['children'][1]['template'],'5:32:match')
        self.assertEqual(tree['cost'],'30')
