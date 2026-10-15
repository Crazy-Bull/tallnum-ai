import unittest
from automation import game
from automation.no80_single_connections import convert


class OrdinaryConnectionTests(unittest.TestCase):
    def test_ordinary_twelve_then_group_replaces_extension_with_real_operations(self):
        prefix={'kind':'edge','before':[],'after':[]}
        step={'kind':'leaf','exit':'extend','target':12,'policy':'extend','policyCells':5,
              'before':[[5120,1,False],[18,1,False],[6,1,False]],'after':[[5120,1,False],[36,1,False]]}
        policy={'id':'single','target':12,'exit':'single','cells':5,'singleTidyExit':True}
        result,changes=convert({'steps':[prefix,step]},{'policies':[policy]},1)
        self.assertEqual(result['steps'][0],prefix)
        single,group=result['steps'][1:]
        self.assertEqual(single['policyCells'],5)
        self.assertEqual(single['exit'],'single')
        state=game.new_game(9,10)
        state['tower']=[game.tile(state,v) for v in (5120,18,6,12)]
        after=game.apply(state,{'kind':'group','indices':group['indices']})
        self.assertEqual([[t['value'],t['physicalCount'],t['kind']=='group'] for t in after['tower']],step['after'])
        self.assertEqual(changes,[{'previousStage':1,'target':12}])

    def test_equal_ordinary_connection_uses_automatic_merge(self):
        step={'kind':'leaf','exit':'extend','target':64,'policy':'extend','policyCells':5,
              'before':[[5120,1,False],[128,1,False],[64,1,False]],'after':[[5120,1,False],[256,1,False]]}
        policy={'id':'single','target':64,'exit':'single','cells':5,'singleTidyExit':True}
        result,_=convert({'steps':[step]},{'policies':[policy]},0)
        self.assertEqual(len(result['steps']),1)
        self.assertEqual(result['steps'][0]['singleConnectionAfter'],step['after'])


if __name__=='__main__':unittest.main()
