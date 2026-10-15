import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from automation.browser import BrowserAdapter, InputInterrupted, ObservationPending, play, reconcile
from automation.common import atomic_json


class RecoveryTests(unittest.TestCase):
    def check_game_over_is_kept_ten_seconds_logged_then_restarted(self,success=False):
        from automation import game
        from automation.runtime import Executor
        class Worker:
            def __init__(self,item): pass
            def query(self,*args): return {'status':'dead'}
            def close(self): pass
        leaf={'id':'leaf','kind':'leaf','policy':'p','target':24,'cells':5,'exit':'match'}
        route={'id':'route','kind':'binary','target':48,'children':[leaf]}
        executor=Executor(route,{'policies':[{'id':'p','states':1}]},Worker)
        with tempfile.TemporaryDirectory() as tmp:
            control=Path(tmp)/'control.json'
            atomic_json(control,{'mode':'run'})
            instances=[]
            clock=[0.0]
            class Adapter:
                def __init__(self,*args,**kwargs):
                    self.page=self; self.games=0; self.closed=False
                    instances.append(self)
                def new_game(self):
                    self.games+=1; self.state=game.new_game(13)
                    if success: self.state['tower']=[game.tile(self.state,48)]
                    if self.games==2: atomic_json(control,{'mode':'stop'})
                    return self.read()
                def read(self): return game.observation(self.state)
                def restart_game(self):
                    self.assertions=(clock[0]>=10)
                    assert self.assertions
                    records=(Path(tmp)/'rounds.jsonl').read_text(encoding='utf-8').splitlines()
                    assert len(records)==1
                    record=json.loads(records[0])
                    assert record['drops']==self.state['drops'] and record['success']==success
                    assert record['dropsToTarget']==(0 if success else None)
                    return self.new_game()
                def perform(self,action,before):
                    self.assertions=(action=={'kind':'drop'})
                    assert self.assertions
                    self.state=game.apply(self.state,action)
                    return self.read()
                def is_closed(self): return False
                def close(self): self.closed=True
            def tick(_):
                adapter=instances[0]
                self.assertFalse(adapter.closed)
                self.assertTrue(adapter.state['gameOver'])
                self.assertEqual(adapter.games,1)
                self.assertTrue(json.loads((Path(tmp)/'game-over.json').read_text())['observation']['gameOver'])
                self.assertFalse((Path(tmp)/'rounds.jsonl').exists())
                clock[0]+=1
            with patch('automation.browser.BrowserAdapter',Adapter), patch('automation.browser.Executor',return_value=executor), patch('automation.browser.time.sleep',tick), patch('automation.browser.time.monotonic',side_effect=lambda:clock[0]), patch('automation.browser.event'):
                play(route,{},tmp,control)
            self.assertEqual(instances[0].games,2)

    def test_failed_round_waits_ten_seconds_and_logs_once(self):
        self.check_game_over_is_kept_ten_seconds_logged_then_restarted()

    def test_successful_round_continues_to_game_over_and_logs_once(self):
        self.check_game_over_is_kept_ten_seconds_logged_then_restarted(True)

    def test_reconcile_rejects_manual_change(self):
        before={'actions':3,'drops':2,'tower':[2], 'revision':4}
        self.assertEqual(reconcile(before,dict(before,revision=5)), 'unchanged')
        self.assertEqual(reconcile(before,dict(before,actions=4)), 'accepted')
        with self.assertRaises(InputInterrupted):
            reconcile(before,dict(before,tower=[4]))

    def test_stop_at_target_preserves_board_without_continuation_or_restart(self):
        from unittest.mock import MagicMock
        from automation import game
        state=game.new_game(13)
        state['tower']=[game.tile(state,640)]
        observation=game.observation(state)
        adapter=MagicMock()
        adapter.attached=False
        adapter.new_game.return_value=observation
        adapter.read.return_value=observation
        executor=MagicMock()
        with tempfile.TemporaryDirectory() as tmp:
            control=Path(tmp)/'control.json'
            atomic_json(control,{'mode':'run','stopAfterTarget':True})
            with patch('automation.browser.BrowserAdapter',return_value=adapter),patch('automation.browser.Executor',return_value=executor),patch('automation.browser.event'):
                play({'target':640},{},tmp,control)
            executor.next_action.assert_not_called()
            adapter.perform.assert_not_called()
            adapter.restart_game.assert_not_called()
            checkpoint=json.loads((Path(tmp)/'checkpoint.json').read_text())
            self.assertEqual(checkpoint['phase'],'target-reached')
            self.assertEqual(checkpoint['observation'],observation)
            self.assertEqual(json.loads(control.read_text())['mode'],'stop')

    def check_recovery(self, accepted_before_timeout, automatic=False):
        with tempfile.TemporaryDirectory() as tmp:
            control=Path(tmp)/'control.json'
            atomic_json(control,{'mode':'run'})
            before={'actions':0,'drops':0,'tower':[2]}
            after={'actions':1,'drops':1,'tower':[4]}
            class Adapter:
                def __init__(self,*args,**kwargs):
                    self.page=self; self.calls=0; self.state=before; self.closed=False
                    instances.append(self)
                def new_game(self): return before
                def read(self): return self.state
                def is_closed(self): return False
                def perform(self,action,observed):
                    self.calls+=1
                    if self.calls==1:
                        if accepted_before_timeout: self.state=after
                        raise (ObservationPending if automatic else InputInterrupted)('focus changed')
                    self.state=after
                    return after
                def close(self): self.closed=True
            class Executor:
                stage=0
                def __init__(self,*args): self.accepted=False
                def next_action(self,obs): return None if self.accepted else {'kind':'drop'}
                def accept(self,b,a,c):
                    self.assertions=(b==before and c==after)
                    assert self.assertions
                    self.accepted=True
                def close(self): pass
            def resume(_):
                self.assertFalse(instances[0].closed)
                self.assertEqual(json.loads(control.read_text())['mode'],'run' if automatic else 'paused')
                if not automatic: atomic_json(control,{'mode':'run'})
            instances=[]
            def stop_after_accept(kind,**kwargs):
                if kind=='action': atomic_json(control,{'mode':'stop'})
            with patch('automation.browser.BrowserAdapter',Adapter), patch('automation.browser.Executor',Executor), patch('automation.browser.time.sleep',resume), patch('automation.browser.event',side_effect=stop_after_accept):
                play({'target':4},{},tmp,control)
            self.assertEqual(instances[0].calls,1 if accepted_before_timeout else 2)
            records=(Path(tmp)/'actions.jsonl').read_text(encoding='utf-8').splitlines()
            self.assertEqual(len(records),1)
            self.assertEqual(json.loads(records[0])['totalDrops'],1)

    def test_lost_input_preserved_until_resume(self): self.check_recovery(False)
    def test_accepted_input_not_repeated_after_timeout(self): self.check_recovery(True)

    def test_tab_switch_accepted_input_recovers_without_pausing_or_repeating(self):
        self.check_recovery(True,automatic=True)

    def test_tab_switch_lost_input_recovers_without_pausing(self):
        self.check_recovery(False,automatic=True)

    def test_save_revision_change_does_not_prevent_stable_read(self):
        from unittest.mock import MagicMock
        a=BrowserAdapter.__new__(BrowserAdapter)
        a.page=MagicMock()
        a.fast_animations=False
        obs={'actions':2,'drops':1,'tower':[{'value':8}], 'revision':5}
        a.page.evaluate.side_effect=[obs,dict(obs,revision=6)]
        a.page.locator.return_value.count.return_value=0
        a.page.locator.return_value.inner_text.return_value='1'
        a.page.locator.return_value.evaluate_all.return_value=[8]
        self.assertEqual(a.read(),dict(obs,revision=6))

    def test_background_animation_timeout_is_recoverable(self):
        from unittest.mock import MagicMock
        a=BrowserAdapter.__new__(BrowserAdapter)
        a.page=MagicMock()
        a.page.locator.return_value.count.return_value=1
        with patch('automation.browser.time.monotonic',side_effect=[0,1,21]):
            with self.assertRaises(ObservationPending): a.read()
        a.page.evaluate.assert_not_called()
