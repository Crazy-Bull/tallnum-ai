"""Replay a measured collision and check the revised leaf on real states."""
import json
import os
from pathlib import Path
import shutil

from . import game
from .no80_route import ROOT, OUT
from .route_runtime import StageExecutor
from .library import PolicyWorker
from .common import atomic_json


def main():
    old=json.loads((OUT/'validation-v1-prefix/games/1121083590.json').read_text())
    context=old['record']['failureContext']
    state=game.new_game(old['replay']['seed'],10)
    for row in old['replay']['trace']:
        if [list(x) for x in game.signature(state)]==context['board'] and state['queue'][:2]==context['queue']:break
        state=game.apply(state,row['action'])
    else:raise ValueError('Missing failure entry')
    route=json.loads((OUT/'route.json').read_text())
    step=route['steps'][context['stage']]
    catalog=json.loads((OUT/'catalog-dynamic.json').read_text())
    item=next(p for p in catalog['policies'] if p['id']==step['policy'])
    item.update(realBoardAlternatives=True,pendingNative=str(ROOT/'automation/pending_value_realboard.exe'))
    shadow=OUT/'regression-policy.bin'
    shutil.copyfile(item['policy'],shadow);item['policy']=str(shadow)
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ['PATH']
    executor=StageExecutor({'kind':'stage','towerLimit':10,'target':-1,'children':[step]},catalog)
    executor.fixed_ids={t['id'] for t in state['tower'] if t['value'] in (5120,18)}
    trace=[]
    try:
        for _ in range(200):
            obs=game.observation(state);action=executor.next_action(obs)
            if action is None or executor.failure_reason:break
            state=game.apply(state,action);executor.accept(obs,action,game.observation(state))
            trace.append({'action':action,'board':game.signature(state)})
        result={'finished':executor.stage==1,'failure':executor.failure_reason,'actions':len(trace),
                'excludedPosts':sum(map(len,executor.real_board_excluded.values())),
                'board':game.signature(state),'trace':trace,'searchEvents':executor.search_events}
        atomic_json(OUT/'collision-regression.json',result)
        print(json.dumps({k:v for k,v in result.items() if k not in ('trace','searchEvents')}),flush=True)
    finally:executor.close()


if __name__=='__main__':main()
