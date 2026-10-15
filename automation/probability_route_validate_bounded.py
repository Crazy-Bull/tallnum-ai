"""Resume probability-only tests with a bounded worker memory budget.

Only immutable worker eviction changes. Routes, seeds, decisions, action
budgets, and already recorded games remain unchanged.
"""
import argparse
import os
from pathlib import Path
import sys

from . import probability_route_validate as validation
from .common import atomic_json, fingerprint


def main():
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--worker-cache-mb',type=int,default=768)
    parser.add_argument('--out',type=Path,required=True)
    options,remaining=parser.parse_known_args()
    if not 64<=options.worker_cache_mb<=4096:parser.error('worker cache must be 64–4096 MiB')
    options.out.mkdir(parents=True,exist_ok=True)
    atomic_json(options.out/'resource-configuration.json',
                {'workerCacheMb':options.worker_cache_mb,'sourceSha256':fingerprint(__file__),
                 'affectsPolicyDecisions':False,'reason':'resume after infrastructure memory exhaustion'})
    original=validation.PolicyWorker
    def bounded(item):
        os.environ['TALLNUM_POLICY_CACHE_MB']=str(options.worker_cache_mb)
        return original(item)
    validation.PolicyWorker=bounded
    sys.argv=[sys.argv[0],*remaining,'--out',str(options.out)]
    validation.main()


if __name__=='__main__':main()
