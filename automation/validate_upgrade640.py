"""Paired seeded seven-cell tests of the original and six-cell upgraded routes."""
import argparse
import json
import os
from .upgrade640 import WORK
from .validation import validate
from .common import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempts',type=int,default=100)
    parser.add_argument('--names',nargs='+',default=['original','original-upgraded','optimized'])
    parser.add_argument('--seed',type=int,default=640001)
    parser.add_argument('--cache-mb',type=int,default=6144)
    args=parser.parse_args()
    if args.cache_mb<=0:parser.error('--cache-mb must be positive')
    os.environ.setdefault('TALLNUM_POLICY_CACHE_MB',str(args.cache_mb))
    catalog=json.loads((WORK/'catalog.json').read_text())
    for name in args.names:
        route=json.loads((WORK/(name+'-route.json')).read_text())
        print(json.dumps({'route':name,'status':'started'}),flush=True)
        report=validate(route,catalog,args.attempts,args.seed,max_actions=200000)
        atomic_json(WORK/(name+'-validation.json'),report)
        print(json.dumps({k:v for k,v in report.items() if k not in ('records','firstSuccessReplay')}),flush=True)


if __name__=='__main__':main()
