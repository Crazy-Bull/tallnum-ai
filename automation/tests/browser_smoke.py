"""Opt-in real page input/observation parity; never uses an existing profile."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.deps'))
from automation.browser import BrowserAdapter
from automation import game
from automation.common import atomic_json

directory=Path('automation/runs/browser-smoke')
adapter=BrowserAdapter(directory,headless=True,fast_animations=True)
count=0
restarts=0
try:
    before=adapter.new_game()
    for step in range(100):
        if before['gameOver']:
            before=adapter.new_game()
            restarts+=1
        options=[{'kind':'drop'},{'kind':'up'},{'kind':'down'},{'kind':'edge'}]
        options.extend({'kind':'group','indices':[i,i+1]} for i in range(len(before['tower'])-1))
        selected=None
        for offset in range(len(options)):
            action=options[(step*7+offset)%len(options)]
            try:
                predicted=game.predict(before,action)
                selected=action
                break
            except ValueError:
                continue
        after=adapter.perform(selected,before)
        assert game.signature(after)==game.signature(predicted),(before,selected,predicted,after)
        assert after['drops']==predicted['drops'] and after['actions']==predicted['actions']
        assert after['gameOver']==predicted['gameOver']
        before=after
        count+=1
        print(json.dumps({'checked':count,'restarts':restarts}),flush=True)
    atomic_json(directory/'result.json',{'actionsChecked':count,'restarts':restarts,'passed':True})
finally:
    adapter.close()
