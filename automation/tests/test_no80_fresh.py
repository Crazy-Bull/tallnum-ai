import unittest
from automation import game
from automation.no80_full_game import fresh_play


class FreshTests(unittest.TestCase):
    def test_browser_uses_the_same_recovery_controller(self):
        from automation.execution import create_executor
        from automation.entry_recovery import RecoveryExecutor
        from automation.opening128_40 import ContractExecutor
        route={'version':2,'kind':'stages','cells':10,'target':10240,
               'steps':[],'browserOpeningContract':True,'entryRecovery':True}
        self.assertIsInstance(create_executor(route,{'policies':[]}),RecoveryExecutor)
        self.assertIsInstance(create_executor({**route,'entryRecovery':False},{'policies':[]}),ContractExecutor)

    def test_no_saved_prefix_or_random_override(self):
        class Controller:
            route={'cells':10,'target':8}
            entry_bridge_events=[]
            failure_reason=None
            failure_context=None
            def reset(self):self.stage=0
            def next_action(self,obs):
                self.seen=obs
                return {'kind':'drop'}
            def accept(self,*args):self.stage+=1
        controller=Controller();result=fresh_play(42,controller,20)
        self.assertEqual(result['replay']['initial'],game.new_game(42,10))
        self.assertEqual(result['record']['outcome'],'success')
        state=game.new_game(42,10)
        for row in result['replay']['trace']:
            state=game.apply(state,row['action'])
            self.assertEqual(row['rngState'],state['rngState'])
            self.assertEqual(row['queue'],state['queue'])
            self.assertEqual(row['board'],game.signature(state))
        self.assertEqual(len(controller.seen['queue']),2)


if __name__=='__main__':unittest.main()
