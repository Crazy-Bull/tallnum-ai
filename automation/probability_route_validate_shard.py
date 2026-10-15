"""Disjoint seed partitions for the same probability-only test cohort."""
import argparse
import gzip
import json
import os
from pathlib import Path

from .common import atomic_json,fingerprint
from .entry_recovery import RecoveryExecutor
from .library import PolicyWorker
from .no80_full_game import fresh_play

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--index',type=int,required=True)
    parser.add_argument('--partitions',type=int,default=4)
    parser.add_argument('--worker-cache-mb',type=int,default=512)
    args=parser.parse_args()
    if not 0<=args.index<args.partitions<=16:parser.error('Invalid partition')
    config=json.loads((args.out/'configuration.json').read_text())
    route=json.loads((args.out/'executed-route.json').read_text())
    catalog=json.loads(args.catalog.read_text())
    if fingerprint(args.catalog)!=config['catalogSha256']:raise ValueError('Catalog changed')
    for name,digest in config['sources'].items():
        if fingerprint(ROOT/'automation'/name)!=digest:raise ValueError('Simulation source changed: '+name)
    used={s['policy'] for s in route['steps'] if s['kind']=='leaf'}
    used.update(i for ids in route.get('bufferRescuePolicies',{}).values() for i in ids)
    catalog={'policies':[p for p in catalog['policies'] if p['id'] in used]}
    def factory(item):
        if (not item.get('pendingValue') or not item.get('disableStaticFallback')
                or item.get('cells',5)<5 or item['target']<24):
            raise ValueError('Invalid probability-only policy')
        return PolicyWorker(item)
    factory.transient_query_cache=True
    os.environ['PATH']=str(ROOT/'.tools/msys64/ucrt64/bin')+os.pathsep+os.environ['PATH']
    os.environ['TALLNUM_POLICY_CACHE_MB']=str(args.worker_cache_mb)
    atomic_json(args.out/f'partition-{args.index}-configuration.json',
                {'index':args.index,'partitions':args.partitions,'workerCacheMb':args.worker_cache_mb,
                 'sourceSha256':fingerprint(__file__),'baseConfigurationSha256':fingerprint(args.out/'configuration.json')})
    executor=RecoveryExecutor(route,catalog,factory)
    try:
        for index,seed in enumerate(config['seeds']):
            if index%args.partitions!=args.index:continue
            path=args.out/'games'/f'{seed}.json.gz'
            if path.exists():continue
            try:result=fresh_play(seed,executor,config['actionBudget'])
            except Exception as error:
                atomic_json(args.out/f'interruption-partition-{args.index}.json',
                            getattr(error,'interrupted_game',{'reason':str(error)}))
                raise
            result['record'].update(templateCalls=executor.template_calls[:],
                                   recoveryEvents=executor.recovery_events[:],
                                   bufferRescues=executor.buffer_rescue_events[:])
            temporary=path.with_suffix('.tmp')
            with gzip.open(temporary,'wt',encoding='utf-8',compresslevel=3) as stream:
                json.dump(result,stream,separators=(',',':'),allow_nan=False)
            temporary.replace(path)
            progress={k:result['record'][k] for k in ('seed','outcome','reason','stage','drops')}
            atomic_json(args.out/f'partition-{args.index}-progress.json',progress)
            print(json.dumps(progress),flush=True)
            del result
    finally:executor.close()


if __name__=='__main__':main()
