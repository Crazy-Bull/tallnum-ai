"""Run the unchanged real opening and the candidate through one controller."""
from copy import deepcopy
import json

from . import game
from .opening128_40 import build
from .single_six import use_single_six
from .play10240 import OPENING
from .validate_entry_bridge import row
from .no80_route import OUT


def full_route(suffix,catalog,entry_recovery=True,opening_catalog_override=None):
    source=json.loads(OPENING.read_text(encoding='utf-8'))
    opening,opening_catalog=use_single_six(*build(source))
    if opening_catalog_override is not None:
        expected={p['id'] for p in opening_catalog['policies']}
        actual={p['id'] for p in opening_catalog_override['policies']}
        if expected!=actual:raise ValueError('Opening probability catalog does not match route policies')
        opening_catalog=opening_catalog_override
    # Historical static mode only: probability mode has no fixed query cache.
    elif (OUT/'min24-cache-builder.exe').exists():
        for policy in opening_catalog['policies']:
            policy['cacheBuilderNative']=str(OUT/'min24-cache-builder.exe')
    if opening['completionContract']!=suffix['initialPrefix']:
        raise ValueError('Opening/continuation contracts differ')
    route=deepcopy(suffix)
    route.update(id=suffix['id']+'-full-opening',initialPrefix=[],
                 steps=opening['steps']+suffix['steps'],
                 releaseAtStage=opening['releaseAtStage'],browserOpeningContract=True,
                 openingSteps=len(opening['steps']),entryRecovery=entry_recovery,
                 completionContract=[[suffix['target'],1,False]])
    policies={p['id']:p for p in catalog['policies']+opening_catalog['policies']}
    return route,{'policies':list(policies.values())}


def fresh_play(seed,executor,max_actions=100000):
    state=game.new_game(seed,executor.route['cells']);initial=deepcopy(state)
    executor.reset();trace=[];milestones={};context=None
    target=executor.route['target'];outcome,reason='limit','action-budget'
    for count in range(max_actions+1):
        ordinary={t['value'] for t in state['tower'] if t['kind']=='tile'}
        for value in (80,128,160,320,640,1280,2560,5120,target):
            if value in ordinary:milestones.setdefault(str(value),state['drops'])
        if target in ordinary:
            outcome,reason='success','';break
        if state['gameOver']:
            outcome,reason='failure',executor.failure_reason or 'actual-game-over';break
        if count==max_actions:break
        try:
            before=game.observation(state);action=executor.next_action(before)
            if executor.failure_reason and context is None:context=deepcopy(executor.failure_context)
            if action is None:raise ValueError('Executor finished without actual target')
            state=game.apply(state,action);trace.append(row(state,action))
            executor.accept(before,action,game.observation(state))
        except Exception as error:
            error.interrupted_game={'seed':seed,'infrastructureFailure':True,'reason':str(error),
                'stage':executor.stage,'checkpoint':state,
                'step':executor.route.get('steps',[])[executor.stage]
                       if executor.stage<len(executor.route.get('steps',[])) else None,
                'replay':{'seed':seed,'initial':initial,'trace':trace}}
            raise
        if count and count%2000==0:
            print(json.dumps({'seed':seed,'drops':state['drops'],'stage':executor.stage,'freshStart':True}),flush=True)
    record={'seed':seed,'outcome':outcome,'reason':reason,'drops':state['drops'],
            'actions':state['actions'],'stage':executor.stage,'milestones':milestones,
            'joined40':executor.stage>=executor.route.get('openingSteps',0),
            'failureContext':context,'board':game.signature(state),
            'unlocked':state['unlocked'][:],'entryBridges':deepcopy(executor.entry_bridge_events)}
    return {'record':record,'replay':{'seed':seed,'initial':initial,'trace':trace,'outcome':outcome}}
