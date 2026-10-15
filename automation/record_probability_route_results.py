"""Record route acceptance and bind full-game evidence by exact route hash."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .common import atomic_json,fingerprint


def record(plans,tests,catalog,out,registry=None):
    plans,tests,out=map(Path,(plans,tests,out))
    targets=(8192,10240,12288);results=[];validations=[]
    for target in targets:
        folder=plans/f'10-{target}'
        route=json.loads((folder/'route.json').read_text(encoding='utf-8'))
        report=json.loads((folder/'planning-report.json').read_text(encoding='utf-8'))
        counts=Counter(s['template'] for s in route['steps'] if s['kind']=='leaf')
        peak=max(int(k.split(':')[1]) for k in counts if k.startswith('5:'))
        calls=sum(n for k,n in counts.items() if k.startswith(f'5:{peak}:'))
        row={'target':target,'cells':route['cells'],'highestFiveCellTarget':peak,
             'highestFiveCellCalls':calls,'stages':len(route['steps']),'leafCounts':dict(counts),
             'route':str((folder/'route.json').resolve()),'routeSha256':fingerprint(folder/'route.json'),
             'lexicographicOrderProvenInScope':report['lexicographicOrderProvenInScope']}
        phase_calls=[{'stage':index+1,**step} for index,step in enumerate(route['steps'])
                     if step['kind']=='leaf' and step['policyCells']==5 and step['target']==peak]
        atomic_json(folder/'highest-five-cell-stages.json',phase_calls)
        test_folder=tests/f'10-{target}'/'validation-100'
        config=json.loads((test_folder/'configuration.json').read_text())
        summary_path=test_folder/'summary.json'
        if summary_path.exists():
            summary=json.loads(summary_path.read_text())
            if fingerprint(test_folder/'executed-route.json')!=row['routeSha256']:
                raise ValueError(f'Tested route differs from the published {target} route')
            if not summary['complete'] or summary['completed']!=100:
                raise ValueError('Incomplete cohort')
            if not summary['originalEngineCheck']['seededRngParity']:
                raise ValueError('Original-engine check failed')
            successes=[r for r in summary['records'] if r['outcome']=='success']
            count=lambda r,goal:sum(c['cells']==5 and c['target']==goal for c in r['templateCalls'])
            validation={'target':target,'cells':route['cells'],'routeSha256':row['routeSha256'],
                        'attempts':100,'successes':summary['successes'],'successRate':summary['successRate'],
                        'unfinished':sum(r['outcome']=='limit' for r in summary['records']),
                        'maximumSuccessfulFive64Calls':max((count(r,64) for r in successes),default=0),
                        'maximumSuccessfulHighestFiveCellCalls':max((count(r,peak) for r in successes),default=0),
                        'originalEngineVerified':summary['originalEngineCheck']['games']==100,
                        'probabilityOnly':config['probabilityOnly'],'forcedDraws':config['forcedDraws'],
                        'actionBudget':config['actionBudget'],'sources':config['sources'],
                        'failureReasons':summary['failureReasons'],'summary':str(summary_path.resolve())}
            row['validation']=validation
            validations.append(validation)
        else:
            row['validation']={'complete':False,'recordedGames':len(list((test_folder/'games').glob('*.json.gz')))}
        results.append(row)
    by_target={row['target']:row for row in results}
    acceptance={'10240HighestFive64':by_target[10240]['highestFiveCellTarget']==64,
                '10240AtMost14Calls':by_target[10240]['highestFiveCellCalls']<=14,
                '12288HighestFive80':by_target[12288]['highestFiveCellTarget']==80,
                '8192NoMoreStagesThan10240':by_target[8192]['stages']<=by_target[10240]['stages']}
    if not all(acceptance.values()):raise ValueError('Route acceptance failed')
    result={'structuralAcceptancePassed':True,'requirements':acceptance,'results':results,
            'allHundredGameTestsComplete':len(validations)==3,'catalogSha256':fingerprint(catalog)}
    atomic_json(out,result)
    if registry is not None and len(validations)==3:
        atomic_json(registry,{'catalogSha256':fingerprint(catalog),'validations':validations})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plans',type=Path,required=True)
    parser.add_argument('--tests',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--registry',type=Path)
    args=parser.parse_args()
    result=record(args.plans,args.tests,args.catalog,args.out,args.registry)
    print(json.dumps({'structuralAcceptancePassed':result['structuralAcceptancePassed'],
                      'allHundredGameTestsComplete':result['allHundredGameTestsComplete']}))


if __name__=='__main__':main()
