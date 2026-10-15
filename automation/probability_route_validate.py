"""Fresh seeded games for arbitrary routes, with probability-only decisions."""
import argparse
from collections import Counter
import gzip
import json
import os
from pathlib import Path
import subprocess

from .common import atomic_json, fingerprint
from .entry_recovery import RecoveryExecutor
from .library import PolicyWorker
from .no80_full_game import fresh_play
from .probability_route_execution import configure_recovery

ROOT=Path(__file__).resolve().parents[1]


def validate(route_path,catalog_path,out,attempts=100,action_budget=100000):
    route=json.loads(Path(route_path).read_text(encoding='utf-8'))
    catalog=json.loads(Path(catalog_path).read_text(encoding='utf-8'))
    # Preserve the planner's explicit allow-list decision. Never silently add
    # excluded rescue definitions or overwrite a correctly keyed mapping.
    if 'bufferRescuePolicies' not in route:
        configure_recovery(route,catalog)
    used={s['policy'] for s in route['steps'] if s['kind']=='leaf'}
    used.update(i for ids in route.get('bufferRescuePolicies',{}).values() for i in ids)
    catalog={'policies':[p for p in catalog['policies'] if p['id'] in used]}
    if {p['id'] for p in catalog['policies']}!=used:raise ValueError('Missing route policy')
    def factory(item):
        if not item.get('pendingValue') or not item.get('disableStaticFallback'):
            raise ValueError('Probability-only simulation requires pending tables without static fallback')
        if item.get('cells',5)<5 or item['target']<24:raise ValueError('Invalid template')
        return PolicyWorker(item)
    factory.transient_query_cache=True
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ['PATH']
    os.environ['TALLNUM_POLICY_CACHE_MB']='4096'
    out=Path(out);(out/'games').mkdir(parents=True,exist_ok=True)
    atomic_json(out/'executed-route.json',route)
    baseline=ROOT/'automation/runs/six-strict-single-002/validation-100-entry-gate-fix/main-ledger.jsonl'
    seeds=[json.loads(row)['seed'] for row in baseline.read_text().splitlines()][:attempts]
    config={'routeSha256':fingerprint(route_path),'catalogSha256':fingerprint(catalog_path),
            'seeds':seeds,'probabilityOnly':True,'freshStart':True,'recovery':True,
            'visiblePreviews':2,'forcedDraws':False,'actionBudget':action_budget,
            'sources':{name:fingerprint(ROOT/'automation'/name) for name in
                       ('probability_route_validate.py','game.py','route_runtime.py',
                        'entry_recovery.py','entry_bridge.py','library.py','no80_full_game.py',
                        'probability_route_execution.py')}}
    config_path=out/'configuration.json'
    if config_path.exists() and json.loads(config_path.read_text())!=config:raise ValueError('Run identity changed')
    atomic_json(config_path,config)
    executor=RecoveryExecutor(route,catalog,factory)
    records=[]
    try:
        for seed in seeds:
            path=out/'games'/f'{seed}.json.gz'
            if path.exists():
                with gzip.open(path,'rt',encoding='utf-8') as stream:result=json.load(stream)
            else:
                try:result=fresh_play(seed,executor,action_budget)
                except Exception as error:
                    atomic_json(out/'interruption.json',getattr(error,'interrupted_game',{'reason':str(error)}))
                    raise
                result['record']['templateCalls']=executor.template_calls[:]
                result['record']['recoveryEvents']=executor.recovery_events[:]
                result['record']['bufferRescues']=executor.buffer_rescue_events[:]
                result['record']['connectionAlignments']=executor.connection_events[:]
                temporary=path.with_suffix('.tmp')
                with gzip.open(temporary,'wt',encoding='utf-8',compresslevel=3) as stream:
                    json.dump(result,stream,separators=(',',':'),allow_nan=False)
                temporary.replace(path)
            records.append(result['record']);del result
            report={'target':route['target'],'completed':len(records),'requested':attempts,
                    'successes':sum(r['outcome']=='success' for r in records),
                    'failureReasons':dict(Counter(r['reason'] for r in records if r['outcome']!='success'))}
            report['successRate']=report['successes']/len(records)
            atomic_json(out/'progress.json',report)
            print(json.dumps(report),flush=True)
    finally:executor.close()
    validation=out/'validation.json.gz'
    with gzip.open(validation,'wt',encoding='utf-8',compresslevel=3) as stream:
        stream.write('{"reports":[{"replays":[')
        for index,seed in enumerate(seeds):
            if index:stream.write(',')
            with gzip.open(out/'games'/f'{seed}.json.gz','rt',encoding='utf-8') as source:
                replay=json.load(source)['replay']
            json.dump(replay,stream,separators=(',',':'))
        stream.write(']}]}')
    check=subprocess.run(['node','--max-old-space-size=512',str(ROOT/'automation/binary_random_check.mjs'),
                          str(validation),'--discard-action-log'],capture_output=True,text=True)
    if check.returncode:raise RuntimeError(check.stdout+check.stderr)
    report.update(complete=len(records)==attempts,
                  originalEngineCheck=json.loads(Path(str(validation)+'.engine-check.json').read_text()),
                  records=records)
    atomic_json(out/'summary.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--route',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--attempts',type=int,default=100)
    args=parser.parse_args()
    if not 1<=args.attempts<=100:parser.error('attempts must be 1..100')
    validate(args.route,args.catalog,args.out,args.attempts)


if __name__=='__main__':main()
