"""Read-only comparison of the two recorded fresh-game validations."""
import gzip
import json
from collections import Counter
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'automation/runs/no80-dynamic/validation-min24-v5-fresh'
NEW = ROOT / 'automation/runs/generic-plans/five-peak-dp-v20/10-10240/validation-100'


def main():
    routes = [json.loads((OLD / 'route.json').read_text()),
              json.loads((NEW / 'executed-route.json').read_text())]
    old = []
    for path in sorted((OLD / 'games').glob('*.json.gz')):
        with gzip.open(path, 'rt', encoding='utf-8') as stream:
            old.append(json.load(stream)['record'])
    new = json.loads((NEW / 'summary.json').read_text())['records']
    old_by_seed = {r['seed']: r for r in old}
    paired = Counter((old_by_seed[r['seed']]['outcome'], r['outcome']) for r in new)
    result = {'pairedOutcomes': {f'{a}->{b}': n for (a, b), n in paired.items()},
              'sameSeedSet': set(old_by_seed) == {r['seed'] for r in new}, 'routes': {}}
    for label, route, records in zip(('old89', 'new51'), routes, (old, new)):
        failures = [r for r in records if r['outcome'] != 'success']
        grouped = Counter()
        detail = []
        for r in failures:
            s = route['steps'][r['stage']]
            prefix = s.get('before', [])
            available = route['cells'] - sum(b[1] for b in prefix)
            key = f"{r['reason']} / {s.get('template', s['kind'])}"
            grouped[key] += 1
            detail.append({'seed': r['seed'], 'stageOneBased': r['stage'] + 1,
                           'reason': r['reason'], 'template': s.get('template'),
                           'before': prefix, 'availableCells': available,
                           'drops': r['drops'], 'milestones': r['milestones'],
                           'failureContext': r.get('failureContext'),
                           'oldOutcome': old_by_seed[r['seed']]['outcome']})
        result['routes'][label] = {
            'stages': len(route['steps']),
            'leafCounts': dict(Counter(s['template'] for s in route['steps'] if s['kind'] == 'leaf')),
            'failureTemplates': dict(grouped), 'failures': detail,
            'failedBeforeFirst5120': sum('5120' not in r['milestones'] for r in failures),
            'failedBeforeFirst1280': sum('1280' not in r['milestones'] for r in failures),
            'fiveCellFailuresWithAtLeastSixAvailable': sum(
                d['template'] is not None and d['template'].startswith('5:') and d['availableCells'] >= 6
                for d in detail),
            'bufferRescueEvents': sum(len(r.get('bufferRescues', [])) for r in records),
            'medianDropsSuccessful': median(r['drops'] for r in records if r['outcome'] == 'success'),
            'medianDropsToFirst5120': median(r['milestones']['5120'] for r in records if '5120' in r['milestones'])}
    out = ROOT / 'automation/runs/generic-plans/comparison-89-vs-51'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    for label, report in result['routes'].items():
        print(label, json.dumps({k: v for k, v in report.items() if k != 'failures'}, ensure_ascii=False))
    print('paired', result['pairedOutcomes'])
    print('same seeds', result['sameSeedSet'])
    print('new failure stages', dict(Counter(d['stageOneBased'] for d in result['routes']['new51']['failures'])))


if __name__ == '__main__':
    main()
