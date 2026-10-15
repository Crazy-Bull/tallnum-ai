"""Resumable paired full-game tests, retaining the measured real opening."""
import argparse
import gzip
import ijson
import json
import os
from pathlib import Path
import subprocess
import shutil
import time

from .binary_random import ephemeral_worker_factory
from .common import atomic_json, fingerprint
from .library import PolicyWorker
from .entry_recovery import RecoveryExecutor
from .no80_route import ROOT, OUT, EVIDENCE, audit
from .route_runtime import RouteExecutor
from .no80_metrics import compact_record, compact_summary as summary
from .validate_entry_bridge import play


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--out',type=Path,default=OUT/'validation-v1')
    parser.add_argument('--catalog',type=Path,default=OUT/'catalog.json')
    parser.add_argument('--route',type=Path,default=OUT/'route.json')
    parser.add_argument('--recovery',action='store_true')
    parser.add_argument('--fresh',action='store_true',help='Execute the opening and entire route from the initial game')
    parser.add_argument('--action-budget',type=int,default=25000)
    parser.add_argument('--compress-replays',action='store_true')
    parser.add_argument('--worker-cache-mb',type=int,default=4096)
    parser.add_argument('--static-cache-dir',type=Path,help='Scratch location for unchanged opening query caches')
    parser.add_argument('--opening-catalog',type=Path,help='Probability-table policies for the unchanged opening steps')
    parser.add_argument('--probability-only',action='store_true',help='Reject every fixed-policy worker and fallback')
    args=parser.parse_args()
    def read(p):
        if str(p).endswith('.gz'):
            with gzip.open(p,'rt',encoding='utf-8') as stream:return json.load(stream)
        return json.loads(Path(p).read_text(encoding='utf-8'))
    route,catalog=read(args.route),read(args.catalog)
    if args.fresh:
        from .no80_full_game import full_route,fresh_play
        route,catalog=full_route(route,catalog,args.recovery,
                                 read(args.opening_catalog) if args.opening_catalog else None)
    elif args.opening_catalog:raise ValueError('Opening catalog requires --fresh')
    if args.probability_only:
        missing=[p['id'] for p in catalog['policies']
                 if not p.get('pendingValue') or not p.get('disableStaticFallback')]
        if missing:raise ValueError('Fixed-policy definitions or fallbacks remain: '+', '.join(missing))
    policy_audit=audit(route,catalog)
    args.out.mkdir(parents=True,exist_ok=True)
    (args.out/'games').mkdir(exist_ok=True)
    configuration={'routeSha256':fingerprint(args.route),
                   'catalogSha256':fingerprint(args.catalog),'recovery':args.recovery,
                   'openingSource':str(EVIDENCE),'forcedDraws':False,'visiblePreviews':2,
                   'unchangedPrefixCheckpoint':None if args.fresh else 5120,
                   'freshStart':args.fresh,
                   'actionBudget':args.action_budget,'replayCompression':'gzip' if args.compress_replays else None,
                   'workerCacheMb':args.worker_cache_mb,
                   'staticCacheDirectory':str(args.static_cache_dir.resolve()) if args.static_cache_dir else None,
                   'openingCatalogSha256':fingerprint(args.opening_catalog) if args.opening_catalog else None,
                   'probabilityOnly':args.probability_only,
                   'replayCheckDiscardsDiagnosticActionLog':True,
                   'policyAudit':policy_audit,
                   'sources':{n:fingerprint(ROOT/'automation'/n) for n in
                              ('runtime.py','route_runtime.py','entry_bridge.py','entry_recovery.py',
                               'library.py','no80_validate.py','pending_value_realboard.cpp',
                               'game.py','opening128_40.py','bootstrap10240.py','validate_entry_bridge.py',
                               'stream_replay_report.py','binary_random_check.mjs','vendor/tallnum.mjs',
                               'no80_metrics.py','validate_buffer_rescue.py','no80_full_game.py',
                               'fixed_cache_stream.cpp','native_policy.cpp','binary_random.py',
                               'no80_probability_opening.py','no80_thirteen_planner.py',
                               'no80_peak_tables.py',
                               'single_six.py','play10240.py','execution.py')},
                   'nativeQueries':{str(p['pendingNative']):fingerprint(p['pendingNative'])
                                    for p in catalog['policies'] if p.get('pendingNative')},
                   'cacheBuilders':{str(p['cacheBuilderNative']):fingerprint(p['cacheBuilderNative'])
                                    for p in catalog['policies'] if p.get('cacheBuilderNative')}}
    config=args.out/'configuration.json'
    if config.exists() and read(config)!=configuration:raise ValueError('Run changed; use a new output directory')
    atomic_json(config,configuration)
    for name in configuration['sources']:
        saved=args.out/'sources'/name;saved.parent.mkdir(parents=True,exist_ok=True)
        if not saved.exists():shutil.copyfile(ROOT/'automation'/name,saved)
    atomic_json(args.out/'route.json',route);atomic_json(args.out/'catalog.json',catalog)
    suffix='.json.gz' if args.compress_replays else '.json'
    baseline={r['seed']:r for r in map(json.loads,(EVIDENCE/'main-ledger.jsonl').read_text().splitlines())}
    factory_static=ephemeral_worker_factory(args.static_cache_dir or args.out/'worker-cache',
                                            persistent=args.static_cache_dir is not None)
    shadows=args.out/'policy-shadow'
    shadows.mkdir(exist_ok=True)
    def factory(item):
        if item.get('cells',5)<5 or item['target']<24 or (item.get('cells',5)==5 and item['target']>=80):
            raise ValueError('Forbidden policy reached at runtime')
        if args.probability_only and (not item.get('pendingValue') or not item.get('disableStaticFallback')):
            raise ValueError('Probability-only run attempted a fixed-policy worker')
        if item.get('pendingValue'):
            # These workers have no static fallback and only read the policy.
            # Copy only policies whose fallback may create a query cache.
            shadow=Path(item['policy'])
            if item.get('cells',5)==5 and not item.get('disableStaticFallback'):
                shadow=shadows/(item['id']+'.policy.bin')
                if not shadow.exists():shutil.copyfile(item['policy'],shadow)
            print(json.dumps({'loadingPolicy':item['id']}),flush=True)
            worker=PolicyWorker({**item,'policy':str(shadow.resolve())})
            print(json.dumps({'policyReady':item['id']}),flush=True)
            return worker
        return factory_static(item)
    factory.transient_query_cache=True
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ['PATH']
    os.environ['TALLNUM_POLICY_CACHE_MB']=str(args.worker_cache_mb)
    if args.recovery:executor_class=RecoveryExecutor
    elif args.fresh:
        from .opening128_40 import ContractExecutor
        executor_class=ContractExecutor
    else:executor_class=RouteExecutor
    executor=executor_class(route,catalog,factory)
    records=[]
    try:
        for seed,old_record in list(baseline.items())[:args.limit]:
            file=args.out/'games'/f'{seed}{suffix}'
            if file.exists():result=read(file)
            else:
                if args.fresh:
                    try:result=fresh_play(seed,executor,args.action_budget)
                    except Exception as error:
                        interrupted=getattr(error,'interrupted_game',None)
                        if interrupted:
                            directory=args.out/'interruptions';directory.mkdir(exist_ok=True)
                            with gzip.open(directory/f'{seed}.json.gz','wt',encoding='utf-8') as stream:
                                json.dump(interrupted,stream,separators=(',',':'),allow_nan=False)
                        raise
                else:
                    old=read(EVIDENCE/'games'/f'{seed}.json')
                    boundary=next(i for i,s in enumerate(route['steps']) if s['before']==[[5120,1,False]])
                    result=play(old['replay'],old_record,executor,checkpoint=5120,start_stage=boundary,max_actions=args.action_budget)
                result['record'].update(bufferRescues=executor.buffer_rescue_events[:],
                                        templateCalls=executor.template_calls[:],
                                        handoffChecks=executor.handoff_events[:],
                                        liveSearch=executor.search_events[:],
                                        sixSingleExits=executor.single_exit_events[:])
                if args.recovery:result['record']['entryRecovery']=executor.recovery_events[:]
                if args.compress_replays:
                    temporary=file.with_suffix(file.suffix+'.tmp')
                    with gzip.open(temporary,'wt',encoding='utf-8',compresslevel=3) as stream:
                        json.dump(result,stream,ensure_ascii=False,separators=(',',':'),allow_nan=False)
                    temporary.replace(file)
                else:atomic_json(file,result)
            records.append(compact_record(result['record'],baseline))
            progress={**summary(records,baseline),'lastSeed':seed,'stage':records[-1]['stage'],
                      'updatedAt':time.time(),'complete':False}
            atomic_json(args.out/'progress.json',progress)
            print(json.dumps({k:v for k,v in progress.items() if k not in ('successesGained','successesLost')}),flush=True)
            del result
            if 'old' in locals():del old
    finally:
        executor.close()
        factory_static.cleanup()
    report=summary(records,baseline)
    atomic_json(args.out/'summary.json',report)
    # Stream large traces: do not hold all 100 games in memory.
    validation=args.out/('validation.json.gz' if args.compress_replays else 'validation.json')
    with (gzip.open(validation,'wt',encoding='utf-8',compresslevel=3) if args.compress_replays
          else validation.open('w',encoding='utf-8')) as stream:
        stream.write('{"reports":[{"replays":[')
        for index,record in enumerate(records):
            if index:stream.write(',')
            file=args.out/'games'/f'{record["seed"]}{suffix}'
            with (gzip.open(file,'rb') if args.compress_replays else file.open('rb')) as source:
                replay=next(ijson.items(source,'replay',use_float=True))
            json.dump(replay,stream,separators=(',',':'))
            del replay
        stream.write(']}]}')
    check=subprocess.run(['node','--max-old-space-size=512',str(ROOT/'automation/binary_random_check.mjs'),str(validation),'--discard-action-log'],capture_output=True,text=True)
    if check.returncode:raise RuntimeError(check.stdout+check.stderr)
    peak_limit=route.get('maxFive64Calls')
    primary_peak_calls=sum(step.get('kind')=='leaf' and step.get('policyCells')==5
                           and step.get('target')==64 for step in route['steps'])
    report.update(originalEngineCheck=read(str(validation)+'.engine-check.json'),
                  complete=len(records)==100, acceptancePassed=len(records)==100
                  and report['successes']>=85 and report.get('forbiddenTemplateCalls',0)==0
                  and (peak_limit is None or primary_peak_calls<=peak_limit))
    atomic_json(args.out/'summary.json',report)
    atomic_json(args.out/'progress.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
