"""Execute a previously successful, explicitly seeded regression fixture
against the real website through normal keyboard/pointer input.
This is an integration test, NOT an unbiased probability measurement.
"""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.deps'))
from automation.browser import BrowserAdapter
from automation.runtime import Executor
from automation.common import atomic_json

parser=argparse.ArgumentParser()
parser.add_argument('--directory',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
validation=json.loads((args.directory/'validation.json').read_text(encoding='utf-8'))
plan=json.loads((args.directory/'plan.json').read_text(encoding='utf-8'))
catalog=json.loads((args.directory/'catalog.json').read_text(encoding='utf-8'))
result=validation.get('holdout') or next(r for r in validation['results'] if r['successes'])
record=next(r for r in result['records'] if r['outcome']=='success')
seed=record['seed']
route=next(r for r in plan['routes'] if r['id']==result['routeId'])
adapter=BrowserAdapter(args.output,headless=True,fast_animations=True,fixture_seed=seed)
executor=Executor(route,catalog)
log=(args.output/'actions.jsonl').open('w',encoding='utf-8')
try:
    before=adapter.new_game()
    for i in range(100000):
        action=executor.next_action(before)
        if action is None:
            adapter.page.screenshot(path=str(args.output/'success.png'))
            atomic_json(args.output/'result.json',{'target':route['target'],'seed':seed,
                'fixture':True,'actions':i,'drops':before['drops'],'observation':before,'passed':True})
            print(json.dumps({'event':'success','target':route['target'],'actions':i,'drops':before['drops']}),flush=True)
            break
        after=adapter.perform(action,before)
        executor.accept(before,action,after)
        log.write(json.dumps({'before':before,'action':action,'after':after},ensure_ascii=False)+'\n');log.flush()
        before=after
        if i%50==0:
            print(json.dumps({'event':'checked','actions':i+1,'drops':after['drops'],'stage':executor.stage}),flush=True)
    else:
        raise RuntimeError('Action budget exceeded')
except Exception as error:
    adapter.page.screenshot(path=str(args.output/'incident.png'))
    atomic_json(args.output/'incident.json',{'error':str(error),'seed':seed})
    raise
finally:
    log.close()
    executor.close()
    adapter.close()
