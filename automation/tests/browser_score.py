"""Opt-in real Chrome regression: finish a dead policy and keep the score panel."""
from pathlib import Path
import json
import time
from unittest.mock import patch

from automation.browser import BrowserAdapter, play
from automation.common import atomic_json, event
from automation.runtime import Executor

directory=Path('automation/runs/browser-score-regression')
control=directory/'control.json'
atomic_json(control,{'mode':'run'})
class DeadWorker:
    def __init__(self,item): pass
    def query(self,*args): return {'status':'dead'}
    def close(self): pass
leaf={'id':'leaf','kind':'leaf','policy':'dead','target':24,'cells':5,'exit':'match'}
route={'id':'route','kind':'binary','target':48,'children':[leaf]}
executor=Executor(route,{'policies':[{'id':'dead','states':1}]},DeadWorker)
adapter=BrowserAdapter(directory,headless=True,fast_animations=True,fixture_seed=13)
initial=adapter.new_game()
adapter.perform({'kind':'drop'},initial)
saved=adapter.read()
adapter.close()
adapter=BrowserAdapter(directory,headless=True,fast_animations=True)
assert adapter.read()==saved,'Opening the existing Chrome profile reset the saved round'

ended_at=[None]
ended_observation=[None]
def capture_event(kind,**data):
    event(kind,**data)
    if kind!='round-ended': return
    ended_at[0]=time.monotonic()
    assert not adapter.page.is_closed()
    observation=adapter.read()
    assert observation['gameOver']
    assert '数字塔已满' in adapter.page.locator('#tallnum-stage').inner_text()
    assert observation['actions']>saved['actions']
    ended_observation[0]=observation
    adapter.page.screenshot(path=str(directory/'game-over.png'))

restart=adapter.restart_game
def verify_restart():
    elapsed=time.monotonic()-ended_at[0]
    assert elapsed>=10,elapsed
    record=json.loads((directory/'rounds.jsonl').read_text(encoding='utf-8').splitlines()[-1])
    assert record['drops']==ended_observation[0]['drops'] and not record['success']
    assert record['settlementSeconds']==10
    fresh=restart()
    assert fresh['actions']==0 and fresh['drops']==0
    atomic_json(directory/'result.json',{'passed':True,'initial':saved,'final':ended_observation[0],
               'settlementElapsedSeconds':elapsed,'newGame':fresh,'record':record})
    atomic_json(control,{'mode':'stop'})
    return fresh

with patch('automation.browser.BrowserAdapter',return_value=adapter), patch('automation.browser.Executor',return_value=executor), patch('automation.browser.event',side_effect=capture_event), patch.object(adapter,'restart_game',side_effect=verify_restart):
    play(route,{},directory,control,headless=True,finish_current_game=True)
print('Real Chrome score panel, ten-second hold, round journal and restart passed',flush=True)
