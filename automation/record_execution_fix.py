"""Record a completed probability-only repair test and its exact identity."""
import argparse
from collections import Counter
import json
from pathlib import Path
from statistics import mean

from .common import atomic_json, fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--registry', type=Path)
    args = parser.parse_args()
    directory = args.directory
    tests = directory / 'validation-100'
    route = json.loads((directory / 'route.json').read_text())
    plan = json.loads((directory / 'planning-report.json').read_text())
    config = json.loads((tests / 'configuration.json').read_text())
    summary = json.loads((tests / 'summary.json').read_text())
    digest = fingerprint(directory / 'route.json')
    if (digest != fingerprint(tests / 'executed-route.json') or config['routeSha256'] != digest
            or config['catalogSha256'] != fingerprint(args.catalog)
            or not config['probabilityOnly'] or config['forcedDraws']
            or not summary['complete'] or summary['completed'] != 100
            or not summary['originalEngineCheck']['seededRngParity']
            or summary['originalEngineCheck']['games'] != 100):
        raise ValueError('Repair evidence is incomplete or identities do not match')
    root = Path(__file__).resolve().parents[1]
    for name, source in config['sources'].items():
        if fingerprint(root / 'automation' / name) != source:
            raise ValueError('Tested runtime source changed: ' + name)
    counts = Counter(s['template'] for s in route['steps'] if s['kind'] == 'leaf')
    peak = max((int(k.split(':')[1]) for k in counts if k.startswith('5:')), default=0)
    calls = sum(n for k, n in counts.items() if k.startswith(f'5:{peak}:'))
    success = [r for r in summary['records'] if r['outcome'] == 'success']
    actual = lambda r, goal: sum(c['cells'] == 5 and c['target'] == goal for c in r['templateCalls'])
    entry = {'target': route['target'], 'cells': route['cells'], 'routeSha256': digest,
             'attempts': 100, 'successes': summary['successes'], 'successRate': summary['successRate'],
             'unfinished': sum(r['outcome'] == 'limit' for r in summary['records']),
             'maximumSuccessfulFive64Calls': max((actual(r, 64) for r in success), default=0),
             'maximumSuccessfulHighestFiveCellCalls': max((actual(r, peak) for r in success), default=0),
             'originalEngineVerified': True, 'probabilityOnly': True, 'forcedDraws': False,
             'actionBudget': config['actionBudget'], 'sources': config['sources'],
             'failureReasons': summary['failureReasons'], 'summary': str((tests / 'summary.json').resolve())}
    result = {'maximumFiveCellTarget': peak, 'highestFiveCellCalls': calls,
              'stages': len(route['steps']), 'leafCounts': dict(counts),
              'bufferRescueEvents': sum(len(r['bufferRescues']) for r in summary['records']),
              'connectionAlignments': sum(len(r.get('connectionAlignments',[])) for r in summary['records']),
              'meanDropsSuccess': mean(r['drops'] for r in success) if success else None,
              'validation': entry,
              'structuralAcceptancePassed': peak == plan['maximumFiveCellTarget']
                                            and calls == plan['highestFiveCellCalls']
                                            and len(route['steps']) == plan['steps'],
              'acceptancePassed': peak == plan['maximumFiveCellTarget']
                                  and calls == plan['highestFiveCellCalls']
                                  and len(route['steps']) == plan['steps']
                                  and summary['successes'] >= 85 and entry['unfinished'] == 0}
    atomic_json(directory / 'repair-results.json', result)
    atomic_json(directory / 'highest-five-cell-stages.json',
                [{'stage': i + 1, **s} for i, s in enumerate(route['steps'])
                 if s['kind'] == 'leaf' and s['policyCells'] == 5 and s['target'] == peak])
    if args.registry is not None:
        registry = json.loads(args.registry.read_text()) if args.registry.exists() else {}
        if registry.get('catalogSha256') not in (None, fingerprint(args.catalog)):
            raise ValueError('Registry belongs to a different catalog')
        previous = [v for v in registry.get('validations', []) if v['routeSha256'] != digest]
        atomic_json(args.registry, {'catalogSha256': fingerprint(args.catalog),
                                   'validations': previous + [entry]})
    print(json.dumps({k: v for k, v in result.items() if k != 'leafCounts'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
