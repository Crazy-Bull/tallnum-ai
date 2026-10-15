"""Audit 100 opening-to-96 trajectories without operating a browser."""
import json
import argparse
from collections import Counter
from pathlib import Path
from automation import game
from automation.common import atomic_json
from automation.library import load_catalog
from automation.runtime import Executor, IncompatibleState, RouteFailure

parser=argparse.ArgumentParser()
parser.add_argument('--directory',type=Path,required=True)
parser.add_argument('--output',default='diagnose-route96.json')
parser.add_argument('--route-index',type=int)
parser.add_argument('--plan-file',type=Path)
args=parser.parse_args()
root=args.directory
routes=json.loads((args.plan_file or root/'plan.json').read_text(encoding='utf-8'))['routes']
if args.route_index is not None:
    route=routes[args.route_index]
else:
    validation=json.loads((root/'validation.json').read_text(encoding='utf-8'))
    route=next(r for r in routes if r['id']==validation['selectedRoute'])
catalog=load_catalog(root,certified_only=True)
executor=Executor(route,catalog)
records=[]
try:
    for seed in range(100000,100100):
        state=game.new_game(seed)
        executor.reset()
        transitions=[]
        queries=[]
        for _ in range(10000):
            before=game.observation(state)
            if executor.stage>=5:
                outcome='success96'; break
            previous=executor.stage
            if executor.fixed_ids is not None and not executor.queue:
                active,fpos,_,fixed=executor._project(before)
                leaf=executor.leaves[previous]
                reply=executor._worker(leaf).query(active,fpos,before['queue'])
                queries.append({'stage':previous,'fpos':fpos,'active':active,'fixed':[before['tower'][i] for i in fixed],
                                'reply':reply,'before':before})
            try:
                action=executor.next_action(before)
                if executor.failure_reason:
                    outcome='route-failure'; break
                state=game.apply(state,action)
                executor.accept(before,action,game.observation(state))
            except (RouteFailure,IncompatibleState) as error:
                outcome=str(error); break
            if executor.stage!=previous:
                transitions.append({'from':previous,'to':executor.stage,'drops':state['drops'],
                                    'observation':game.observation(state)})
        else: outcome='limit'
        records.append({'seed':seed,'outcome':outcome,'reason':executor.failure_reason,'stage':executor.stage,
                        'drops':state['drops'],'transitions':transitions,'lastQueries':queries[-3:],
                        'failureObservation':before})
finally:
    executor.close()
summary={'attempts':len(records),'success96':sum(r['outcome']=='success96' for r in records),
         'reached48':sum(any(t['to']>=2 for t in r['transitions']) for r in records),
         'failures':dict(Counter(f"stage{r['stage']}:{r['reason'] or r['outcome']}" for r in records if r['outcome']!='success96'))}
atomic_json(root/args.output,{'summary':summary,'records':records})
print(json.dumps(summary))
for stage in (2,3,4):
    examples=[r for r in records if r['stage']==stage and r['outcome']!='success96']
    for r in examples[:2]:
        q=r['lastQueries'][-1]
        print(json.dumps({'seed':r['seed'],'stage':stage,'reason':r['reason'],
                          'active':game.signature({'tower':q['active']}),'fpos':q['fpos'],
                          'fixed':game.signature({'tower':q['fixed']}),'reply':q['reply'],
                          'queue':q['before']['queue']},ensure_ascii=False))
