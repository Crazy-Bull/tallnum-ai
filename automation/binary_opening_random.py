"""Test a binary continuation after a previously verified real 40 opening."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import time

from . import game
from .binary_random import compile_route, ephemeral_worker_factory
from .common import atomic_json, fingerprint
from .full10240 import bind40
from .route_runtime import RouteExecutor
from .validation import summarize


def run(plan, weights, opening, batch='main', max_actions=20000, output=None):
    if opening.get('originalEngineCheck',{}).get('games',0)<100:
        raise ValueError('Opening needs independently checked real replays')
    source=next(r for r in opening['reports'] if r['batch']==batch)
    if source['attempts']!=100 or source['forcedDraws'] or source.get('visiblePreviews',2)!=2:
        raise ValueError('Expected 100 honest two-preview opening games')
    route,catalog=compile_route(plan,weights,checkpoint=40)
    if any(int(s['template'].split(':')[1])>64 for s in route['steps'] if s['kind']=='leaf'):
        raise ValueError('Continuation exceeds five-cell 64')
    factory=ephemeral_worker_factory(Path(output).parent/'worker-cache' if output else Path('worker-cache'))
    executor=RouteExecutor(route,catalog,factory)
    records=[];replays=[];started=time.monotonic()
    try:
        for index,(old,replay) in enumerate(zip(source['records'],source['replays'])):
            state=deepcopy(replay['initial'])
            trace=deepcopy(replay['trace'])
            for event in trace:
                state=game.apply(state,event['action'])
                if game.signature(state)!=[tuple(x) for x in event['board']] or state['rngState']!=event['rngState']:
                    raise ValueError('Opening replay changed')
            outcome=old['outcome'];reason=old['reason'];joined=False
            if outcome=='success':
                bind40(executor,game.observation(state));joined=True
                outcome='limit';reason='action-budget'
                for _ in range(max_actions):
                    if any(t['kind']=='tile' and t['value']==plan['target'] for t in state['tower']):
                        outcome='success';reason='';break
                    if state['gameOver']:
                        outcome='failure';reason=executor.failure_reason or 'actual-game-over';break
                    before=game.observation(state)
                    action=executor.next_action(before)
                    if action is None:
                        outcome='success';reason='';break
                    state=game.apply(state,action)
                    executor.accept(before,action,game.observation(state))
                    trace.append({'action':action,'board':game.signature(state),'queue':state['queue'][:],
                                  'unlocked':state['unlocked'][:],'rngState':state['rngState'],
                                  'gameOver':state['gameOver']})
            records.append({'seed':old['seed'],'outcome':outcome,'reason':reason,'joined40':joined,
                            'drops':state['drops'],'actions':state['actions'],
                            'stage':executor.stage if joined else None,'board':game.signature(state),
                            'unlocked':state['unlocked'][:]})
            replays.append({'seed':old['seed'],'outcome':outcome,'initial':replay['initial'],'trace':trace})
            if output and (index+1)%10==0:
                atomic_json(output,{'complete':False,'completed':index+1,
                                    'successes':sum(r['outcome']=='success' for r in records),
                                    'records':records,'replays':replays})
                print(json.dumps({'completed':index+1,'successes':sum(r['outcome']=='success' for r in records)}),flush=True)
    finally:
        executor.close()
        factory.cleanup()
    report={**summarize(records),'mode':'real-opening','batch':batch,'forcedDraws':False,
            'visiblePreviews':2,'openingJoined':sum(r['joined40'] for r in records),
            'elapsedSeconds':time.monotonic()-started,
            'failureReasons':dict(Counter(r['reason'] for r in records if r['outcome']!='success')),
            'records':records,'replays':replays}
    result={'complete':True,'planSha256':fingerprint(plan['_path']) if '_path' in plan else None,
            'reports':[report]}
    if output:atomic_json(output,result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    parser.add_argument('--weights',type=Path,required=True)
    parser.add_argument('--opening',type=Path,required=True)
    parser.add_argument('--batch',choices=('main','holdout'),default='main')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-actions',type=int,default=20000)
    args=parser.parse_args()
    plan=json.loads(args.plan.read_text());plan['_path']=str(args.plan)
    result=run(plan,json.loads(args.weights.read_text()),json.loads(args.opening.read_text()),
               args.batch,args.max_actions,args.output)
    print(json.dumps({k:v for k,v in result['reports'][0].items() if k not in ('records','replays')},indent=2),flush=True)


if __name__=='__main__':main()
