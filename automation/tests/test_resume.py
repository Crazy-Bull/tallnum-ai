import json
from pathlib import Path
import tempfile
import unittest

from automation import game
from automation.runtime import Executor
from automation.resume import restore_executor


class Worker:
    def __init__(self,item): pass
    def close(self): pass
    def query(self,active,fpos,queue):
        before={'tower':active,'queue':queue,'numberSet':'standard','towerLimit':7,
                'poolVersion':2,'actions':0,'drops':0,'gameOver':False}
        values=game.predict(before,{'kind':'down'})['tower']
        board={'fpos':1,'blocks':[{'value':t['value'],'span':t['physicalCount'],'combo':t['kind']=='group'} for t in values]}
        return {'status':'ok','success':False,'ops':[{'kind':'down','board':board}],'board':board}


class ResumeTests(unittest.TestCase):
    def fixture(self):
        route={'id':'leaf','kind':'leaf','policy':'p','target':24,'cells':5,'exit':'single'}
        catalog={'policies':[{'id':'p','states':1}]}
        executor=Executor(route,catalog,Worker)
        state=game.new_game(100000)
        state['queue']=[6,10,15,8]
        records=[]
        for _ in range(2):
            before=game.observation(state)
            action=executor.next_action(before)
            state=game.apply(state,action)
            after=game.observation(state)
            executor.accept(before,action,after,legacy_opening=True)
            records.append({'before':before,'action':action,'after':after})
        executor.close()
        return route,catalog,state,records

    def test_old_journal_restores_the_existing_route_and_new_gap_behavior(self):
        route,catalog,state,records=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'actions.jsonl'
            path.write_text(''.join(json.dumps(r)+'\n' for r in records))
            e=restore_executor(route,catalog,path,game.observation(state),Worker)
            self.assertEqual(e.virtual_gap,0)
            before=game.observation(state)
            action=e.next_action(before)
            after=game.observation(game.apply(state,action))
            e.accept(before,action,after)
            self.assertEqual(e.virtual_gap,1)
            e.close()

    def test_already_executed_unlogged_action_is_confirmed_and_saved(self):
        route,catalog,state,records=self.fixture()
        state=game.apply(state,{'kind':'down'})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'actions.jsonl'
            path.write_text(''.join(json.dumps(r)+'\n' for r in records))
            e=restore_executor(route,catalog,path,game.observation(state),Worker)
            rows=[json.loads(r) for r in path.read_text().splitlines()]
            self.assertEqual(len(rows),3)
            self.assertTrue(rows[-1]['recovered'])
            self.assertEqual(rows[-1]['after']['drops'],3)
            e.close()
